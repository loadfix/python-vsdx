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
"""Cross-functional / swim-lane diagram template — issue #121.

Build a Visio swim-lane (a.k.a. "cross-functional flowchart") from a
plain-Python description::

    from vsdx.kit.swim_lanes import build_swim_lane_diagram

    diagram = build_swim_lane_diagram(
        title="Order processing",
        lanes=["Customer", "Sales", "Warehouse", "Finance"],
        steps=[
            {"lane": "Customer",  "text": "Place order",       "kind": "start"},
            {"lane": "Sales",     "text": "Validate order"},
            {"lane": "Warehouse", "text": "Pick + pack"},
            {"lane": "Customer", "text": "Receive shipment", "kind": "end"},
            {"lane": "Finance",   "text": "Send invoice"},
        ],
        flows=[
            ("Place order",     "Validate order"),
            ("Validate order",  "Pick + pack"),
            ("Pick + pack",     "Receive shipment"),
            ("Validate order",  "Send invoice"),
        ],
    )
    diagram.save("order-processing.vsdx")

Layout
------

* The page is laid out in landscape with vertical lanes of equal
  width. ``page_width`` and ``page_height`` are caller-tunable but
  default to 14" x 8.5".
* A title band runs across the top of the page.
* A header band beneath it holds each lane's name (Visio's standard
  cross-functional convention — Microsoft's built-in template uses
  the same arrangement).
* Each lane body is a tall rectangle outline covering the rest of the
  page. Step shapes auto-stack inside their lane top-to-bottom in
  declaration order.
* Flows are emitted as right-angle dynamic connectors between the
  step shapes, with names matched verbatim from the *flows* tuples
  against the steps' ``text``.

Step kinds
----------

The optional ``kind`` key on each step picks the shape:

* ``start`` / ``end`` → a rounded shape (``Ellipse`` master) — the
  standard "terminator" symbol in flowchart notation.
* ``decision`` → a diamond, authored as a custom shape with a
  four-segment closed path.
* default (omit ``kind`` or pass ``"step"``) → a plain ``Rectangle``.

The set of recognised kind tokens is exposed as the
:data:`SWIM_LANE_STEP_KINDS` tuple.

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
# Public constants
# ---------------------------------------------------------------------------

#: ``kind`` token for an entry-point step — rendered as a rounded shape.
SWIM_LANE_KIND_START: str = "start"

#: ``kind`` token for a terminating step — rendered as a rounded shape.
SWIM_LANE_KIND_END: str = "end"

#: ``kind`` token for a branching step — rendered as a diamond.
SWIM_LANE_KIND_DECISION: str = "decision"

#: ``kind`` token for the default rectangular step. Omitting ``kind``
#: from a step dict has the same effect.
SWIM_LANE_KIND_DEFAULT: str = "step"

#: Frozen tuple of every recognised step-kind token, in canonical order.
SWIM_LANE_STEP_KINDS: Tuple[str, ...] = (
    SWIM_LANE_KIND_START,
    SWIM_LANE_KIND_END,
    SWIM_LANE_KIND_DECISION,
    SWIM_LANE_KIND_DEFAULT,
)


# A swim-lane "step" is described as a small dict. We accept either
# ``Mapping[str, Any]`` (the doc-string spelling) or any object that
# quacks the same way; the keys we read are listed in :func:`_step_text`,
# :func:`_step_lane`, :func:`_step_kind`.
StepLike = Mapping[str, Any]
FlowLike = Tuple[str, str]


# ---------------------------------------------------------------------------
# Layout constants — kept module-private; tweakable via build kwargs
# ---------------------------------------------------------------------------

# Margins — the page region we author into.
_PAGE_MARGIN_X: float = 0.5  # inches on left + right
_PAGE_MARGIN_Y: float = 0.5  # inches on top + bottom

# Title band — one fat rectangle across the top of the lanes.
_TITLE_BAND_HEIGHT: float = 0.6  # inches

# Header band — lane-name rectangles directly under the title.
_HEADER_BAND_HEIGHT: float = 0.5

# Step shape size + vertical spacing between consecutive steps in a lane.
_STEP_HEIGHT: float = 0.6
_STEP_VERTICAL_GAP: float = 0.3
_STEP_HORIZONTAL_PADDING: float = 0.25  # gap between step edge and lane wall

# Default page geometry — landscape orientation suits multi-lane diagrams.
_DEFAULT_PAGE_WIDTH: float = 14.0
_DEFAULT_PAGE_HEIGHT: float = 8.5


# ---------------------------------------------------------------------------
# Step-dict accessors
# ---------------------------------------------------------------------------


def _step_text(step: StepLike, *, ix: int) -> str:
    """Return the ``text`` of *step*, raising on absent / non-string."""
    if "text" not in step:
        raise ValueError(
            "swim-lane step %d is missing a required 'text' key" % ix
        )
    text = step["text"]
    if not isinstance(text, str) or not text:
        raise ValueError(
            "swim-lane step %d 'text' must be a non-empty str (got %r)"
            % (ix, text)
        )
    return text


def _step_lane(step: StepLike, *, ix: int) -> str:
    """Return the ``lane`` of *step*, raising on absent / non-string."""
    if "lane" not in step:
        raise ValueError(
            "swim-lane step %d is missing a required 'lane' key" % ix
        )
    lane = step["lane"]
    if not isinstance(lane, str) or not lane:
        raise ValueError(
            "swim-lane step %d 'lane' must be a non-empty str (got %r)"
            % (ix, lane)
        )
    return lane


def _step_kind(step: StepLike, *, ix: int) -> str:
    """Return the ``kind`` of *step*, defaulting to ``"step"``."""
    raw = step.get("kind", SWIM_LANE_KIND_DEFAULT)
    if not isinstance(raw, str):
        raise ValueError(
            "swim-lane step %d 'kind' must be a str (got %r)" % (ix, raw)
        )
    if raw not in SWIM_LANE_STEP_KINDS:
        raise ValueError(
            "swim-lane step %d 'kind' must be one of %r (got %r)"
            % (ix, SWIM_LANE_STEP_KINDS, raw)
        )
    return raw


# ---------------------------------------------------------------------------
# Lane / step layout maths
# ---------------------------------------------------------------------------


def _lane_geometry(
    lanes: Sequence[str],
    page_width: float,
    page_height: float,
) -> Dict[str, Tuple[float, float, float, float]]:
    """Return ``{lane_name: (x_centre, lane_top, lane_width, body_height)}``.

    The lane region runs from just under the header band down to the
    bottom margin. ``x_centre`` is the lane's centre-pin X (inches in
    page coordinates).
    """
    inner_w = page_width - 2 * _PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _PAGE_MARGIN_X)
        )
    lane_width = inner_w / len(lanes)

    # In Visio, Y=0 is the BOTTOM of the page. lane_top = the y of the
    # lane body's top edge.
    lane_top = page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT - _HEADER_BAND_HEIGHT
    body_height = lane_top - _PAGE_MARGIN_Y
    if body_height <= 0:
        raise ValueError(
            "page_height=%r is too small for the title + header bands"
            % page_height
        )

    out: Dict[str, Tuple[float, float, float, float]] = {}
    for i, name in enumerate(lanes):
        x_centre = _PAGE_MARGIN_X + (i + 0.5) * lane_width
        out[name] = (x_centre, lane_top, lane_width, body_height)
    return out


def _step_pin_y(step_index_in_lane: int, lane_top: float) -> float:
    """Return the centre-pin Y for the *step_index_in_lane*-th step in a lane.

    Steps stack down from just below the lane's top edge. Indexing is
    zero-based; the first step's centre is one half-step + spacing
    below ``lane_top``.
    """
    centre_offset = (
        _STEP_VERTICAL_GAP
        + (step_index_in_lane * (_STEP_HEIGHT + _STEP_VERTICAL_GAP))
        + _STEP_HEIGHT / 2
    )
    return lane_top - centre_offset


# ---------------------------------------------------------------------------
# Shape-author dispatch per kind
# ---------------------------------------------------------------------------


def _add_step_shape(
    page: Any,
    *,
    kind: str,
    text: str,
    pin_x: float,
    pin_y: float,
    width: float,
    height: float,
) -> Shape:
    """Drop the per-kind shape, set its label, return the proxy.

    Branches:

    * ``start`` / ``end`` → :class:`vsdx.shapes.autoshape.Ellipse`
      (the standard rounded "terminator" in flowchart notation).
    * ``decision`` → :func:`page.shapes.add_custom_shape` with a
      four-segment diamond path.
    * everything else → plain :class:`vsdx.shapes.autoshape.Rectangle`.
    """
    if kind in (SWIM_LANE_KIND_START, SWIM_LANE_KIND_END):
        shape = page.shapes.add_shape(
            VS_SHAPE_TYPE.ELLIPSE,
            at=(pin_x, pin_y),
            size=(width, height),
            text=text,
        )
        return shape

    if kind == SWIM_LANE_KIND_DECISION:
        shape = page.shapes.add_custom_shape(
            at=(pin_x, pin_y),
            size=(width, height),
            master="Rectangle",
        )
        # Diamond geometry — author in shape-local coordinates where
        # (0, 0) is the bottom-left and (1, 1) is the top-right (Visio's
        # default for custom shape paths). Verts: top, right, bottom,
        # left; closed via :meth:`Geometry.close`.
        geometry = shape.geometry
        geometry.move_to(0.5, 1.0)
        geometry.line_to(1.0, 0.5)
        geometry.line_to(0.5, 0.0)
        geometry.line_to(0.0, 0.5)
        geometry.close()
        # Drop the label via the text setter on the underlying
        # TextShape.
        shape.text = text  # type: ignore[attr-defined]
        return shape

    # Default — a plain rectangle.
    shape = page.shapes.add_shape(
        VS_SHAPE_TYPE.RECTANGLE,
        at=(pin_x, pin_y),
        size=(width, height),
        text=text,
    )
    return shape


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_swim_lane_diagram(
    *,
    title: str,
    lanes: Sequence[str],
    steps: Sequence[StepLike],
    flows: Iterable[FlowLike] = (),
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
) -> VisioDocument:
    """Author a swim-lane (cross-functional flowchart) and return the document.

    :param title: caption rendered in the page's title band.
    :param lanes: ordered iterable of lane names. Each lane becomes a
        vertical column of equal width; the order of *lanes* is the
        left-to-right order on the page.
    :param steps: iterable of step descriptors. Each step is a dict
        with the keys:

        * ``"lane"`` (required) — the lane name; must appear in
          *lanes*.
        * ``"text"`` (required) — the step's label, also used as the
          flow-edge identifier.
        * ``"kind"`` (optional) — one of the tokens in
          :data:`SWIM_LANE_STEP_KINDS`. Defaults to
          ``SWIM_LANE_KIND_DEFAULT``.

        Steps are stacked top-to-bottom inside their lane in the order
        they appear in *steps*.

    :param flows: iterable of ``(from_text, to_text)`` tuples. Each
        tuple is rendered as a right-angle dynamic connector between
        the two step shapes. Both ``from_text`` and ``to_text`` must
        match a step's ``text`` exactly (string equality). Defaults to
        an empty sequence — a swim-lane diagram with no flows is
        legal (e.g. a stub diagram waiting on a later authoring pass).

    :param page_width: page width in inches. Default: 14.0 (landscape).
    :param page_height: page height in inches. Default: 8.5.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title* (whitespace-trimmed); falls back to ``"Page-1"`` when
        *title* is empty.
    :param routing: connector routing mode forwarded to
        :func:`vsdx.routing.route_connector`. Default:
        :data:`vsdx.routing.ROUTING_RIGHT_ANGLE` — the conventional
        right-angle "elbow" routing used by every swim-lane template
        Microsoft ships.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises ValueError: when *lanes* is empty, when a step references
        a lane that is not in *lanes*, when step ``text`` values
        collide (flow-edge ambiguity), when a flow tuple references
        a step ``text`` that does not exist, or when the page is too
        small to accommodate the title + header bands.

    .. versionadded:: 0.4.0
    """
    # -- 1. Argument validation ------------------------------------------
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)
    lane_list: List[str] = list(lanes)
    if not lane_list:
        raise ValueError("lanes must contain at least one lane name")
    if len(set(lane_list)) != len(lane_list):
        raise ValueError(
            "lanes must be unique; got duplicates in %r" % lane_list
        )
    step_list: List[StepLike] = list(steps)
    if not step_list:
        raise ValueError("steps must contain at least one step")
    flow_list: List[FlowLike] = list(flows)

    # Validate step coherence and build a name -> step-index map.
    seen_text: Dict[str, int] = {}
    for ix, step in enumerate(step_list):
        text = _step_text(step, ix=ix)
        lane_name = _step_lane(step, ix=ix)
        _step_kind(step, ix=ix)  # raises on invalid kind
        if lane_name not in lane_list:
            raise ValueError(
                "step %d 'lane'=%r is not in lanes=%r" % (ix, lane_name, lane_list)
            )
        if text in seen_text:
            raise ValueError(
                "step text %r duplicated (steps %d and %d) — flow edges "
                "use 'text' as the unique key, so labels must be unique"
                % (text, seen_text[text], ix)
            )
        seen_text[text] = ix

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

    # -- 2. Document + page ----------------------------------------------
    doc = Visio()
    name = (page_name or title.strip() or "Page-1")
    page = doc.pages.add_page(name=name, width=page_width, height=page_height)

    # -- 3. Title band ----------------------------------------------------
    title_pin_y = page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT / 2
    inner_w = page_width - 2 * _PAGE_MARGIN_X
    title_pin_x = _PAGE_MARGIN_X + inner_w / 2
    if title:
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(inner_w, _TITLE_BAND_HEIGHT),
            text=title,
        )

    # -- 4. Lane headers + lane body outlines ----------------------------
    geometry_for_lane = _lane_geometry(lane_list, page_width, page_height)
    header_pin_y = (
        page_height
        - _PAGE_MARGIN_Y
        - _TITLE_BAND_HEIGHT
        - _HEADER_BAND_HEIGHT / 2
    )
    for lane_name in lane_list:
        x_centre, lane_top, lane_width, body_height = geometry_for_lane[lane_name]
        # Header rectangle (one per lane, sitting beneath the title).
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(x_centre, header_pin_y),
            size=(lane_width, _HEADER_BAND_HEIGHT),
            text=lane_name,
        )
        # Body outline — the tall rectangle that contains the steps.
        body_pin_y = lane_top - body_height / 2
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(x_centre, body_pin_y),
            size=(lane_width, body_height),
        )

    # -- 5. Step shapes (stacked top-to-bottom inside each lane) ---------
    step_proxies: Dict[str, Shape] = {}
    lane_step_count: Dict[str, int] = {n: 0 for n in lane_list}
    for ix, step in enumerate(step_list):
        text = _step_text(step, ix=ix)
        lane_name = _step_lane(step, ix=ix)
        kind = _step_kind(step, ix=ix)
        x_centre, lane_top, lane_width, _body_h = geometry_for_lane[lane_name]
        step_index = lane_step_count[lane_name]
        lane_step_count[lane_name] += 1

        step_w = max(0.1, lane_width - 2 * _STEP_HORIZONTAL_PADDING)
        step_h = _STEP_HEIGHT
        pin_y = _step_pin_y(step_index, lane_top)
        proxy = _add_step_shape(
            page,
            kind=kind,
            text=text,
            pin_x=x_centre,
            pin_y=pin_y,
            width=step_w,
            height=step_h,
        )
        step_proxies[text] = proxy

    # -- 6. Flow connectors ----------------------------------------------
    for from_name, to_name in flow_list:
        page.add_connector(
            step_proxies[from_name],
            step_proxies[to_name],
            routing=routing,
        )

    return doc


__all__ = [
    "SWIM_LANE_KIND_DECISION",
    "SWIM_LANE_KIND_DEFAULT",
    "SWIM_LANE_KIND_END",
    "SWIM_LANE_KIND_START",
    "SWIM_LANE_STEP_KINDS",
    "FlowLike",
    "StepLike",
    "build_swim_lane_diagram",
]
