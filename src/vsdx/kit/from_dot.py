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
"""Graphviz DOT → Visio importer — issue #125.

Public entry points:

* :func:`document_from_dot` — read a ``.dot`` / ``.gv`` file and return
  a :class:`~vsdx.document.VisioDocument`.
* :func:`document_from_dot_string` — like :func:`document_from_dot`
  but accepts the DOT source as an in-memory string.

The two factories also surface as classmethods on
:class:`~vsdx.document.VisioDocument`:

.. code-block:: python

    from vsdx import VisioDocument

    doc = VisioDocument.from_dot("graph.dot")
    doc = VisioDocument.from_dot_string("digraph { A -> B }")

Supported DOT syntax subset
---------------------------

* ``digraph Name { ... }`` and ``graph Name { ... }`` for directed and
  undirected graphs.
* Node declarations — ``A;`` and ``A [label="Foo", shape=box,
  color=red, style=dashed];``.
* Edge declarations — ``A -> B [label="x"];`` (directed) and ``A -- B``
  (undirected). Chain forms (``A -> B -> C``) decompose into pairwise
  edges.
* Subgraphs / clusters — ``subgraph cluster_0 { ... }``. Cluster
  bodies are rendered as labelled :class:`~vsdx.container.Container`
  rectangles wrapping their members. Non-cluster subgraphs (those
  whose name does not start with ``cluster``) are flattened into the
  parent graph — Graphviz's own semantics for subgraph attribute
  inheritance is *not* modelled here; we treat them as namespacing
  hints only.
* Common shapes — ``box`` / ``rect`` / ``rectangle`` (rectangle),
  ``ellipse`` / ``oval`` (ellipse), ``circle`` (ellipse),
  ``diamond`` / ``rhombus`` (diamond, authored via the decision
  glyph), ``parallelogram`` (slanted box, authored as a custom
  geometry). Unrecognised shapes fall back to ``box``.
* Common attributes — ``label``, ``shape``, ``color``, ``fillcolor``,
  ``style=dashed`` / ``style=dotted`` / ``style=solid``.
* Comments — C-style ``// line comment`` and ``/* block comment */``.

Out of scope
------------

* **Strict mode** (``strict graph``) — the ``strict`` keyword is
  tolerated and silently ignored; duplicate edge collapse is left to
  the caller.
* **HTML-like labels** (``label=<<TABLE>...</TABLE>>``) — the parser
  treats them as opaque strings.
* **Layout sugar** — the auto-layout is a simple top-down grid. We do
  not implement Graphviz's Sugiyama layered layout. The user can
  post-process the document in Visio (or via the
  :mod:`vsdx.layout` helpers) for a tidier rendering.
* **External attribute scoping** (``node [...]; A; B;`` to set
  defaults) — node-level attribute defaults declared via the bare
  ``node`` / ``edge`` / ``graph`` keywords are tolerated but ignored.
* **Port references** — ``A:f1 -> B:f2`` syntax is parsed (the port
  segment is stripped) but the port semantics are dropped.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import os
from typing import (
    Any,
    Dict,
    List,
    Mapping,
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
# Public constants
# ---------------------------------------------------------------------------

#: Default node width (inches) when none is supplied via ``width=``.
DOT_DEFAULT_NODE_WIDTH: float = 1.4

#: Default node height (inches) when none is supplied via ``height=``.
DOT_DEFAULT_NODE_HEIGHT: float = 0.7

#: Horizontal spacing between adjacent nodes on the same row.
DOT_DEFAULT_HORIZONTAL_GAP: float = 0.6

#: Vertical spacing between adjacent rows.
DOT_DEFAULT_VERTICAL_GAP: float = 0.5

#: Margin added around the cluster's content rectangle.
DOT_DEFAULT_CLUSTER_PADDING: float = 0.35

#: Page margin reserved on every edge of the rendered drawing.
DOT_DEFAULT_PAGE_MARGIN: float = 0.5


#: Recognised shape tokens — maps the DOT spelling to the Visio
#: authoring kind we render. The rendering layer dispatches on the
#: kind string; the same mapping covers the synonyms Graphviz accepts
#: (``box`` / ``rect`` / ``rectangle``, ``ellipse`` / ``oval``).
DOT_SHAPE_MAP: Dict[str, str] = {
    "box": "rectangle",
    "rect": "rectangle",
    "rectangle": "rectangle",
    "square": "rectangle",
    "ellipse": "ellipse",
    "oval": "ellipse",
    "circle": "ellipse",
    "diamond": "diamond",
    "rhombus": "diamond",
    "parallelogram": "parallelogram",
}


#: Shape kinds the renderer knows how to draw natively. Anything not
#: in this set falls back to ``"rectangle"``.
DOT_SHAPE_KINDS: Tuple[str, ...] = (
    "rectangle",
    "ellipse",
    "diamond",
    "parallelogram",
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class DotParseError(ValueError):
    """Raised when the DOT source cannot be parsed.

    Carries the offending fragment in :attr:`fragment` and the source
    line number in :attr:`line_no` (one-based) when available so
    callers can surface a useful pointer.
    """

    def __init__(
        self,
        message: str,
        fragment: Optional[str] = None,
        line_no: Optional[int] = None,
    ) -> None:
        location = ""
        if line_no is not None:
            location = " (line %d)" % line_no
        super().__init__("%s%s" % (message, location))
        self.fragment = fragment
        self.line_no = line_no


# Token kinds — the lexer emits these as ``(kind, value, line_no)``
# triples. A handful are simple punctuation; ``ID`` covers identifier
# tokens (bare words, quoted strings, numerics) and HTML-shape labels
# (``<...>``).
_TK_ID = "ID"
_TK_LBRACE = "{"
_TK_RBRACE = "}"
_TK_LBRACKET = "["
_TK_RBRACKET = "]"
_TK_SEMI = ";"
_TK_COMMA = ","
_TK_EQ = "="
_TK_DEDGE = "->"  # directed edge
_TK_UEDGE = "--"  # undirected edge
_TK_COLON = ":"
_TK_EOF = "EOF"


# Reserved keywords that terminate identifier-context parses early.
_DOT_KEYWORDS = frozenset(
    {"graph", "digraph", "subgraph", "node", "edge", "strict"}
)


def _strip_comments(source: str) -> str:
    """Return *source* with C-style ``//`` and ``/* … */`` comments removed.

    Newlines inside block comments are preserved so the line-number
    tracking in the lexer stays accurate.
    """
    out: List[str] = []
    i = 0
    n = len(source)
    in_string = False
    string_quote = ""
    while i < n:
        ch = source[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if ch == string_quote:
                in_string = False
                string_quote = ""
            i += 1
            continue
        if ch in ('"', "'"):
            in_string = True
            string_quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            # Line comment — skip to end of line, keep the newline.
            j = source.find("\n", i + 2)
            if j == -1:
                break
            i = j
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            # Block comment — skip to matching ``*/``; preserve newlines.
            j = source.find("*/", i + 2)
            if j == -1:
                # Unterminated block comment — treat the rest as comment.
                # Preserve internal newlines so subsequent reports line up.
                for c in source[i:]:
                    if c == "\n":
                        out.append("\n")
                break
            for c in source[i + 2:j]:
                if c == "\n":
                    out.append("\n")
            i = j + 2
            continue
        if ch == "#" and (i == 0 or source[i - 1] == "\n"):
            # ``#``-prefixed line comment (DOT also accepts this form
            # at line start). Skip to end of line.
            j = source.find("\n", i + 1)
            if j == -1:
                break
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tokenise(source: str) -> List[Tuple[str, str, int]]:
    """Lex *source* into a flat list of ``(kind, value, line_no)`` tuples.

    The lexer is purely position-tracking — it never interprets edge
    operators or attributes. The parser layer above handles grouping.
    """
    cleaned = _strip_comments(source)
    tokens: List[Tuple[str, str, int]] = []
    i = 0
    n = len(cleaned)
    line_no = 1
    while i < n:
        ch = cleaned[i]
        if ch == "\n":
            line_no += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            tokens.append((_TK_LBRACE, ch, line_no))
            i += 1
            continue
        if ch == "}":
            tokens.append((_TK_RBRACE, ch, line_no))
            i += 1
            continue
        if ch == "[":
            tokens.append((_TK_LBRACKET, ch, line_no))
            i += 1
            continue
        if ch == "]":
            tokens.append((_TK_RBRACKET, ch, line_no))
            i += 1
            continue
        if ch == ";":
            tokens.append((_TK_SEMI, ch, line_no))
            i += 1
            continue
        if ch == ",":
            tokens.append((_TK_COMMA, ch, line_no))
            i += 1
            continue
        if ch == "=":
            tokens.append((_TK_EQ, ch, line_no))
            i += 1
            continue
        if ch == ":":
            tokens.append((_TK_COLON, ch, line_no))
            i += 1
            continue
        if ch == "-" and i + 1 < n and cleaned[i + 1] == ">":
            tokens.append((_TK_DEDGE, "->", line_no))
            i += 2
            continue
        if ch == "-" and i + 1 < n and cleaned[i + 1] == "-":
            tokens.append((_TK_UEDGE, "--", line_no))
            i += 2
            continue
        if ch == '"':
            # Quoted string — handle backslash-escaped quotes.
            j = i + 1
            buf: List[str] = []
            start_line = line_no
            while j < n:
                c = cleaned[j]
                if c == "\\" and j + 1 < n:
                    nxt = cleaned[j + 1]
                    # DOT supports a few backslash escapes; pass them
                    # through verbatim apart from \\" → " and \\\\ → \\.
                    if nxt == '"':
                        buf.append('"')
                    elif nxt == "\\":
                        buf.append("\\")
                    elif nxt == "n":
                        buf.append("\n")
                    elif nxt == "l" or nxt == "r":
                        buf.append("\n")
                    else:
                        buf.append(nxt)
                    j += 2
                    continue
                if c == '"':
                    break
                if c == "\n":
                    line_no += 1
                buf.append(c)
                j += 1
            if j >= n:
                raise DotParseError(
                    "unterminated quoted string", line_no=start_line
                )
            tokens.append((_TK_ID, "".join(buf), start_line))
            i = j + 1
            continue
        if ch == "<":
            # HTML-like label — opaque string captured between
            # balanced angle brackets. The block is preserved verbatim
            # (minus the outer ``<`` / ``>``) so callers can recognise
            # the HTML form even though we don't render it.
            depth = 1
            j = i + 1
            buf2: List[str] = []
            start_line = line_no
            while j < n and depth > 0:
                c = cleaned[j]
                if c == "<":
                    depth += 1
                    buf2.append(c)
                elif c == ">":
                    depth -= 1
                    if depth == 0:
                        break
                    buf2.append(c)
                else:
                    if c == "\n":
                        line_no += 1
                    buf2.append(c)
                j += 1
            if depth != 0:
                raise DotParseError(
                    "unterminated HTML-like label", line_no=start_line
                )
            # Mark HTML labels by leaving the angle brackets attached
            # so the parser can see the leading ``<`` and treat the
            # label as opaque (HTML rendering is out-of-scope).
            tokens.append((_TK_ID, "<" + "".join(buf2) + ">", start_line))
            i = j + 1
            continue
        # Bare identifier — letters, digits, underscores, dots, dashes
        # (DOT permits leading digits for numerics so we accept those
        # here and let the parser disambiguate by context).
        if ch.isalnum() or ch in "_.+-":
            j = i
            while j < n:
                c = cleaned[j]
                if c.isalnum() or c in "_.":
                    j += 1
                    continue
                # Allow a single embedded ``-`` only inside numerics —
                # otherwise it's an edge operator we already handled.
                break
            if j == i:
                # Single non-identifier character that doesn't match
                # anything above — bail.
                raise DotParseError(
                    "unrecognised character %r" % ch, line_no=line_no
                )
            tokens.append((_TK_ID, cleaned[i:j], line_no))
            i = j
            continue
        raise DotParseError(
            "unrecognised character %r" % ch, line_no=line_no
        )
    tokens.append((_TK_EOF, "", line_no))
    return tokens


# A lightweight parser AST — flat dataclasses-as-dicts so we avoid the
# extra import surface of ``dataclasses`` (Py 3.9 floor).


class _Node:
    """Parsed node-declaration — name + attribute mapping."""

    __slots__ = ("name", "attrs")

    def __init__(self, name: str, attrs: Mapping[str, str]) -> None:
        self.name = name
        self.attrs = dict(attrs)


class _Edge:
    """Parsed edge-declaration — endpoints, directedness, attribute mapping."""

    __slots__ = ("from_name", "to_name", "directed", "attrs")

    def __init__(
        self,
        from_name: str,
        to_name: str,
        directed: bool,
        attrs: Mapping[str, str],
    ) -> None:
        self.from_name = from_name
        self.to_name = to_name
        self.directed = directed
        self.attrs = dict(attrs)


class _Subgraph:
    """Parsed subgraph — name + list of nested statements."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.is_cluster = name.startswith("cluster")
        self.label: Optional[str] = None
        self.members: List[str] = []
        self.edges: List[_Edge] = []
        self.subgraphs: List["_Subgraph"] = []
        # Bag of {node_name: {attr: value}} captured during parsing.
        # Lifted up to the parent graph by :meth:`_merge_subgraph`.
        self._pending_attrs: Dict[str, Dict[str, str]] = {}


