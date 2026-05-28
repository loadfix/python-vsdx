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
"""Mermaid flowchart import — issue #123.

Pure-Python parser + builder turning a Mermaid ``flowchart`` (a.k.a.
``graph``) source string into a fully-formed
:class:`~vsdx.document.VisioDocument`. The two public classmethods
:meth:`vsdx.document.VisioDocument.from_mermaid` (path) and
:meth:`vsdx.document.VisioDocument.from_mermaid_string` (str) delegate
to :func:`build_from_mermaid` here.

Supported syntax subset
=======================

* Header — ``flowchart`` / ``graph`` followed by an optional ``TD`` /
  ``LR`` / ``BT`` / ``RL`` / ``TB`` direction.
* Node shapes — ``A[Rect]``, ``A(Rounded)``, ``A((Circle))``,
  ``A{Diamond}``. The first richer appearance of a node id wins.
* Edges — ``-->`` (solid arrow), ``---`` (plain line, no arrow),
  ``-.->`` (dashed arrow), with an optional ``|label|`` after the
  token. Chained ``A --> B --> C`` decomposes to two edges.
* Subgraph blocks — ``subgraph Title ... end`` becomes a labelled
  :class:`~vsdx.container.Container`.

Out of scope (tracked as future work):

* ``sequenceDiagram``, ``gantt``, ``classDiagram``, ``stateDiagram``,
  ``erDiagram``, ``pie`` and other non-flowchart top-levels.
* Markdown-in-label, HTML escapes, click events.
* ``style`` / ``classDef`` / ``linkStyle`` directives — parsed away
  silently rather than rendered.

Layout simplification
=====================

This builder does **not** ship a Sugiyama layered layout. Instead it
arranges nodes on a fixed-width grid — five columns by default,
top-down in declaration order — and lets the connector auto-routing
engine (``routing="right-angle"``) draw the wires. Callers needing
tighter placement can post-process via :func:`vsdx.layout.layout`
(``"hierarchy"`` mode) or :meth:`~vsdx.page.Page.reroute_connectors`.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import (
    IO,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

# Default grid auto-layout knobs (inches).
DEFAULT_GRID_COLUMNS = 5
DEFAULT_CELL_WIDTH = 2.0
DEFAULT_CELL_HEIGHT = 1.4
DEFAULT_SHAPE_WIDTH = 1.5
DEFAULT_SHAPE_HEIGHT = 0.75
DEFAULT_MARGIN_X = 1.0
DEFAULT_MARGIN_Y = 1.0


# Direction tokens. ``TB`` is a Mermaid synonym for ``TD`` and folds into
# it at intake. All four resolve to the same column-major top-down grid
# in 0.4.0; the direction is preserved on :class:`MermaidFlowchart` for
# downstream callers that want to honour it themselves.
DIRECTION_TOP_DOWN = "TD"
DIRECTION_LEFT_RIGHT = "LR"
DIRECTION_BOTTOM_TOP = "BT"
DIRECTION_RIGHT_LEFT = "RL"
DIRECTIONS = (
    DIRECTION_TOP_DOWN, DIRECTION_LEFT_RIGHT,
    DIRECTION_BOTTOM_TOP, DIRECTION_RIGHT_LEFT,
)
_DIRECTION_ALIASES = {
    "TB": DIRECTION_TOP_DOWN, "TD": DIRECTION_TOP_DOWN,
    "LR": DIRECTION_LEFT_RIGHT, "BT": DIRECTION_BOTTOM_TOP,
    "RL": DIRECTION_RIGHT_LEFT,
}


# Node-shape tokens — match the Mermaid bracket family rather than the
# Visio master name so the value stays stable if the master mapping
# shifts.
NODE_SHAPE_RECTANGLE = "rect"
NODE_SHAPE_ROUNDED = "rounded"
NODE_SHAPE_CIRCLE = "circle"
NODE_SHAPE_DIAMOND = "diamond"
NODE_SHAPES = (
    NODE_SHAPE_RECTANGLE, NODE_SHAPE_ROUNDED,
    NODE_SHAPE_CIRCLE, NODE_SHAPE_DIAMOND,
)


# Edge-style tokens.
EDGE_STYLE_SOLID = "solid"
EDGE_STYLE_DASHED = "dashed"
EDGE_STYLE_PLAIN = "plain"  # ``---`` — line, no arrow.
EDGE_STYLES = (EDGE_STYLE_SOLID, EDGE_STYLE_DASHED, EDGE_STYLE_PLAIN)


# ---------------------------------------------------------------------------
# AST dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MermaidNode:
    """A single node parsed out of a Mermaid flowchart source.

    *label* defaults to *id* when no bracket form is given; *shape* is
    one of the :data:`NODE_SHAPES` tokens.
    """

    id: str
    label: str
    shape: str = NODE_SHAPE_RECTANGLE


@dataclass
class MermaidEdge:
    """A directed edge between two :class:`MermaidNode` ids.

    *label* is the bar-delimited text from a ``A -->|label| B`` form,
    or ``None`` for an unlabelled edge.
    """

    source: str
    target: str
    style: str = EDGE_STYLE_SOLID
    label: Optional[str] = None


@dataclass
class MermaidSubgraph:
    """A ``subgraph Title ... end`` block.

    *node_ids* records every node id declared inside the block in
    source order. Mermaid scopes a node to the first subgraph that
    claims it; the builder respects that.
    """

    title: str
    node_ids: List[str] = field(default_factory=list)


@dataclass
class MermaidFlowchart:
    """Parsed AST for a Mermaid flowchart source.

    Use :func:`parse_mermaid` to populate one from a string, or
    :func:`build_from_mermaid` to drive the full file→document pipeline.
    """

    direction: str = DIRECTION_TOP_DOWN
    nodes: List[MermaidNode] = field(default_factory=list)
    edges: List[MermaidEdge] = field(default_factory=list)
    subgraphs: List[MermaidSubgraph] = field(default_factory=list)

    def node_by_id(self, node_id: str) -> Optional[MermaidNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None


# ---------------------------------------------------------------------------
# Parser errors
# ---------------------------------------------------------------------------


class MermaidParseError(ValueError):
    """Raised when the Mermaid source cannot be parsed.

    Carries the offending 1-based line number and line text. Inherits
    from :class:`ValueError` for symmetry with the rest of the vsdx
    error hierarchy.
    """

    def __init__(self, message: str, line_no: int, line: str) -> None:
        self.line_no = line_no
        self.line = line
        self._inner_message = message
        super().__init__(f"line {line_no}: {message}: {line!r}")


# ---------------------------------------------------------------------------
# Tokeniser / parser
# ---------------------------------------------------------------------------


# ``flowchart`` and ``graph`` are interchangeable in Mermaid 9+; direction
# is optional (Mermaid defaults to ``TB``).
_HEADER_RE = re.compile(
    r"^\s*(?:flowchart|graph)(?:\s+(?P<dir>[A-Z]{2}))?\s*$"
)
_SUBGRAPH_OPEN_RE = re.compile(r"^\s*subgraph\s+(?P<title>.+?)\s*$")
_SUBGRAPH_CLOSE_RE = re.compile(r"^\s*end\s*$")
_COMMENT_RE = re.compile(r"^\s*%%")

# Mermaid styling primitives that don't map onto Visio in this PR — we
# accept and skip rather than raise.
_SKIP_PREFIX_RE = re.compile(
    r"^\s*(?:style|classDef|class|click|linkStyle|"
    r"direction|accTitle|accDescr)\b",
    re.IGNORECASE,
)

# Edge tokens, longest-first so ``-.->`` outranks ``-->``. Each tuple is
# ``(literal, style, has_arrow)``.
_EDGE_TOKENS: Tuple[Tuple[str, str, bool], ...] = (
    ("-.->", EDGE_STYLE_DASHED, True),
    ("-->", EDGE_STYLE_SOLID, True),
    ("---", EDGE_STYLE_PLAIN, False),
)

# Node-shape opener → closer mapping. Longest-first matters for ``((`` vs
# ``(``; the resolver picks the first prefix that matches.
_SHAPE_BRACKETS: Tuple[Tuple[str, str, str], ...] = (
    ("((", "))", NODE_SHAPE_CIRCLE),
    ("(", ")", NODE_SHAPE_ROUNDED),
    ("[", "]", NODE_SHAPE_RECTANGLE),
    ("{", "}", NODE_SHAPE_DIAMOND),
)


def parse_mermaid(source: str) -> MermaidFlowchart:
    """Parse Mermaid flowchart *source* into a :class:`MermaidFlowchart`.

    Lines outside the supported subset (``style``, ``classDef``,
    ``click``, etc.) are silently skipped. Lines that look like
    flowchart syntax but fail to parse raise :class:`MermaidParseError`.

    The first non-blank, non-comment line must be a header
    (``flowchart`` / ``graph`` followed by an optional direction).
    """
    chart = MermaidFlowchart()
    # Strip a Markdown ``` ```mermaid ``` ``` fence — common when pasting
    # from a playground.
    source = _strip_markdown_fence(source)
    lines = source.splitlines()
    header_seen = False
    # Stack of open ``subgraph`` blocks; nested blocks scope nodes to
    # the innermost one.
    subgraph_stack: List[MermaidSubgraph] = []

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if _COMMENT_RE.match(line):
            continue

        if not header_seen:
            m = _HEADER_RE.match(line)
            if not m:
                raise MermaidParseError(
                    "expected 'flowchart' or 'graph' header",
                    idx,
                    line,
                )
            direction_raw = m.group("dir") or "TB"
            chart.direction = _DIRECTION_ALIASES.get(
                direction_raw.upper(), DIRECTION_TOP_DOWN
            )
            header_seen = True
            continue

        m = _SUBGRAPH_OPEN_RE.match(line)
        if m:
            sg = MermaidSubgraph(title=_subgraph_title(m.group("title").strip()))
            chart.subgraphs.append(sg)
            subgraph_stack.append(sg)
            continue
        if _SUBGRAPH_CLOSE_RE.match(line):
            if subgraph_stack:
                subgraph_stack.pop()
            continue
        if _SKIP_PREFIX_RE.match(line):
            continue

        try:
            _parse_statement(
                line.strip(),
                chart=chart,
                subgraph_stack=subgraph_stack,
            )
        except MermaidParseError as exc:
            # Re-raise with the correct outer line number / text.
            raise MermaidParseError(
                getattr(exc, "_inner_message", None) or str(exc),
                idx,
                line,
            ) from None
        except ValueError as exc:
            raise MermaidParseError(str(exc), idx, line) from None

    if not header_seen:
        raise MermaidParseError(
            "no flowchart / graph header found in source",
            line_no=0,
            line="",
        )

    return chart


def _strip_markdown_fence(source: str) -> str:
    """Drop a leading `````mermaid`` / trailing ``````` fence."""
    lines = source.splitlines()
    if not lines or not lines[0].strip().startswith("```"):
        return source
    body = lines[1:]
    if body and body[-1].strip() == "```":
        body = body[:-1]
    return "\n".join(body)


def _subgraph_title(raw: str) -> str:
    """Pull the rendered title out of a ``subgraph`` opener.

    Mermaid permits ``subgraph id`` (id-only), ``subgraph "Some Title"``,
    or ``subgraph id [Display Title]``; the bracketed form is the only
    one that splits id and label.
    """
    if "[" in raw and raw.rstrip().endswith("]"):
        return raw[raw.index("[") + 1 : -1].strip()
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _parse_statement(
    line: str,
    *,
    chart: MermaidFlowchart,
    subgraph_stack: Sequence[MermaidSubgraph],
) -> None:
    """Parse one non-blank, non-comment, non-header source line.

    Edge statements carry at least one edge token (``-->`` / ``---`` /
    ``-.->``) and optionally a ``|label|`` immediately after; bare node
    declarations have no edge token. Chained ``A --> B --> C`` decomposes
    via recursion on the right-hand side.
    """
    pos, token = _find_first_edge(line)
    if pos < 0:
        # Bare node declaration — no edge.
        node = _parse_node(line.strip(), chart)
        _adopt_into_subgraph(node.id, subgraph_stack, chart)
        return

    # Edge form. Pluck out an inline ``|label|`` immediately after the
    # token if present; the label may contain spaces but no pipes.
    after_token = pos + len(token[0])
    label, label_end = _extract_inline_label(line, after_token)
    style = token[1]
    left = line[:pos].strip()
    right = line[label_end:].strip()
    if not left or not right:
        raise MermaidParseError(
            "edge token must have a node on both sides", line_no=0, line=line
        )
    source_node = _parse_node(left, chart)
    _adopt_into_subgraph(source_node.id, subgraph_stack, chart)
    _parse_chained_target(
        right,
        prev_id=source_node.id,
        style=style,
        label=label,
        chart=chart,
        subgraph_stack=subgraph_stack,
    )


def _parse_chained_target(
    rhs: str,
    *,
    prev_id: str,
    style: str,
    label: Optional[str],
    chart: MermaidFlowchart,
    subgraph_stack: Sequence[MermaidSubgraph],
) -> None:
    """Walk ``A --> B --> C`` chains, emitting one edge per hop."""
    pos, token = _find_first_edge(rhs)
    if pos < 0:
        target_node = _parse_node(rhs.strip(), chart)
        _adopt_into_subgraph(target_node.id, subgraph_stack, chart)
        chart.edges.append(
            MermaidEdge(prev_id, target_node.id, style, label)
        )
        return
    after_token = pos + len(token[0])
    next_label, label_end = _extract_inline_label(rhs, after_token)
    target_node = _parse_node(rhs[:pos].strip(), chart)
    _adopt_into_subgraph(target_node.id, subgraph_stack, chart)
    chart.edges.append(MermaidEdge(prev_id, target_node.id, style, label))
    _parse_chained_target(
        rhs[label_end:].strip(),
        prev_id=target_node.id,
        style=token[1],
        label=next_label,
        chart=chart,
        subgraph_stack=subgraph_stack,
    )


def _find_first_edge(line: str) -> Tuple[int, Tuple[str, str, bool]]:
    """Return ``(pos, token)`` for the leftmost edge token, or ``(-1, ...)``."""
    best_pos = -1
    best_token: Tuple[str, str, bool] = ("", "", False)
    for token in _EDGE_TOKENS:
        idx = line.find(token[0])
        if idx < 0:
            continue
        if best_pos < 0 or idx < best_pos:
            best_pos, best_token = idx, token
    return best_pos, best_token


def _extract_inline_label(
    line: str, start: int
) -> Tuple[Optional[str], int]:
    """Pull a ``|label|`` out of *line* starting at *start*.

    Returns ``(label, end_pos)`` where ``end_pos`` is the index just
    past the closing pipe (or *start* itself when no label is present).
    A missing closing pipe raises :class:`MermaidParseError`.
    """
    cursor = start
    while cursor < len(line) and line[cursor] == " ":
        cursor += 1
    if cursor >= len(line) or line[cursor] != "|":
        return None, start
    end = line.find("|", cursor + 1)
    if end < 0:
        raise MermaidParseError(
            "edge label opened with '|' but never closed",
            line_no=0,
            line=line,
        )
    return line[cursor + 1 : end].strip(), end + 1


# A bare node id is alphanumeric + underscore + dash + dot (Mermaid is
# permissive on dashes and dots inside ids).
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_\-\.]+")


def _parse_node(text: str, chart: MermaidFlowchart) -> MermaidNode:
    """Resolve *text* (``A``, ``A[Label]``, ``A((Foo))``, …) to a node.

    Reuses an already-registered node with the same id, upgrading
    *label* / *shape* on the first richer appearance (``A`` then
    ``A[Foo]`` ends up labelled). Registers new ids on *chart*.
    """
    text = text.strip()
    if not text:
        raise MermaidParseError("empty node reference", line_no=0, line=text)
    m = _NODE_ID_RE.match(text)
    if not m:
        raise MermaidParseError(
            "node id must start with [A-Za-z0-9_]", line_no=0, line=text
        )
    node_id = m.group(0)
    rest = text[m.end():].strip()

    shape = NODE_SHAPE_RECTANGLE
    label: Optional[str] = None
    if rest:
        for opener, closer, kind in _SHAPE_BRACKETS:
            if rest.startswith(opener):
                if not rest.endswith(closer):
                    raise MermaidParseError(
                        f"node bracket {opener!r} not closed with {closer!r}",
                        line_no=0,
                        line=text,
                    )
                inner = rest[len(opener) : len(rest) - len(closer)]
                label = _strip_quotes(inner.strip())
                shape = kind
                break
        else:
            raise MermaidParseError(
                "trailing text after node id is not a recognised bracket form",
                line_no=0,
                line=text,
            )

    existing = chart.node_by_id(node_id)
    if existing is None:
        node = MermaidNode(
            id=node_id,
            label=label if label is not None else node_id,
            shape=shape,
        )
        chart.nodes.append(node)
        return node
    # First richer appearance wins. Subsequent references that don't
    # carry a label / non-default shape leave the upgrade intact.
    if label is not None and existing.label == existing.id:
        existing.label = label
    if shape != NODE_SHAPE_RECTANGLE and existing.shape == NODE_SHAPE_RECTANGLE:
        existing.shape = shape
    return existing


def _strip_quotes(text: str) -> str:
    """Strip a leading + trailing matched ``"`` from *text*."""
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def _adopt_into_subgraph(
    node_id: str,
    subgraph_stack: Sequence[MermaidSubgraph],
    chart: MermaidFlowchart,
) -> None:
    """Record *node_id* against the innermost open ``subgraph`` block.

    First-claim semantics — once a node belongs to a subgraph, later
    appearances in unrelated subgraphs are ignored (matching Mermaid).
    """
    if not subgraph_stack:
        return
    current = subgraph_stack[-1]
    for sg in chart.subgraphs:
        if node_id in sg.node_ids:
            return
    if node_id not in current.node_ids:
        current.node_ids.append(node_id)


