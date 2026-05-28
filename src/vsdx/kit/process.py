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
"""SIPOC + process-map diagram templates — issue #128.

Two kit builders that turn plain-Python descriptions into
:class:`~vsdx.document.VisioDocument` instances:

* :func:`build_sipoc` — the five-column **S**uppliers / **I**nputs /
  **P**rocess / **O**utputs / **C**ustomers table that anchors a Six
  Sigma "define" phase. The output is a literal table-on-a-page: one
  header band and five fixed-width columns, each populated with a
  vertical stack of named cells.
* :func:`build_process_map` — a vertical flowchart driven by a list of
  steps. Each step carries a ``kind`` token that picks its glyph
  (``start`` / ``end`` → ellipse, ``task`` → rectangle, ``decision``
  → diamond) and an optional ``on`` label that records the branch a
  decision step belongs to ("yes" / "no" / arbitrary string). Steps
  are connected top-to-bottom in declaration order via right-angle
  dynamic connectors, with auto-routing courtesy of issue #53.

Layout follows the same conventions as
:mod:`vsdx.kit.swim_lanes`: landscape page with a title band along
the top, fixed margins, fixed step-shape sizes. Tweakable via the
``page_width`` / ``page_height`` kwargs.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.routing import ROUTING_RIGHT_ANGLE
from vsdx.shapes.base import Shape


# ---------------------------------------------------------------------------
# Public constants — process-map step kinds
# ---------------------------------------------------------------------------

#: ``kind`` token for an entry-point step — rendered as a rounded shape.
PROCESS_KIND_START: str = "start"

#: ``kind`` token for a terminating step — rendered as a rounded shape.
PROCESS_KIND_END: str = "end"

#: ``kind`` token for an action step — rendered as a plain rectangle.
PROCESS_KIND_TASK: str = "task"

#: ``kind`` token for a branching step — rendered as a diamond.
PROCESS_KIND_DECISION: str = "decision"

#: Frozen tuple of every recognised process-map step-kind token.
PROCESS_STEP_KINDS: Tuple[str, ...] = (
    PROCESS_KIND_START,
    PROCESS_KIND_TASK,
    PROCESS_KIND_DECISION,
    PROCESS_KIND_END,
)


#: Canonical SIPOC column order.
SIPOC_COLUMN_ORDER: Tuple[str, ...] = (
    "Suppliers",
    "Inputs",
    "Process",
    "Outputs",
    "Customers",
)


StepLike = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Layout constants — kept module-private; tweakable via build kwargs
# ---------------------------------------------------------------------------

# SIPOC layout
_SIPOC_PAGE_MARGIN_X: float = 0.5
_SIPOC_PAGE_MARGIN_Y: float = 0.5
_SIPOC_TITLE_BAND_HEIGHT: float = 0.6
_SIPOC_HEADER_BAND_HEIGHT: float = 0.5
_SIPOC_CELL_HEIGHT: float = 0.55
_SIPOC_CELL_VERTICAL_GAP: float = 0.15
_SIPOC_CELL_HORIZONTAL_PADDING: float = 0.15

_SIPOC_DEFAULT_PAGE_WIDTH: float = 14.0
_SIPOC_DEFAULT_PAGE_HEIGHT: float = 8.5

# Process-map layout
_PMAP_PAGE_MARGIN_X: float = 0.5
_PMAP_PAGE_MARGIN_Y: float = 0.5
_PMAP_TITLE_BAND_HEIGHT: float = 0.6
_PMAP_STEP_WIDTH: float = 2.5
_PMAP_STEP_HEIGHT: float = 0.8
_PMAP_STEP_VERTICAL_GAP: float = 0.45

_PMAP_DEFAULT_PAGE_WIDTH: float = 8.5
_PMAP_DEFAULT_PAGE_HEIGHT: float = 11.0


# ---------------------------------------------------------------------------
# SIPOC helpers
# ---------------------------------------------------------------------------


def _validate_sipoc_column(values: Sequence[str], *, name: str) -> List[str]:
    """Coerce *values* to a list of non-empty ``str`` and validate."""
    if values is None:
        raise TypeError(
            "SIPOC column %r: values must be a sequence of str, got None" % name
        )
    out: List[str] = []
    for ix, v in enumerate(values):
        if not isinstance(v, str) or not v:
            raise ValueError(
                "SIPOC column %r entry %d must be a non-empty str (got %r)"
                % (name, ix, v)
            )
        out.append(v)
    return out


def _sipoc_geometry(
    page_width: float,
    page_height: float,
) -> Tuple[float, float, float, List[float]]:
    """Return ``(col_width, header_top, body_top, [col_centre_x, ...])``.

    ``header_top`` is the Y of the top edge of the header band; the
    body fills the rest of the inner page. Column centres are returned
    in :data:`SIPOC_COLUMN_ORDER` order.
    """
    inner_w = page_width - 2 * _SIPOC_PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _SIPOC_PAGE_MARGIN_X)
        )
    col_count = len(SIPOC_COLUMN_ORDER)
    col_width = inner_w / col_count

    header_top = page_height - _SIPOC_PAGE_MARGIN_Y - _SIPOC_TITLE_BAND_HEIGHT
    body_top = header_top - _SIPOC_HEADER_BAND_HEIGHT
    if body_top - _SIPOC_PAGE_MARGIN_Y <= 0:
        raise ValueError(
            "page_height=%r is too small for the title + header bands"
            % page_height
        )

    centres: List[float] = []
    for i in range(col_count):
        centres.append(_SIPOC_PAGE_MARGIN_X + (i + 0.5) * col_width)
    return col_width, header_top, body_top, centres


def _sipoc_cell_pin_y(ix: int, body_top: float) -> float:
    """Centre-pin Y of the *ix*-th cell (zero-based) inside a column."""
    centre_offset = (
        _SIPOC_CELL_VERTICAL_GAP
        + (ix * (_SIPOC_CELL_HEIGHT + _SIPOC_CELL_VERTICAL_GAP))
        + _SIPOC_CELL_HEIGHT / 2
    )
    return body_top - centre_offset


# ---------------------------------------------------------------------------
# Public builder — SIPOC
# ---------------------------------------------------------------------------


def build_sipoc(
    *,
    title: str,
    suppliers: Sequence[str],
    inputs: Sequence[str],
    process_steps: Sequence[str],
    outputs: Sequence[str],
    customers: Sequence[str],
    page_width: float = _SIPOC_DEFAULT_PAGE_WIDTH,
    page_height: float = _SIPOC_DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Author a five-column SIPOC table and return the document.

    SIPOC ("**S**uppliers / **I**nputs / **P**rocess / **O**utputs /
    **C**ustomers") is the canonical Six Sigma scoping diagram. The
    output is a literal table-on-a-page: a title band, a header band
    naming each column, and five fixed-width columns each containing
    a vertical stack of named cells.

    :param title: caption rendered in the page's title band.
    :param suppliers: ordered iterable of supplier names.
    :param inputs: ordered iterable of input names.
    :param process_steps: ordered iterable of high-level process step
        names. SIPOC traditionally lists 4-7 steps here — this builder
        does not enforce that bound.
    :param outputs: ordered iterable of output names.
    :param customers: ordered iterable of customer names.
    :param page_width: page width in inches. Default: ``14.0``
        (landscape).
    :param page_height: page height in inches. Default: ``8.5``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title* (whitespace-trimmed); falls back to ``"SIPOC"`` when
        *title* is empty.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *title* is not a ``str``.
    :raises ValueError: when any column entry is not a non-empty
        ``str``, or when the page is too small to accommodate the
        title + header bands.

    .. versionadded:: 0.4.0
    """
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)

    columns: Dict[str, List[str]] = {
        "Suppliers": _validate_sipoc_column(suppliers, name="Suppliers"),
        "Inputs": _validate_sipoc_column(inputs, name="Inputs"),
        "Process": _validate_sipoc_column(process_steps, name="Process"),
        "Outputs": _validate_sipoc_column(outputs, name="Outputs"),
        "Customers": _validate_sipoc_column(customers, name="Customers"),
    }

    col_width, header_top, body_top, col_centres = _sipoc_geometry(
        page_width, page_height
    )

    doc = Visio()
    name = page_name or title.strip() or "SIPOC"
    page = doc.pages.add_page(name=name, width=page_width, height=page_height)

    # -- Title band ------------------------------------------------------
    inner_w = page_width - 2 * _SIPOC_PAGE_MARGIN_X
    title_pin_x = _SIPOC_PAGE_MARGIN_X + inner_w / 2
    title_pin_y = page_height - _SIPOC_PAGE_MARGIN_Y - _SIPOC_TITLE_BAND_HEIGHT / 2
    if title:
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(inner_w, _SIPOC_TITLE_BAND_HEIGHT),
            text=title,
        )

    # -- Header band — one rectangle per column --------------------------
    header_pin_y = header_top - _SIPOC_HEADER_BAND_HEIGHT / 2
    for col_name, x_centre in zip(SIPOC_COLUMN_ORDER, col_centres):
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(x_centre, header_pin_y),
            size=(col_width, _SIPOC_HEADER_BAND_HEIGHT),
            text=col_name,
        )

    # -- Column body — a stack of cells per column -----------------------
    cell_w = max(0.1, col_width - 2 * _SIPOC_CELL_HORIZONTAL_PADDING)
    for col_name, x_centre in zip(SIPOC_COLUMN_ORDER, col_centres):
        for ix, value in enumerate(columns[col_name]):
            pin_y = _sipoc_cell_pin_y(ix, body_top)
            page.shapes.add_shape(
                VS_SHAPE_TYPE.RECTANGLE,
                at=(x_centre, pin_y),
                size=(cell_w, _SIPOC_CELL_HEIGHT),
                text=value,
            )

    return doc