class _Graph:
    """Top-level graph — directed flag + list of nested statements."""

    __slots__ = ("name", "directed", "strict", "nodes", "edges", "subgraphs")

    def __init__(self, name: Optional[str], directed: bool, strict: bool) -> None:
        self.name = name
        self.directed = directed
        self.strict = strict
        self.nodes: Dict[str, _Node] = {}
        self.edges: List[_Edge] = []
        self.subgraphs: List[_Subgraph] = []


class _Parser:
    """Recursive-descent DOT parser.

    Entry point is :meth:`parse_graph`. The parser keeps a flat token
    cursor and never lookback-rewinds beyond the next-token peek, so
    error reporting is precise: every :class:`DotParseError` carries
    the line number of the offending token.
    """

    def __init__(self, tokens: List[Tuple[str, str, int]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self, offset: int = 0) -> Tuple[str, str, int]:
        ix = self.pos + offset
        if ix >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[ix]

    def _advance(self) -> Tuple[str, str, int]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, kind: str) -> Tuple[str, str, int]:
        tok = self._peek()
        if tok[0] != kind:
            raise DotParseError(
                "expected %r, got %r" % (kind, tok[1]), line_no=tok[2]
            )
        return self._advance()

    def parse_graph(self) -> _Graph:
        # Optional ``strict``.
        strict = False
        tok = self._peek()
        if tok[0] == _TK_ID and tok[1].lower() == "strict":
            self._advance()
            strict = True
            tok = self._peek()
        if tok[0] != _TK_ID or tok[1].lower() not in ("graph", "digraph"):
            raise DotParseError(
                "expected 'graph' or 'digraph' keyword, got %r" % tok[1],
                line_no=tok[2],
            )
        directed = tok[1].lower() == "digraph"
        self._advance()
        # Optional graph name.
        name = None
        nxt = self._peek()
        if nxt[0] == _TK_ID and nxt[1] not in ("{", "}"):
            name = nxt[1]
            self._advance()
        self._expect(_TK_LBRACE)
        graph = _Graph(name=name, directed=directed, strict=strict)
        self._parse_stmt_list(graph, directed)
        self._expect(_TK_RBRACE)
        # Trailing tokens (apart from EOF) are an error — DOT is a
        # single-graph format.
        tok = self._peek()
        if tok[0] != _TK_EOF:
            raise DotParseError(
                "unexpected trailing token %r" % tok[1], line_no=tok[2]
            )
        return graph

    def _parse_stmt_list(
        self,
        graph: Union[_Graph, _Subgraph],
        directed: bool,
    ) -> None:
        while True:
            tok = self._peek()
            if tok[0] == _TK_RBRACE or tok[0] == _TK_EOF:
                return
            if tok[0] == _TK_SEMI:
                self._advance()
                continue
            self._parse_stmt(graph, directed)

    def _parse_stmt(
        self,
        graph: Union[_Graph, _Subgraph],
        directed: bool,
    ) -> None:
        tok = self._peek()
        if tok[0] != _TK_ID:
            raise DotParseError(
                "expected identifier or keyword, got %r" % tok[1],
                line_no=tok[2],
            )

        # Subgraph statement — ``subgraph name? { ... }`` or
        # ``{ ... }`` (anonymous).
        lower = tok[1].lower()
        if lower == "subgraph":
            self._advance()
            sub_name: Optional[str] = None
            nxt = self._peek()
            if nxt[0] == _TK_ID:
                sub_name = nxt[1]
                self._advance()
            self._expect(_TK_LBRACE)
            sub = _Subgraph(sub_name or "")
            self._parse_stmt_list(sub, directed)
            self._expect(_TK_RBRACE)
            self._merge_subgraph(graph, sub)
            return
        if tok[0] == _TK_LBRACE:
            self._advance()
            sub = _Subgraph("")
            self._parse_stmt_list(sub, directed)
            self._expect(_TK_RBRACE)
            self._merge_subgraph(graph, sub)
            return
        if lower in ("node", "edge"):
            # Node-default / edge-default attribute block. We tolerate
            # the syntax but discard the values.
            self._advance()
            self._maybe_consume_attr_list()
            return
        if lower == "graph":
            # Graph-level attribute block — ``graph [label="X"]``.
            self._advance()
            captured = self._maybe_consume_attr_list()
            if isinstance(graph, _Subgraph) and "label" in captured:
                graph.label = captured["label"]
            return

        # ``ID = ID`` — graph-level attribute setter (e.g. ``rankdir=LR``).
        nxt = self._peek(1)
        if nxt[0] == _TK_EQ:
            self._advance()
            self._expect(_TK_EQ)
            value_tok = self._peek()
            if value_tok[0] != _TK_ID:
                raise DotParseError(
                    "expected attribute value, got %r" % value_tok[1],
                    line_no=value_tok[2],
                )
            value = value_tok[1]
            self._advance()
            if isinstance(graph, _Subgraph) and tok[1].lower() == "label":
                graph.label = value
            return

        # Node/edge statement starting with an identifier.
        first_id = self._parse_node_id()
        # Inline subgraph after the first ID? ``A -> { B C }`` form is
        # tolerated by stripping the braces and treating B / C as a
        # right-hand cluster of endpoints.
        nxt = self._peek()
        if nxt[0] in (_TK_DEDGE, _TK_UEDGE):
            # Edge chain: A op B (op C ...) [attrs]
            chain: List[Tuple[str, bool]] = [(first_id, False)]
            while True:
                op = self._peek()
                if op[0] not in (_TK_DEDGE, _TK_UEDGE):
                    break
                op_directed = op[0] == _TK_DEDGE
                if op_directed != directed:
                    raise DotParseError(
                        "edge operator %r does not match graph directedness"
                        % op[1],
                        line_no=op[2],
                    )
                self._advance()
                # RHS may be a single ID or an inline subgraph block.
                rhs_tok = self._peek()
                if rhs_tok[0] == _TK_LBRACE:
                    self._advance()
                    inner_ids: List[str] = []
                    while True:
                        inner = self._peek()
                        if inner[0] == _TK_RBRACE:
                            self._advance()
                            break
                        if inner[0] == _TK_SEMI:
                            self._advance()
                            continue
                        if inner[0] != _TK_ID:
                            raise DotParseError(
                                "unexpected token in edge subgraph %r"
                                % inner[1],
                                line_no=inner[2],
                            )
                        inner_ids.append(self._parse_node_id())
                    # Append every inner ID as a chained endpoint.
                    for iid in inner_ids:
                        chain.append((iid, op_directed))
                else:
                    next_id = self._parse_node_id()
                    chain.append((next_id, op_directed))
            attrs = self._maybe_consume_attr_list()
            self._add_chained_edges(graph, chain, directed, attrs)
            return

        # Node statement.
        attrs = self._maybe_consume_attr_list()
        self._add_node(graph, first_id, attrs)

    def _parse_node_id(self) -> str:
        tok = self._expect(_TK_ID)
        # Strip an optional port reference (``A:f1`` / ``A:f1:n``); we
        # don't model port semantics, but we tolerate the syntax.
        while self._peek()[0] == _TK_COLON:
            self._advance()
            self._expect(_TK_ID)
        return tok[1]

    def _maybe_consume_attr_list(self) -> Dict[str, str]:
        """Consume ``[k=v, k=v, ...] [k=v]`` series and return merged dict."""
        result: Dict[str, str] = {}
        while self._peek()[0] == _TK_LBRACKET:
            self._advance()
            while True:
                tok = self._peek()
                if tok[0] == _TK_RBRACKET:
                    self._advance()
                    break
                if tok[0] in (_TK_COMMA, _TK_SEMI):
                    self._advance()
                    continue
                if tok[0] != _TK_ID:
                    raise DotParseError(
                        "expected attribute name, got %r" % tok[1],
                        line_no=tok[2],
                    )
                k = self._advance()[1]
                eq = self._peek()
                if eq[0] != _TK_EQ:
                    raise DotParseError(
                        "expected '=' after attribute name %r" % k,
                        line_no=eq[2],
                    )
                self._advance()
                v_tok = self._peek()
                if v_tok[0] != _TK_ID:
                    raise DotParseError(
                        "expected attribute value, got %r" % v_tok[1],
                        line_no=v_tok[2],
                    )
                self._advance()
                result[k.lower()] = v_tok[1]
        return result

    def _add_node(
        self,
        graph: Union[_Graph, _Subgraph],
        name: str,
        attrs: Mapping[str, str],
    ) -> None:
        if isinstance(graph, _Subgraph):
            if name not in graph.members:
                graph.members.append(name)
            # The actual node record lives on the top-level graph; the
            # caller patches it in via :meth:`_merge_subgraph`.
            existing = graph._pending_attrs.get(name, {})
            existing.update(attrs)
            graph._pending_attrs[name] = existing
            return
        existing_node = graph.nodes.get(name)
        if existing_node is None:
            graph.nodes[name] = _Node(name=name, attrs=dict(attrs))
        else:
            existing_node.attrs.update(attrs)

    def _add_chained_edges(
        self,
        graph: Union[_Graph, _Subgraph],
        chain: List[Tuple[str, bool]],
        directed: bool,
        attrs: Mapping[str, str],
    ) -> None:
        # Make sure each endpoint is registered as a node.
        for name, _ in chain:
            self._add_node(graph, name, {})
        # Decompose ``A -> B -> C`` into pairwise edges.
        for ix in range(len(chain) - 1):
            from_name = chain[ix][0]
            to_name = chain[ix + 1][0]
            edge = _Edge(
                from_name=from_name,
                to_name=to_name,
                directed=directed,
                attrs=dict(attrs),
            )
            if isinstance(graph, _Subgraph):
                graph.edges.append(edge)
            else:
                graph.edges.append(edge)

    def _merge_subgraph(
        self,
        parent: Union[_Graph, _Subgraph],
        sub: _Subgraph,
    ) -> None:
        # Lift node records pinned to the subgraph up to the top-level
        # graph so attributes survive even though clusters render as
        # containers. Bare subgraphs (``{ A B }``) are flattened —
        # their nodes/edges promote to the parent. Cluster subgraphs
        # are preserved as wrappers.
        for name, attrs in sub._pending_attrs.items():
            if isinstance(parent, _Graph):
                node = parent.nodes.get(name)
                if node is None:
                    parent.nodes[name] = _Node(name=name, attrs=dict(attrs))
                else:
                    node.attrs.update(attrs)
            else:
                # Promote to grand-parent's pending bag.
                existing = parent._pending_attrs.get(name, {})
                existing.update(attrs)
                parent._pending_attrs[name] = existing
                if name not in parent.members:
                    parent.members.append(name)
        if not sub.is_cluster:
            # Flatten — propagate edges and member-list up.
            if isinstance(parent, _Graph):
                parent.edges.extend(sub.edges)
                for nested in sub.subgraphs:
                    parent.subgraphs.append(nested)
            else:
                parent.edges.extend(sub.edges)
                for nested in sub.subgraphs:
                    parent.subgraphs.append(nested)
                for name in sub.members:
                    if name not in parent.members:
                        parent.members.append(name)
            return
        # Cluster — record the subgraph on the parent.
        if isinstance(parent, _Graph):
            parent.subgraphs.append(sub)
        else:
            parent.subgraphs.append(sub)