# ---------------------------------------------------------------------------
# Builder — AST → VisioDocument
# ---------------------------------------------------------------------------


# Map :data:`NODE_SHAPES` tokens onto vsdx autoshape master names. 0.4.0
# ships three built-in masters (Rectangle / Ellipse / Triangle); circles
# project onto Ellipse and diamonds fall back to Rectangle until a
# bespoke diamond geometry lands in a follow-up.
_SHAPE_MASTER_MAP = {
    NODE_SHAPE_RECTANGLE: "Rectangle",
    NODE_SHAPE_ROUNDED: "Rectangle",
    NODE_SHAPE_CIRCLE: "Ellipse",
    NODE_SHAPE_DIAMOND: "Rectangle",
}


def build_from_mermaid(
    source: Union[str, "os.PathLike[str]", IO[str]],
    *,
    columns: int = DEFAULT_GRID_COLUMNS,
    page_name: str = "Mermaid",
) -> VisioDocument:
    """Parse Mermaid *source* and return a populated :class:`VisioDocument`.

    *source* may be a path-like, a file-like opened in text mode, or a
    raw Mermaid string (anything containing a newline or starting with
    ``flowchart`` / ``graph`` / ```` ``` ```` is treated as inline
    source; everything else is treated as a path).

    *columns* controls the grid auto-layout column count.

    *page_name* sets the rendered page name on the produced document.
    """
    text = _coerce_to_text(source)
    chart = parse_mermaid(text)
    return _build_document(chart, columns=columns, page_name=page_name)