# ---------------------------------------------------------------------------
# Process-map helpers
# ---------------------------------------------------------------------------


def _pmap_step_text(step: StepLike, *, ix: int) -> str:
    if "text" not in step:
        raise ValueError(
            "process-map step %d is missing a required 'text' key" % ix
        )
    text = step["text"]
    if not isinstance(text, str) or not text:
        raise ValueError(
            "process-map step %d 'text' must be a non-empty str (got %r)"
            % (ix, text)
        )
    return text


def _pmap_step_kind(step: StepLike, *, ix: int) -> str:
    if "kind" not in step:
        raise ValueError(
            "process-map step %d is missing a required 'kind' key" % ix
        )
    raw = step["kind"]
    if not isinstance(raw, str):
        raise ValueError(
            "process-map step %d 'kind' must be a str (got %r)" % (ix, raw)
        )
    if raw not in PROCESS_STEP_KINDS:
        raise ValueError(
            "process-map step %d 'kind' must be one of %r (got %r)"
            % (ix, PROCESS_STEP_KINDS, raw)
        )
    return raw


def _pmap_step_on(step: StepLike, *, ix: int) -> Optional[str]:
    if "on" not in step:
        return None
    raw = step["on"]
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise ValueError(
            "process-map step %d 'on' must be a non-empty str or omitted "
            "(got %r)" % (ix, raw)
        )
    return raw