def _parse_dot(source: str) -> _Graph:
    """Return the parsed AST for *source*."""
    tokens = _tokenise(source)
    parser = _Parser(tokens)
    return parser.parse_graph()


# ---------------------------------------------------------------------------
# Layout — simple top-down grid
# ---------------------------------------------------------------------------


def _resolve_shape_kind(raw: Optional[str]) -> str:
    """Return the renderable kind for a DOT ``shape=`` attribute value."""
    if raw is None:
        return "rectangle"
    return DOT_SHAPE_MAP.get(raw.strip().lower(), "rectangle")


def _resolve_label(node: _Node) -> str:
    """Return the rendered label for *node* — falls back to the node ID."""
    raw = node.attrs.get("label")
    if raw is None:
        return node.name
    if raw.startswith("<") and raw.endswith(">"):
        # HTML-like label — out-of-scope for rendering; show the node
        # name so the diagram is still readable.
        return node.name
    return raw


def _topological_levels(
    nodes: Sequence[str],
    edges: Sequence[_Edge],
) -> List[List[str]]:
    """Group *nodes* into top-down rows for the simple grid layout.

    Sources (no incoming edges) populate the first row; subsequent
    rows are formed by repeatedly removing the current row and
    re-computing source membership. Cycles are broken by emitting any
    remaining nodes as a final row in declaration order so the
    function is total.
    """
    incoming: Dict[str, set[str]] = {n: set() for n in nodes}
    for edge in edges:
        if edge.directed and edge.from_name in incoming and edge.to_name in incoming:
            if edge.from_name != edge.to_name:
                incoming[edge.to_name].add(edge.from_name)

    remaining = list(nodes)
    levels: List[List[str]] = []
    while remaining:
        current = [n for n in remaining if not incoming[n]]
        if not current:
            # Cycle / undirected graph — emit the rest as one row to
            # keep the function total. Preserves declaration order so
            # the layout stays deterministic.
            levels.append(remaining)
            return levels
        levels.append(current)
        consumed = set(current)
        remaining = [n for n in remaining if n not in consumed]
        for inc_set in incoming.values():
            inc_set.difference_update(consumed)
    return levels


