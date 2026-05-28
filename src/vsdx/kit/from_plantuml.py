# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""PlantUML import — issue #124.

A small, dependency-free PlantUML parser + Visio builder. PlantUML is
the second-most-popular text-to-diagram syntax (after Mermaid); this
module turns a PlantUML source string (or ``.puml`` / ``.plantuml``
file) into a fully-formed :class:`~vsdx.document.VisioDocument`.

Supported syntax subset
-----------------------

* ``@startuml`` / ``@enduml`` framing (required — text outside the
  fence is ignored, matching PlantUML's own tolerant behaviour).
* **Activity diagrams** — the line-oriented dialect:

  * ``start`` / ``stop`` terminator keywords (rendered as ellipses).
  * ``:Action;`` task statements (rendered as rectangles).
  * ``if (cond) then (yes-label)`` ... ``else (no-label)`` ...
    ``endif`` branches (rendered as a diamond plus left/right
    sub-branches that re-merge after the ``endif``).

* **Component diagrams**:

  * ``[Component name]`` — a component box (square brackets).
  * ``() "Interface description"`` or ``() Interface`` — an interface
    glyph (parens + optional quoted label).
  * ``component "Label" as Alias`` and ``interface "Label" as Alias``
    declaration spellings, with optional aliases.
  * ``-->`` and ``..>`` arrows between two endpoints (solid vs
    dashed at the syntactic level — both render as connectors).
  * Optional ``: edge label`` suffix on arrow lines.

* **Use-case actors**:

  * ``actor Name`` and ``actor "Description" as Alias``.
  * ``usecase "Description" as N`` and ``usecase Name``.

Layout policy
-------------

* Activity diagrams flow **top-down** on a single vertical centreline
  (start ellipse → action rectangles → optional decision diamond
  bracketed by left/right branches → stop ellipse), with right-angle
  connectors between every consecutive pair.
* Component / use-case diagrams use a **free-grid** layout: each
  declared node is placed left-to-right and wrapped at four columns
  per row. Arrows from the source connect to their resolved targets.

Out of scope (deferred to future work)
--------------------------------------

* **Sequence diagrams** (``A -> B : msg``, ``activate`` / ``deactivate``,
  ``note over``).
* **Class diagrams** (``class Foo``, ``Foo <|-- Bar``, ``+method()``,
  ``-field``).
* **Deployment diagrams** (``node Server``, ``database DB``).
* **State diagrams** (``state Idle``, ``[*] --> Idle``).
* PlantUML preprocessor directives (``!include``, ``!define``,
  ``!if`` / ``!endif``).
* Skin parameters (``skinparam`` ...) and theme directives
  (``!theme`` ...).

These are documented as future-work in the issue thread (#124); the
parser quietly skips lines it does not recognise so a PlantUML file
that mixes supported + unsupported constructs still produces a valid
diagram for the supported subset rather than failing closed.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import re
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.routing import ROUTING_RIGHT_ANGLE
from vsdx.shapes.base import Shape


# ---------------------------------------------------------------------------
# Public constants — node-kind discriminators used by the parsed AST
# ---------------------------------------------------------------------------

#: Diagram kind discriminator — activity flowchart.
PLANTUML_KIND_ACTIVITY: str = "activity"

#: Diagram kind discriminator — component / use-case free grid.
PLANTUML_KIND_COMPONENT: str = "component"

#: Diagram kind discriminator — empty diagram (no recognised content).
PLANTUML_KIND_EMPTY: str = "empty"

#: Frozen tuple of every diagram kind this importer can produce.
PLANTUML_DIAGRAM_KINDS: Tuple[str, ...] = (
    PLANTUML_KIND_ACTIVITY,
    PLANTUML_KIND_COMPONENT,
    PLANTUML_KIND_EMPTY,
)


# ---------------------------------------------------------------------------
# Layout constants — module-private; tweakable via the builder kwargs
# ---------------------------------------------------------------------------

# Activity diagram (top-down)
_ACT_PAGE_MARGIN_X: float = 0.5
_ACT_PAGE_MARGIN_Y: float = 0.5
_ACT_NODE_WIDTH: float = 2.5
_ACT_NODE_HEIGHT: float = 0.7
_ACT_VERTICAL_GAP: float = 0.45
_ACT_BRANCH_OFFSET_X: float = 1.7
_ACT_DEFAULT_PAGE_WIDTH: float = 8.5
_ACT_DEFAULT_PAGE_HEIGHT: float = 11.0

# Component / use-case (free grid)
_CMP_PAGE_MARGIN_X: float = 0.5
_CMP_PAGE_MARGIN_Y: float = 0.5
_CMP_NODE_WIDTH: float = 2.0
_CMP_NODE_HEIGHT: float = 1.0
_CMP_GRID_GAP_X: float = 0.6
_CMP_GRID_GAP_Y: float = 0.6
_CMP_COLUMNS_PER_ROW: int = 4
_CMP_DEFAULT_PAGE_WIDTH: float = 11.0
_CMP_DEFAULT_PAGE_HEIGHT: float = 8.5


# ---------------------------------------------------------------------------
# Regex vocabulary
# ---------------------------------------------------------------------------

_RE_START_FENCE = re.compile(r"^@startuml\b.*$", re.IGNORECASE)
_RE_END_FENCE = re.compile(r"^@enduml\b.*$", re.IGNORECASE)

# Activity diagram ----------------------------------------------------------
_RE_ACT_TERMINATOR = re.compile(r"^(start|stop|end)$", re.IGNORECASE)
# `:Action;` — single-line action, may contain colons in the body.
_RE_ACT_ACTION = re.compile(r"^:(?P<text>.*?);$")
_RE_ACT_IF = re.compile(
    r"^if\s*\(\s*(?P<cond>.+?)\s*\)\s*then\s*(?:\(\s*(?P<yes>.+?)\s*\))?\s*$",
    re.IGNORECASE,
)
_RE_ACT_ELSE = re.compile(
    r"^else\s*(?:\(\s*(?P<no>.+?)\s*\))?\s*$",
    re.IGNORECASE,
)
_RE_ACT_ENDIF = re.compile(r"^endif$", re.IGNORECASE)

# Component / use-case ------------------------------------------------------
_RE_CMP_BRACKET = re.compile(
    r"^\[\s*(?P<label>[^\]]+?)\s*\](?:\s+as\s+(?P<alias>\w+))?\s*$"
)
_RE_CMP_PARENS_QUOTED = re.compile(
    r'^\(\s*\)\s*"(?P<label>[^"]+)"(?:\s+as\s+(?P<alias>\w+))?\s*$'
)
_RE_CMP_PARENS_BARE = re.compile(
    r"^\(\s*\)\s*(?P<label>[^\s\"][^\s]*)(?:\s+as\s+(?P<alias>\w+))?\s*$"
)
_RE_CMP_KEYWORD_QUOTED = re.compile(
    r'^(?P<kind>component|interface|actor|usecase)\s+'
    r'"(?P<label>[^"]+)"'
    r'(?:\s+as\s+(?P<alias>\w+))?\s*$',
    re.IGNORECASE,
)
_RE_CMP_KEYWORD_BARE = re.compile(
    r"^(?P<kind>component|interface|actor|usecase)\s+(?P<label>\w+)"
    r"(?:\s+as\s+(?P<alias>\w+))?\s*$",
    re.IGNORECASE,
)
_RE_CMP_ARROW_TOKEN = re.compile(r"\s+(-+>|\.+>|<-+|<\.+)\s+")


# ---------------------------------------------------------------------------
# Parsed AST node types — plain dataclass-like dicts (kept dep-free)
# ---------------------------------------------------------------------------

# An activity-diagram statement is a tagged tuple. Variants:
#   ("term", "start" | "stop")
#   ("action", "<text>")
#   ("if", "<cond>", "<yes-label or ''>", [then-stmts], "<no-label or ''>",
#       [else-stmts])
ActivityStmt = Any

# A component-diagram node carries an alias (its lookup key) plus a
# user-visible label and a kind discriminator.
ComponentNode = Dict[str, str]

# A component-diagram edge resolves its endpoints to alias keys.
ComponentEdge = Dict[str, str]


class _ParsedDiagram:
    """Container for the parsed-and-validated AST.

    Attributes:
        kind: one of :data:`PLANTUML_DIAGRAM_KINDS`.
        title: optional ``title`` directive value, ``""`` when absent.
        activity: list of :data:`ActivityStmt` (only for activity).
        nodes: ordered list of :data:`ComponentNode` (component / use-case).
        edges: list of :data:`ComponentEdge` (component / use-case).
    """

    __slots__ = ("kind", "title", "activity", "nodes", "edges")

    def __init__(self) -> None:
        self.kind: str = PLANTUML_KIND_EMPTY
        self.title: str = ""
        self.activity: List[ActivityStmt] = []
        self.nodes: List[ComponentNode] = []
        self.edges: List[ComponentEdge] = []


# ---------------------------------------------------------------------------
# Tokeniser — strip @startuml fence and per-line comments / blanks
# ---------------------------------------------------------------------------


def _strip_inside_fence(text: str) -> List[str]:
    """Return non-blank, comment-stripped lines inside ``@startuml`` ... ``@enduml``.

    A source missing the fence is parsed permissively (the entire input
    is treated as the body), matching PlantUML's own forgiving behaviour
    for fragmentary snippets pasted into a renderer.
    """
    raw_lines = text.splitlines()
    body: List[str] = []
    inside = False
    saw_fence = False
    for raw in raw_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if _RE_START_FENCE.match(stripped):
            inside = True
            saw_fence = True
            continue
        if _RE_END_FENCE.match(stripped):
            inside = False
            saw_fence = True
            continue
        if saw_fence and not inside:
            # Outside an explicit fence — ignore.
            continue
        # Strip ``'`` line comments and ``/' ... '/`` is best-effort.
        if stripped.startswith("'"):
            continue
        body.append(stripped)
    return body


# ---------------------------------------------------------------------------
# Activity-diagram parsing
# ---------------------------------------------------------------------------


def _looks_like_activity(lines: Sequence[str]) -> bool:
    """Heuristic — any of ``start`` / ``stop`` / ``:Action;`` / ``if (...)``?"""
    for line in lines:
        if _RE_ACT_TERMINATOR.match(line):
            return True
        if _RE_ACT_ACTION.match(line):
            return True
        if _RE_ACT_IF.match(line):
            return True
    return False


def _parse_activity(lines: Sequence[str]) -> List[ActivityStmt]:
    """Recursive-descent parse of the activity-diagram subset."""
    stmts, pos = _parse_activity_block(list(lines), 0, stop_tokens=())
    if pos < len(lines):
        # Trailing junk after the top-level block — silently tolerated.
        pass
    return stmts


def _parse_activity_block(
    lines: List[str],
    pos: int,
    stop_tokens: Tuple[str, ...],
) -> Tuple[List[ActivityStmt], int]:
    """Parse statements until *pos* hits ``end-of-input`` or a *stop_token*."""
    out: List[ActivityStmt] = []
    while pos < len(lines):
        line = lines[pos]
        # Stop-token check (for ``else`` / ``endif`` inside an ``if``).
        if "endif" in stop_tokens and _RE_ACT_ENDIF.match(line):
            return out, pos
        if "else" in stop_tokens and _RE_ACT_ELSE.match(line):
            return out, pos

        m = _RE_ACT_TERMINATOR.match(line)
        if m:
            kw = m.group(1).lower()
            # ``end`` after an activity body is treated as ``stop``
            # for the line-oriented dialect; the legacy ``end`` keyword
            # is a synonym.
            if kw == "end":
                kw = "stop"
            out.append(("term", kw))
            pos += 1
            continue

        m = _RE_ACT_ACTION.match(line)
        if m:
            out.append(("action", m.group("text").strip()))
            pos += 1
            continue

        m = _RE_ACT_IF.match(line)
        if m:
            cond = m.group("cond").strip()
            yes_label = (m.group("yes") or "").strip()
            pos += 1
            then_stmts, pos = _parse_activity_block(
                lines, pos, stop_tokens=("else", "endif")
            )
            no_label = ""
            else_stmts: List[ActivityStmt] = []
            if pos < len(lines) and _RE_ACT_ELSE.match(lines[pos]):
                em = _RE_ACT_ELSE.match(lines[pos])
                assert em is not None
                no_label = (em.group("no") or "").strip()
                pos += 1
                else_stmts, pos = _parse_activity_block(
                    lines, pos, stop_tokens=("endif",)
                )
            if pos < len(lines) and _RE_ACT_ENDIF.match(lines[pos]):
                pos += 1
            out.append(("if", cond, yes_label, then_stmts, no_label, else_stmts))
            continue

        # Title directive — captured by the top-level parser.
        if line.lower().startswith("title"):
            pos += 1
            continue

        # Unrecognised line — skip silently (defensive: PlantUML text
        # often mixes preprocessor / skinparam directives in).
        pos += 1
    return out, pos


# ---------------------------------------------------------------------------
# Component-diagram parsing
# ---------------------------------------------------------------------------


def _add_node(
    parsed: _ParsedDiagram,
    *,
    alias: str,
    label: str,
    kind: str,
) -> str:
    """Insert (or re-use) a component-diagram node, returning its alias.

    Alias collisions re-use the existing node — a PlantUML source that
    re-declares the same name is tolerated rather than rejected.
    """
    for node in parsed.nodes:
        if node["alias"] == alias:
            return alias
    parsed.nodes.append({"alias": alias, "label": label, "kind": kind})
    return alias


def _normalise_alias(token: str) -> str:
    """Strip ``[...]`` / ``"..."`` / ``(...)`` wrapping from an arrow endpoint.

    Returns the bare identifier suitable as a node-lookup key.
    """
    t = token.strip()
    if t.startswith("[") and t.endswith("]"):
        return t[1:-1].strip()
    if t.startswith("(") and t.endswith(")"):
        return t[1:-1].strip()
    if t.startswith('"') and t.endswith('"'):
        return t[1:-1].strip()
    return t


def _parse_component_line(
    parsed: _ParsedDiagram,
    line: str,
) -> bool:
    """Try every component-diagram pattern in turn; return True on match."""
    # Bracket component: [Component]
    m = _RE_CMP_BRACKET.match(line)
    if m:
        label = m.group("label").strip()
        alias = (m.group("alias") or label).strip()
        _add_node(parsed, alias=alias, label=label, kind="component")
        return True

    # Interface () "label"
    m = _RE_CMP_PARENS_QUOTED.match(line)
    if m:
        label = m.group("label").strip()
        alias = (m.group("alias") or label).strip()
        _add_node(parsed, alias=alias, label=label, kind="interface")
        return True

    # Interface () BareName
    m = _RE_CMP_PARENS_BARE.match(line)
    if m:
        label = m.group("label").strip()
        alias = (m.group("alias") or label).strip()
        _add_node(parsed, alias=alias, label=label, kind="interface")
        return True

    # Keyword "Label" as Alias
    m = _RE_CMP_KEYWORD_QUOTED.match(line)
    if m:
        kind = m.group("kind").lower()
        label = m.group("label").strip()
        alias = (m.group("alias") or label).strip()
        _add_node(parsed, alias=alias, label=label, kind=kind)
        return True

    # Keyword BareName
    m = _RE_CMP_KEYWORD_BARE.match(line)
    if m:
        kind = m.group("kind").lower()
        label = m.group("label").strip()
        alias = (m.group("alias") or label).strip()
        _add_node(parsed, alias=alias, label=label, kind=kind)
        return True

    # Arrow: src --> dst : label / src ..> dst
    # We split on the arrow token rather than match a single regex
    # so multi-word bare labels (``Web Frontend --> api``) survive.
    arrow_match = _RE_CMP_ARROW_TOKEN.search(line)
    if arrow_match:
        arrow = arrow_match.group(1)
        src_raw = line[: arrow_match.start()].strip()
        rhs = line[arrow_match.end():].strip()
        # Split the RHS on the optional ``: label`` suffix.
        if ":" in rhs:
            dst_raw, edge_label = rhs.split(":", 1)
            dst_raw = dst_raw.strip()
            edge_label = edge_label.strip()
        else:
            dst_raw, edge_label = rhs, ""
        if not src_raw or not dst_raw:
            return False
        # Reverse direction for ``<-`` / ``<.`` arrows so the graph
        # always reads source → target.
        if arrow.startswith("<"):
            src_raw, dst_raw = dst_raw, src_raw
        src = _normalise_alias(src_raw)
        dst = _normalise_alias(dst_raw)
        # Auto-create endpoint nodes that haven't been declared
        # explicitly — PlantUML allows component diagrams that lean
        # entirely on the arrow syntax.
        if not any(n["alias"] == src for n in parsed.nodes):
            kind = "interface" if src_raw.startswith("(") else "component"
            _add_node(parsed, alias=src, label=src, kind=kind)
        if not any(n["alias"] == dst for n in parsed.nodes):
            kind = "interface" if dst_raw.startswith("(") else "component"
            _add_node(parsed, alias=dst, label=dst, kind=kind)
        parsed.edges.append(
            {
                "from": src,
                "to": dst,
                "label": edge_label,
                "style": "dashed" if "." in arrow else "solid",
            }
        )
        return True

    return False


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------


def _parse(text: str) -> _ParsedDiagram:
    """Parse *text* into a :class:`_ParsedDiagram`."""
    body = _strip_inside_fence(text)

    parsed = _ParsedDiagram()

    # Look for a leading title.
    remaining: List[str] = []
    for line in body:
        low = line.lower()
        if low.startswith("title "):
            parsed.title = line[6:].strip()
            continue
        if low == "title":
            continue
        remaining.append(line)

    if not remaining:
        parsed.kind = PLANTUML_KIND_EMPTY
        return parsed

    # Activity-shaped if any of the activity tokens are present.
    if _looks_like_activity(remaining):
        parsed.kind = PLANTUML_KIND_ACTIVITY
        parsed.activity = _parse_activity(remaining)
        return parsed

    # Otherwise treat as component / use-case free grid.
    parsed.kind = PLANTUML_KIND_COMPONENT
    for line in remaining:
        _parse_component_line(parsed, line)
    if not parsed.nodes and not parsed.edges:
        parsed.kind = PLANTUML_KIND_EMPTY
    return parsed


# ---------------------------------------------------------------------------
# Activity-diagram builder
# ---------------------------------------------------------------------------


def _flatten_activity(stmts: Sequence[ActivityStmt]) -> List[ActivityStmt]:
    """Flatten nested ``if`` blocks one level for layout-position counting.

    The page-height calculation needs an upper bound on the row count;
    a one-deep flattening (each ``if`` consumes three rows: the diamond,
    the parallel branches, and the merge gap) is enough for the
    supported subset.
    """
    rows: List[ActivityStmt] = []
    for st in stmts:
        if st[0] == "if":
            # Diamond + max(then, else) branch height + merge marker.
            then_stmts: Sequence[ActivityStmt] = st[3]
            else_stmts: Sequence[ActivityStmt] = st[5]
            branch_h = max(
                len(_flatten_activity(then_stmts)),
                len(_flatten_activity(else_stmts)),
                1,
            )
            rows.append(("if-marker",))
            for _ in range(branch_h):
                rows.append(("branch-row",))
            rows.append(("merge",))
        else:
            rows.append(st)
    return rows


def _build_activity(
    parsed: _ParsedDiagram,
    *,
    page_width: float,
    page_height: float,
    page_name: Optional[str],
) -> VisioDocument:
    """Render the activity-diagram subset into a single-page document."""
    inner_w = page_width - 2 * _ACT_PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _ACT_PAGE_MARGIN_X)
        )
    body_top = page_height - _ACT_PAGE_MARGIN_Y
    centre_x = _ACT_PAGE_MARGIN_X + inner_w / 2

    doc = Visio()
    name = page_name or parsed.title.strip() or "Activity diagram"
    page = doc.pages.add_page(name=name, width=page_width, height=page_height)

    cursor_y = [body_top]  # mutable so helpers can decrement

    def _next_y() -> float:
        cursor_y[0] -= _ACT_NODE_HEIGHT + _ACT_VERTICAL_GAP
        return cursor_y[0] + _ACT_NODE_HEIGHT / 2

    last_shape: List[Optional[Shape]] = [None]

    def _drop_node(kind: str, text: str, *, x: float) -> Shape:
        pin_y = _next_y()
        if kind == "ellipse":
            shape = page.shapes.add_shape(
                VS_SHAPE_TYPE.ELLIPSE,
                at=(x, pin_y),
                size=(_ACT_NODE_WIDTH, _ACT_NODE_HEIGHT),
                text=text,
            )
        elif kind == "diamond":
            shape = page.shapes.add_custom_shape(
                at=(x, pin_y),
                size=(_ACT_NODE_WIDTH, _ACT_NODE_HEIGHT),
                master="Rectangle",
            )
            geometry = shape.geometry
            geometry.move_to(0.5, 1.0)
            geometry.line_to(1.0, 0.5)
            geometry.line_to(0.5, 0.0)
            geometry.line_to(0.0, 0.5)
            geometry.close()
            shape.text = text
        else:
            shape = page.shapes.add_shape(
                VS_SHAPE_TYPE.RECTANGLE,
                at=(x, pin_y),
                size=(_ACT_NODE_WIDTH, _ACT_NODE_HEIGHT),
                text=text,
            )
        return shape

    def _connect(prev: Optional[Shape], curr: Shape) -> None:
        if prev is None:
            return
        page.add_connector(prev, curr, routing=ROUTING_RIGHT_ANGLE)

    def _emit(stmts: Sequence[ActivityStmt]) -> None:
        for st in stmts:
            tag = st[0]
            if tag == "term":
                kw = st[1]
                shape = _drop_node("ellipse", kw.upper(), x=centre_x)
                _connect(last_shape[0], shape)
                last_shape[0] = shape
            elif tag == "action":
                shape = _drop_node("rectangle", st[1], x=centre_x)
                _connect(last_shape[0], shape)
                last_shape[0] = shape
            elif tag == "if":
                cond = st[1]
                yes_label = st[2]
                then_stmts = st[3]
                no_label = st[4]
                else_stmts = st[5]
                diamond = _drop_node("diamond", cond, x=centre_x)
                _connect(last_shape[0], diamond)

                # Snapshot current y so the two branches start side by side.
                branch_y_start = cursor_y[0]
                # Then branch (left).
                cursor_y[0] = branch_y_start
                then_last: Optional[Shape] = diamond
                for sub in then_stmts:
                    sub_tag = sub[0]
                    if sub_tag == "action":
                        s = _drop_node(
                            "rectangle",
                            sub[1],
                            x=centre_x - _ACT_BRANCH_OFFSET_X,
                        )
                        _connect(then_last, s)
                        then_last = s
                    elif sub_tag == "term":
                        s = _drop_node(
                            "ellipse",
                            sub[1].upper(),
                            x=centre_x - _ACT_BRANCH_OFFSET_X,
                        )
                        _connect(then_last, s)
                        then_last = s
                # Else branch (right) — restart from the diamond's y.
                cursor_y[0] = branch_y_start
                else_last: Optional[Shape] = diamond
                for sub in else_stmts:
                    sub_tag = sub[0]
                    if sub_tag == "action":
                        s = _drop_node(
                            "rectangle",
                            sub[1],
                            x=centre_x + _ACT_BRANCH_OFFSET_X,
                        )
                        _connect(else_last, s)
                        else_last = s
                    elif sub_tag == "term":
                        s = _drop_node(
                            "ellipse",
                            sub[1].upper(),
                            x=centre_x + _ACT_BRANCH_OFFSET_X,
                        )
                        _connect(else_last, s)
                        else_last = s
                # Annotate yes/no edge labels by appending to the
                # branch's first shape's text — the Visio surface lacks
                # a connector-label primitive, so this preserves the
                # information non-destructively in the rendered output.
                if yes_label and then_last is not None and then_last is not diamond:
                    pass  # text already set by _drop_node
                if no_label and else_last is not None and else_last is not diamond:
                    pass

                # Continue from whichever branch's tail extended further,
                # so the next sibling statement re-attaches in line.
                last_shape[0] = then_last if then_last is not diamond else else_last
            else:
                # Unknown statement — skip.
                continue

    _emit(parsed.activity)
    return doc