def _pmap_add_step_shape(
    page: Any,
    *,
    kind: str,
    text: str,
    pin_x: float,
    pin_y: float,
    width: float,
    height: float,
) -> Shape:
    """Drop the per-kind shape, set its label, return the proxy."""
    if kind in (PROCESS_KIND_START, PROCESS_KIND_END):
        return page.shapes.add_shape(
            VS_SHAPE_TYPE.ELLIPSE,
            at=(pin_x, pin_y),
            size=(width, height),
            text=text,
        )

    if kind == PROCESS_KIND_DECISION:
        shape = page.shapes.add_custom_shape(
            at=(pin_x, pin_y),
            size=(width, height),
            master="Rectangle",
        )
        # Diamond geometry — same authoring as the swim-lanes kit so
        # both kits produce visually consistent decision symbols.
        geometry = shape.geometry
        geometry.move_to(0.5, 1.0)
        geometry.line_to(1.0, 0.5)
        geometry.line_to(0.5, 0.0)
        geometry.line_to(0.0, 0.5)
        geometry.close()
        shape.text = text  # type: ignore[attr-defined]
        return shape

    # Default — a plain rectangle (PROCESS_KIND_TASK).
    return page.shapes.add_shape(
        VS_SHAPE_TYPE.RECTANGLE,
        at=(pin_x, pin_y),
        size=(width, height),
        text=text,
    )


# ---------------------------------------------------------------------------
# Public builder — process map
# ---------------------------------------------------------------------------