def _node_size(node: _Node) -> Tuple[float, float]:
    """Return ``(width, height)`` for *node* in inches.

    Honours DOT's ``width=`` / ``height=`` numeric attributes when
    present (Graphviz uses inches as well, so the unit translates
    directly), otherwise falls back to the module defaults.
    """
    w = DOT_DEFAULT_NODE_WIDTH
    h = DOT_DEFAULT_NODE_HEIGHT
    raw_w = node.attrs.get("width")
    raw_h = node.attrs.get("height")
    if raw_w is not None:
        try:
            w = max(0.2, float(raw_w))
        except ValueError:
            pass
    if raw_h is not None:
        try:
            h = max(0.2, float(raw_h))
        except ValueError:
            pass
    return w, h


def _draw_node(
    page: Any,
    node: _Node,
    pin_x: float,
    pin_y: float,
    width: float,
    height: float,
) -> Shape:
    """Author *node* at the supplied position and return its proxy."""
    kind = _resolve_shape_kind(node.attrs.get("shape"))
    label = _resolve_label(node)

    if kind == "ellipse":
        proxy = page.shapes.add_shape(
            VS_SHAPE_TYPE.ELLIPSE,
            at=(pin_x, pin_y),
            size=(width, height),
            text=label,
        )
    elif kind == "diamond":
        proxy = page.shapes.add_custom_shape(
            at=(pin_x, pin_y),
            size=(width, height),
            master="Rectangle",
        )
        geometry = proxy.geometry
        geometry.move_to(0.5, 1.0)
        geometry.line_to(1.0, 0.5)
        geometry.line_to(0.5, 0.0)
        geometry.line_to(0.0, 0.5)
        geometry.close()
        proxy.text = label  # type: ignore[attr-defined]
    elif kind == "parallelogram":
        proxy = page.shapes.add_custom_shape(
            at=(pin_x, pin_y),
            size=(width, height),
            master="Rectangle",
        )
        # Parallelogram skewed to the right by 20% of the width.
        geometry = proxy.geometry
        geometry.move_to(0.2, 0.0)
        geometry.line_to(1.0, 0.0)
        geometry.line_to(0.8, 1.0)
        geometry.line_to(0.0, 1.0)
        geometry.close()
        proxy.text = label  # type: ignore[attr-defined]
    else:
        proxy = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(pin_x, pin_y),
            size=(width, height),
            text=label,
        )

    # Apply common styling attributes — DOT colours can be hex
    # (``#ff0000``), bare names (``red``), or RGBa tuples; we pass the
    # raw string straight through to the cell. The proxy stores it on
    # the Visio @V attribute as opaque text — Visio's layout engine
    # interprets it. Theme colours come through unchanged.
    color = node.attrs.get("color")
    if color is not None:
        try:
            proxy.line_color = color  # type: ignore[attr-defined]
        except Exception:
            pass
    fill = node.attrs.get("fillcolor")
    if fill is not None:
        try:
            proxy.fill_foregnd = fill  # type: ignore[attr-defined]
        except Exception:
            pass

    style = (node.attrs.get("style") or "").lower().strip()
    # ``style`` is a comma-separated list — we honour the single
    # tokens we support and ignore the rest.
    if style:
        tokens = {t.strip() for t in style.split(",") if t.strip()}
        if "dashed" in tokens or "dotted" in tokens:
            try:
                # LinePattern V=2 is a dashed pattern; V=4 is dotted.
                # Both are stable across Visio releases.
                v = "2" if "dashed" in tokens else "4"
                cell = proxy._element.get_or_add_cell("LinePattern")
                cell.set("V", v)
            except Exception:
                pass
    return proxy


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def document_from_dot_string(
    source: str,
    *,
    page_name: Optional[str] = None,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
) -> VisioDocument:
    """Parse *source* (DOT text) and author the matching Visio document.

    :param source: DOT-language source text. Both ``digraph`` and
        ``graph`` forms are accepted; the parser auto-detects the
        directedness from the keyword.
    :param page_name: optional ``@NameU`` for the rendered page.
        Defaults to the graph's declared name (``digraph X { ... }``)
        or ``"DOT graph"`` when the graph is anonymous.
    :param page_width: optional explicit page width in inches. When
        omitted the page sizes itself to fit the laid-out grid plus
        :data:`DOT_DEFAULT_PAGE_MARGIN` margins.
    :param page_height: optional explicit page height in inches.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises DotParseError: when *source* is not valid DOT.
    :raises TypeError: when *source* is not a ``str``.

    .. versionadded:: 0.4.0
    """
    if not isinstance(source, str):
        raise TypeError(
            "source must be a str (got %r)" % type(source).__name__
        )

    graph = _parse_dot(source)
    return _build_document(
        graph,
        page_name=page_name,
        page_width=page_width,
        page_height=page_height,
    )