def _coerce_to_text(
    source: Union[str, "os.PathLike[str]", IO[str]],
) -> str:
    """Normalise *source* into a Mermaid source string.

    A multi-line string is treated as inline source; a single-line
    string falls back to the filesystem when the path exists.
    """
    if hasattr(source, "read"):
        data = source.read()  # type: ignore[union-attr]
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return data
    if isinstance(source, (str, os.PathLike)):
        as_str = os.fspath(source)
        if "\n" in as_str:
            return as_str
        if os.path.exists(as_str):
            with open(as_str, "r", encoding="utf-8") as fh:
                return fh.read()
        return as_str
    raise TypeError(
        "from_mermaid source must be a path, file-like, or str — got %r"
        % type(source).__name__
    )


def _build_document(
    chart: MermaidFlowchart,
    *,
    columns: int,
    page_name: str,
) -> VisioDocument:
    doc = Visio()
    page = doc.pages.add_page(name=page_name)

    # Resize the page so the full grid fits — the 8.5 x 11 default
    # works for most inputs but a 50-node graph wants more.
    n = len(chart.nodes)
    cols = max(1, int(columns))
    rows = (n + cols - 1) // cols
    needed_w = DEFAULT_MARGIN_X * 2 + cols * DEFAULT_CELL_WIDTH
    needed_h = DEFAULT_MARGIN_Y * 2 + max(1, rows) * DEFAULT_CELL_HEIGHT
    if needed_w > float(page.width):
        page.width = needed_w
    if needed_h > float(page.height):
        page.height = needed_h

    # First pass — drop nodes onto the grid in declaration order.
    shapes_by_id: dict = {}
    for index, node in enumerate(chart.nodes):
        master = _SHAPE_MASTER_MAP.get(node.shape, "Rectangle")
        col = index % cols
        row = index // cols
        pin_x = DEFAULT_MARGIN_X + col * DEFAULT_CELL_WIDTH + DEFAULT_SHAPE_WIDTH / 2
        pin_y = (
            float(page.height)
            - DEFAULT_MARGIN_Y
            - row * DEFAULT_CELL_HEIGHT
            - DEFAULT_SHAPE_HEIGHT / 2
        )
        # Circles get a square footprint so they actually look round.
        if node.shape == NODE_SHAPE_CIRCLE:
            size = (DEFAULT_SHAPE_HEIGHT, DEFAULT_SHAPE_HEIGHT)
        else:
            size = (DEFAULT_SHAPE_WIDTH, DEFAULT_SHAPE_HEIGHT)
        shapes_by_id[node.id] = page.shapes.add_shape(
            master, at=(pin_x, pin_y), size=size, text=node.label,
        )

    # Second pass — connectors. An unknown node id raises so callers
    # catch typos rather than silently dropping edges.
    for edge in chart.edges:
        src = shapes_by_id.get(edge.source)
        tgt = shapes_by_id.get(edge.target)
        if src is None or tgt is None:
            missing = edge.source if src is None else edge.target
            raise MermaidParseError(
                f"edge references undeclared node {missing!r}",
                line_no=0,
                line="",
            )
        connector = page.add_connector(src, tgt, routing="right-angle")
        if edge.label:
            connector.text = edge.label
        # ``plain`` drops the arrow head; ``dashed`` writes LinePattern.
        # Generic cell setter — neither is first-class on the connector
        # proxy yet.
        if edge.style == EDGE_STYLE_DASHED:
            connector._element.get_or_add_cell("LinePattern").set("V", "2")
        elif edge.style == EDGE_STYLE_PLAIN:
            connector._element.get_or_add_cell("EndArrow").set("V", "0")

    # Third pass — subgraphs become labelled containers around their
    # member shapes.
    for sg in chart.subgraphs:
        members = [
            shapes_by_id[mid] for mid in sg.node_ids if mid in shapes_by_id
        ]
        if not members:
            continue
        xs = [float(m.pin_x) for m in members]
        ys = [float(m.pin_y) for m in members]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        w = max(xs) - min(xs) + DEFAULT_SHAPE_WIDTH + 0.6
        h = max(ys) - min(ys) + DEFAULT_SHAPE_HEIGHT + 0.6
        container = page.add_container(
            title=sg.title, at=(cx, cy), size=(w, h), auto_resize=True,
        )
        for member in members:
            try:
                container.members.add(member)
            except Exception:  # noqa: BLE001 — best-effort adoption
                # Already inside another container (nested subgraph) —
                # leave it where it is rather than blowing up.
                pass

    return doc


__all__ = [
    "DEFAULT_CELL_HEIGHT",
    "DEFAULT_CELL_WIDTH",
    "DEFAULT_GRID_COLUMNS",
    "DEFAULT_MARGIN_X",
    "DEFAULT_MARGIN_Y",
    "DEFAULT_SHAPE_HEIGHT",
    "DEFAULT_SHAPE_WIDTH",
    "DIRECTIONS",
    "DIRECTION_BOTTOM_TOP",
    "DIRECTION_LEFT_RIGHT",
    "DIRECTION_RIGHT_LEFT",
    "DIRECTION_TOP_DOWN",
    "EDGE_STYLES",
    "EDGE_STYLE_DASHED",
    "EDGE_STYLE_PLAIN",
    "EDGE_STYLE_SOLID",
    "MermaidEdge",
    "MermaidFlowchart",
    "MermaidNode",
    "MermaidParseError",
    "MermaidSubgraph",
    "NODE_SHAPES",
    "NODE_SHAPE_CIRCLE",
    "NODE_SHAPE_DIAMOND",
    "NODE_SHAPE_RECTANGLE",
    "NODE_SHAPE_ROUNDED",
    "build_from_mermaid",
    "parse_mermaid",
]