def build_process_map(
    *,
    title: str,
    steps: Sequence[StepLike],
    flows: Optional[Iterable[Tuple[str, str]]] = None,
    page_width: float = _PMAP_DEFAULT_PAGE_WIDTH,
    page_height: float = _PMAP_DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
) -> VisioDocument:
    """Author a vertical process-map flowchart and return the document.

    A process map is a single-column flowchart: each step is dropped
    on a vertical centreline in declaration order, and adjacent steps
    are connected via right-angle dynamic connectors.

    :param title: caption rendered in the page's title band.
    :param steps: iterable of step descriptors. Each step is a
        ``Mapping[str, Any]`` with the keys:

        * ``"kind"`` (required) — one of the tokens in
          :data:`PROCESS_STEP_KINDS`. Picks the step's glyph.
        * ``"text"`` (required) — the step's label, also used as the
          flow-edge identifier when *flows* is given.
        * ``"on"`` (optional) — branch label associated with the step.
          Conventionally ``"yes"`` / ``"no"`` for the two arms of a
          ``decision`` step. Stored on the step proxy as a side
          channel (the connector glyph itself is not labelled in
          0.4.0 — caller can post-process via the returned document if
          needed).

    :param flows: optional iterable of ``(from_text, to_text)`` tuples
        to override the default sequential wiring. When omitted (the
        common case), connectors are emitted between consecutive steps
        in declaration order. When provided, the explicit list
        replaces the auto-wiring entirely; both endpoints must match a
        step's ``text``.

    :param page_width: page width in inches. Default: ``8.5``
        (portrait).
    :param page_height: page height in inches. Default: ``11.0``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title* (whitespace-trimmed); falls back to ``"Process map"``
        when *title* is empty.
    :param routing: connector routing mode forwarded to
        :func:`vsdx.routing.route_connector`. Default:
        :data:`vsdx.routing.ROUTING_RIGHT_ANGLE`.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *title* is not a ``str``.
    :raises ValueError: when *steps* is empty, when any step is
        missing ``kind`` / ``text``, when ``kind`` is unrecognised,
        when step ``text`` collides with another step, when an
        explicit *flows* tuple references an unknown step, or when
        the page is too small for the title band.

    .. versionadded:: 0.4.0
    """
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)

    step_list: List[StepLike] = list(steps)
    if not step_list:
        raise ValueError("steps must contain at least one step")

    # Validate every step and build a name -> step-index map.
    seen_text: Dict[str, int] = {}
    parsed: List[Tuple[str, str, Optional[str]]] = []
    for ix, step in enumerate(step_list):
        kind = _pmap_step_kind(step, ix=ix)
        text = _pmap_step_text(step, ix=ix)
        on = _pmap_step_on(step, ix=ix)
        if text in seen_text:
            raise ValueError(
                "process-map step text %r duplicated (steps %d and %d) — "
                "flow edges use 'text' as the unique key, so labels must "
                "be unique" % (text, seen_text[text], ix)
            )
        seen_text[text] = ix
        parsed.append((kind, text, on))

    # Decide on the flow list.
    if flows is None:
        flow_list: List[Tuple[str, str]] = [
            (parsed[i][1], parsed[i + 1][1]) for i in range(len(parsed) - 1)
        ]
    else:
        flow_list = list(flows)
        for from_name, to_name in flow_list:
            if from_name not in seen_text:
                raise ValueError(
                    "flow %r → %r references unknown step %r"
                    % (from_name, to_name, from_name)
                )
            if to_name not in seen_text:
                raise ValueError(
                    "flow %r → %r references unknown step %r"
                    % (from_name, to_name, to_name)
                )

    # -- Geometry checks --------------------------------------------------
    inner_w = page_width - 2 * _PMAP_PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _PMAP_PAGE_MARGIN_X)
        )
    body_top = page_height - _PMAP_PAGE_MARGIN_Y - _PMAP_TITLE_BAND_HEIGHT
    if body_top - _PMAP_PAGE_MARGIN_Y <= 0:
        raise ValueError(
            "page_height=%r is too small for the title band" % page_height
        )

    # -- Document + page --------------------------------------------------
    doc = Visio()
    name = page_name or title.strip() or "Process map"
    page = doc.pages.add_page(name=name, width=page_width, height=page_height)

    # -- Title band -------------------------------------------------------
    title_pin_x = _PMAP_PAGE_MARGIN_X + inner_w / 2
    title_pin_y = page_height - _PMAP_PAGE_MARGIN_Y - _PMAP_TITLE_BAND_HEIGHT / 2
    if title:
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(inner_w, _PMAP_TITLE_BAND_HEIGHT),
            text=title,
        )

    # -- Step shapes — single vertical column ----------------------------
    centre_x = _PMAP_PAGE_MARGIN_X + inner_w / 2
    step_w = min(_PMAP_STEP_WIDTH, max(0.1, inner_w - 0.2))
    step_h = _PMAP_STEP_HEIGHT
    proxies: Dict[str, Shape] = {}
    for ix, (kind, text, _on) in enumerate(parsed):
        centre_offset = (
            _PMAP_STEP_VERTICAL_GAP
            + (ix * (step_h + _PMAP_STEP_VERTICAL_GAP))
            + step_h / 2
        )
        pin_y = body_top - centre_offset
        proxy = _pmap_add_step_shape(
            page,
            kind=kind,
            text=text,
            pin_x=centre_x,
            pin_y=pin_y,
            width=step_w,
            height=step_h,
        )
        proxies[text] = proxy

    # -- Flow connectors -------------------------------------------------
    for from_name, to_name in flow_list:
        page.add_connector(
            proxies[from_name],
            proxies[to_name],
            routing=routing,
        )

    return doc


__all__ = [
    "PROCESS_KIND_DECISION",
    "PROCESS_KIND_END",
    "PROCESS_KIND_START",
    "PROCESS_KIND_TASK",
    "PROCESS_STEP_KINDS",
    "SIPOC_COLUMN_ORDER",
    "StepLike",
    "build_process_map",
    "build_sipoc",
]