def document_from_dot(
    path: Union[str, "os.PathLike[str]"],
    *,
    page_name: Optional[str] = None,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    encoding: str = "utf-8",
) -> VisioDocument:
    """Read a DOT file from *path* and author the matching Visio document.

    :param path: filesystem path to a ``.dot`` / ``.gv`` source file.
    :param page_name: forwarded to :func:`document_from_dot_string`.
    :param page_width: forwarded to :func:`document_from_dot_string`.
    :param page_height: forwarded to :func:`document_from_dot_string`.
    :param encoding: text encoding used to decode the file. Defaults
        to ``"utf-8"`` — Graphviz's own canonical encoding.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises DotParseError: when the file cannot be parsed.
    :raises OSError: when *path* cannot be read.

    .. versionadded:: 0.4.0
    """
    with open(os.fspath(path), "r", encoding=encoding) as fh:
        text = fh.read()
    return document_from_dot_string(
        text,
        page_name=page_name,
        page_width=page_width,
        page_height=page_height,
    )


def _build_document(
    graph: _Graph,
    *,
    page_name: Optional[str],
    page_width: Optional[float],
    page_height: Optional[float],
) -> VisioDocument:
    """Convert the parsed AST *graph* into a :class:`VisioDocument`."""
    # -- 1. Assemble the ordered node list (declaration order). -------
    declared: List[str] = list(graph.nodes.keys())
    # Walk every cluster and append any cluster-local node that hasn't
    # already been seen at the top level — this keeps the layout grid
    # row-coherent even when a cluster declares its own members.
    for sub in graph.subgraphs:
        for member in sub.members:
            if member not in graph.nodes:
                graph.nodes[member] = _Node(name=member, attrs={})
                declared.append(member)
    # Subgraph membership index — node-name to cluster index.
    cluster_of: Dict[str, int] = {}
    clusters_with_members: List[Tuple[int, _Subgraph, List[str]]] = []
    for ix, sub in enumerate(graph.subgraphs):
        members = [m for m in sub.members if m in graph.nodes]
        clusters_with_members.append((ix, sub, members))
        for m in members:
            cluster_of.setdefault(m, ix)

    # -- 2. Compute the row layout. -----------------------------------
    levels = _topological_levels(declared, graph.edges)

    # -- 3. Compute geometry. -----------------------------------------
    margin = DOT_DEFAULT_PAGE_MARGIN
    h_gap = DOT_DEFAULT_HORIZONTAL_GAP
    v_gap = DOT_DEFAULT_VERTICAL_GAP

    # Per-node size — measured up-front so the row geometry can centre
    # nodes regardless of variable width.
    sizes: Dict[str, Tuple[float, float]] = {}
    for name, node in graph.nodes.items():
        sizes[name] = _node_size(node)

    # Row widths and heights.
    row_widths: List[float] = []
    row_heights: List[float] = []
    for level in levels:
        if not level:
            row_widths.append(0.0)
            row_heights.append(0.0)
            continue
        widths = [sizes[n][0] for n in level]
        heights = [sizes[n][1] for n in level]
        row_widths.append(sum(widths) + h_gap * (len(level) - 1))
        row_heights.append(max(heights))

    grid_width = max(row_widths) if row_widths else 0.0
    grid_height = (
        sum(row_heights) + v_gap * max(0, len(row_heights) - 1)
        if row_heights
        else 0.0
    )

    # Cluster padding — every cluster expands by 2*padding in each
    # axis to accommodate the wrap. We only adjust grid_height /
    # grid_width once all members are known.
    cluster_extra_w = 0.0
    cluster_extra_h = 0.0
    for _ix, _sub, members in clusters_with_members:
        if members:
            cluster_extra_w = max(cluster_extra_w, 2 * DOT_DEFAULT_CLUSTER_PADDING)
            cluster_extra_h += 2 * DOT_DEFAULT_CLUSTER_PADDING

    final_w = page_width if page_width is not None else (
        grid_width + 2 * margin + cluster_extra_w
    )
    final_h = page_height if page_height is not None else (
        grid_height + 2 * margin + cluster_extra_h
    )
    # Guard against absurd minima — a one-shape diagram needs enough
    # canvas for the shape + margins.
    final_w = max(final_w, 4.0)
    final_h = max(final_h, 3.0)

    # -- 4. Build the document. ---------------------------------------
    doc = Visio()
    name = page_name
    if name is None:
        name = graph.name or "DOT graph"
    page = doc.pages.add_page(name=name, width=final_w, height=final_h)

    # Y-cursor descends from the top of the inner page; the first row
    # sits at ``final_h - margin - row_h0/2``.
    proxies: Dict[str, Shape] = {}
    y_cursor = final_h - margin
    for level, row_w, row_h in zip(levels, row_widths, row_heights):
        if row_h <= 0:
            continue
        row_pin_y = y_cursor - row_h / 2.0
        # Centre the row on the page horizontally.
        x_cursor = (final_w - row_w) / 2.0
        for name in level:
            node = graph.nodes[name]
            w, h = sizes[name]
            pin_x = x_cursor + w / 2.0
            proxy = _draw_node(page, node, pin_x, row_pin_y, w, h)
            proxies[name] = proxy
            x_cursor += w + h_gap
        y_cursor -= row_h + v_gap

    # -- 5. Cluster containers (drawn before edges so the connectors
    #       glue between member shapes, not the cluster wrapper). ----
    _ = clusters_with_members  # silence linters when no clusters present
    for _ix, sub, members in clusters_with_members:
        members_in_doc = [m for m in members if m in proxies]
        if not members_in_doc:
            continue
        # Bounding box of every member.
        min_x = min(
            float(proxies[m].pin_x) - float(proxies[m].width) / 2.0
            for m in members_in_doc
        )
        max_x = max(
            float(proxies[m].pin_x) + float(proxies[m].width) / 2.0
            for m in members_in_doc
        )
        min_y = min(
            float(proxies[m].pin_y) - float(proxies[m].height) / 2.0
            for m in members_in_doc
        )
        max_y = max(
            float(proxies[m].pin_y) + float(proxies[m].height) / 2.0
            for m in members_in_doc
        )
        pad = DOT_DEFAULT_CLUSTER_PADDING
        c_w = (max_x - min_x) + 2 * pad
        c_h = (max_y - min_y) + 2 * pad
        c_pin_x = (min_x + max_x) / 2.0
        c_pin_y = (min_y + max_y) / 2.0
        wrap = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(c_pin_x, c_pin_y),
            size=(c_w, c_h),
            text=sub.label or sub.name,
        )
        # Visually distinguish the cluster wrapper — dashed outline.
        try:
            cell = wrap._element.get_or_add_cell("LinePattern")
            cell.set("V", "2")
        except Exception:
            pass
        # Move the wrapper to the *back* so edge connectors paint above
        # it — Visio renders shapes in document order, and a fresh
        # rectangle would otherwise sit in front of every member.
        try:
            page_contents = page.shapes._element.shapes_element  # type: ignore[attr-defined]
            shape_lst = page_contents.shape_lst
            # Remove and re-insert as the first shape.
            page_contents.remove(wrap._element)
            page_contents.insert(0, wrap._element)
            del shape_lst  # silence linter
        except Exception:
            pass

    # -- 6. Edges. ----------------------------------------------------
    # We accumulate every edge from the top-level graph and from the
    # nested clusters so the connectors land regardless of how the
    # author grouped them.
    every_edge: List[_Edge] = list(graph.edges)
    for sub in graph.subgraphs:
        every_edge.extend(sub.edges)

    for edge in every_edge:
        from_proxy = proxies.get(edge.from_name)
        to_proxy = proxies.get(edge.to_name)
        if from_proxy is None or to_proxy is None:
            # Endpoint isn't in the rendered grid — ignore. This
            # arises when an edge references a node that was declared
            # only as an attribute target inside a node-default block.
            continue
        try:
            conn = page.add_connector(
                from_proxy,
                to_proxy,
                routing=ROUTING_RIGHT_ANGLE,
            )
        except Exception:
            # Routing can fail if the two shapes overlap exactly; fall
            # back to a straight connector with no routing, which is
            # always safe.
            conn = page.add_connector(from_proxy, to_proxy)
        # Edge label, if any.
        label = edge.attrs.get("label")
        if label and not (label.startswith("<") and label.endswith(">")):
            try:
                conn.text = label  # type: ignore[attr-defined]
            except Exception:
                pass
        # Edge style — dashed / dotted line patterns.
        style = (edge.attrs.get("style") or "").lower().strip()
        if style:
            tokens = {t.strip() for t in style.split(",") if t.strip()}
            if "dashed" in tokens or "dotted" in tokens:
                try:
                    cell = conn._element.get_or_add_cell("LinePattern")
                    cell.set("V", "2" if "dashed" in tokens else "4")
                except Exception:
                    pass
        # Edge colour.
        edge_color = edge.attrs.get("color")
        if edge_color is not None:
            try:
                conn.line_color = edge_color  # type: ignore[attr-defined]
            except Exception:
                pass

    return doc


# Used to keep ``_TK_*`` symbols reachable for tooling / introspection
# without exposing them as public API.
_TOKEN_KINDS: Tuple[str, ...] = (
    _TK_ID,
    _TK_LBRACE,
    _TK_RBRACE,
    _TK_LBRACKET,
    _TK_RBRACKET,
    _TK_SEMI,
    _TK_COMMA,
    _TK_EQ,
    _TK_DEDGE,
    _TK_UEDGE,
    _TK_COLON,
    _TK_EOF,
)


__all__ = [
    "DOT_DEFAULT_CLUSTER_PADDING",
    "DOT_DEFAULT_HORIZONTAL_GAP",
    "DOT_DEFAULT_NODE_HEIGHT",
    "DOT_DEFAULT_NODE_WIDTH",
    "DOT_DEFAULT_PAGE_MARGIN",
    "DOT_DEFAULT_VERTICAL_GAP",
    "DOT_SHAPE_KINDS",
    "DOT_SHAPE_MAP",
    "DotParseError",
    "document_from_dot",
    "document_from_dot_string",
]