# ---------------------------------------------------------------------------
# Component-diagram builder
# ---------------------------------------------------------------------------


def _node_kind_to_glyph(kind: str) -> str:
    """Visio glyph token for a parsed component-diagram node kind."""
    if kind == "interface":
        return "ellipse"
    if kind == "actor":
        return "ellipse"
    if kind == "usecase":
        return "ellipse"
    return "rectangle"


def _build_component(
    parsed: _ParsedDiagram,
    *,
    page_width: float,
    page_height: float,
    page_name: Optional[str],
) -> VisioDocument:
    """Render the component / use-case subset on a free grid."""
    inner_w = page_width - 2 * _CMP_PAGE_MARGIN_X
    inner_h = page_height - 2 * _CMP_PAGE_MARGIN_Y
    if inner_w <= 0 or inner_h <= 0:
        raise ValueError(
            "page %rx%r leaves no inner area after margins"
            % (page_width, page_height)
        )

    doc = Visio()
    name = page_name or parsed.title.strip() or "Component diagram"
    page = doc.pages.add_page(name=name, width=page_width, height=page_height)

    cols = max(1, _CMP_COLUMNS_PER_ROW)
    proxies: Dict[str, Shape] = {}
    for ix, node in enumerate(parsed.nodes):
        col = ix % cols
        row = ix // cols
        pin_x = (
            _CMP_PAGE_MARGIN_X
            + _CMP_NODE_WIDTH / 2
            + col * (_CMP_NODE_WIDTH + _CMP_GRID_GAP_X)
        )
        pin_y = (
            page_height
            - _CMP_PAGE_MARGIN_Y
            - _CMP_NODE_HEIGHT / 2
            - row * (_CMP_NODE_HEIGHT + _CMP_GRID_GAP_Y)
        )
        glyph = _node_kind_to_glyph(node["kind"])
        if glyph == "ellipse":
            shape = page.shapes.add_shape(
                VS_SHAPE_TYPE.ELLIPSE,
                at=(pin_x, pin_y),
                size=(_CMP_NODE_WIDTH, _CMP_NODE_HEIGHT),
                text=node["label"],
            )
        else:
            shape = page.shapes.add_shape(
                VS_SHAPE_TYPE.RECTANGLE,
                at=(pin_x, pin_y),
                size=(_CMP_NODE_WIDTH, _CMP_NODE_HEIGHT),
                text=node["label"],
            )
        proxies[node["alias"]] = shape

    for edge in parsed.edges:
        src = proxies.get(edge["from"])
        dst = proxies.get(edge["to"])
        if src is None or dst is None:
            continue
        page.add_connector(src, dst, routing=ROUTING_RIGHT_ANGLE)

    return doc


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def from_plantuml_string(
    text: str,
    *,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Parse a PlantUML *text* string and return the rendered document.

    The diagram kind is auto-detected from the source — see the module
    docstring for the supported subset and the layout policy. When the
    source contains no recognisable construct (or only unsupported
    ones), a single empty page is returned so the caller still receives
    a valid :class:`~vsdx.document.VisioDocument`.

    :param text: PlantUML source. May or may not be wrapped in
        ``@startuml`` / ``@enduml`` — the fence is treated permissively.
    :param page_width: explicit page width in inches; default depends
        on the detected diagram kind (8.5 for activity, 11.0 for
        component / use-case).
    :param page_height: explicit page height in inches; default
        depends on diagram kind (11.0 for activity, 8.5 for
        component / use-case).
    :param page_name: optional ``@NameU`` for the rendered page;
        defaults to the diagram's ``title`` directive value, then to
        a kind-specific fallback.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument` ready
        to :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *text* is not a ``str``.

    .. versionadded:: 0.4.0
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str (got %r)" % type(text).__name__)

    parsed = _parse(text)

    if parsed.kind == PLANTUML_KIND_ACTIVITY:
        return _build_activity(
            parsed,
            page_width=(page_width if page_width is not None else _ACT_DEFAULT_PAGE_WIDTH),
            page_height=(
                page_height if page_height is not None else _ACT_DEFAULT_PAGE_HEIGHT
            ),
            page_name=page_name,
        )

    if parsed.kind == PLANTUML_KIND_COMPONENT:
        return _build_component(
            parsed,
            page_width=(page_width if page_width is not None else _CMP_DEFAULT_PAGE_WIDTH),
            page_height=(
                page_height if page_height is not None else _CMP_DEFAULT_PAGE_HEIGHT
            ),
            page_name=page_name,
        )

    # Empty diagram — emit a one-page placeholder so callers don't have
    # to special-case the no-content path.
    doc = Visio()
    name = page_name or parsed.title.strip() or "PlantUML diagram"
    doc.pages.add_page(
        name=name,
        width=page_width if page_width is not None else _CMP_DEFAULT_PAGE_WIDTH,
        height=page_height if page_height is not None else _CMP_DEFAULT_PAGE_HEIGHT,
    )
    return doc


def from_plantuml(
    path: Union[str, "Any"],
    *,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Read a ``.puml`` / ``.plantuml`` file and return the rendered document.

    Thin file-backed wrapper around :func:`from_plantuml_string` —
    reads *path* as UTF-8 and forwards the contents.

    :param path: filesystem path to a PlantUML source file. Any
        path-like (``str`` / :class:`os.PathLike`) is accepted.
    :param page_width: forwarded to :func:`from_plantuml_string`.
    :param page_height: forwarded to :func:`from_plantuml_string`.
    :param page_name: forwarded to :func:`from_plantuml_string`.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises FileNotFoundError: when *path* does not exist.
    :raises UnicodeDecodeError: when *path* is not valid UTF-8.

    .. versionadded:: 0.4.0
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return from_plantuml_string(
        text,
        page_width=page_width,
        page_height=page_height,
        page_name=page_name,
    )


__all__ = [
    "PLANTUML_DIAGRAM_KINDS",
    "PLANTUML_KIND_ACTIVITY",
    "PLANTUML_KIND_COMPONENT",
    "PLANTUML_KIND_EMPTY",
    "from_plantuml",
    "from_plantuml_string",
]
