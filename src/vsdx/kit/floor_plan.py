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
"""Floor-plan diagram template — issue #127.

Author a Visio floor plan from plain-Python descriptions of rooms,
furniture, and fixtures::

    from vsdx.kit.floor_plan import build_floor_plan

    diagram = build_floor_plan(
        title="Office floor plan — level 3",
        rooms=[
            {"name": "Reception",      "x": 0, "y": 0, "width": 4, "height": 3,
             "unit": "meters"},
            {"name": "Open office",    "x": 4, "y": 0, "width": 12, "height": 8},
            {"name": "Meeting room A", "x": 16, "y": 0, "width": 4, "height": 3,
             "capacity": 6},
            {"name": "Kitchen",        "x": 0, "y": 3, "width": 4, "height": 3},
            {"name": "Bathroom",       "x": 0, "y": 6, "width": 2, "height": 2},
        ],
        furniture=[
            {"kind": "desk",  "x": 5,   "y": 1,   "rotation": 0},
            {"kind": "desk",  "x": 8,   "y": 1,   "rotation": 0},
            {"kind": "chair", "x": 5.5, "y": 1.7, "rotation": 0},
            {"kind": "sofa",  "x": 1,   "y": 0.5, "rotation": 0},
        ],
        fixtures=[
            {"kind": "door",   "x": 4, "y": 1.5, "wall": "left", "width": 1},
            {"kind": "window", "x": 8, "y": 0,   "wall": "top",  "width": 2},
        ],
    )
    diagram.save("floor-plan-l3.vsdx")

Coordinate system
-----------------

All ``x`` / ``y`` values in *rooms* / *furniture* / *fixtures* are
**bottom-left-anchored** — ``(0, 0)`` is the bottom-left corner of the
floor plan, matching Visio's native page-coordinate convention. Every
element specifies its **bottom-left corner** (not its centre); the
builder converts each to Visio's centre-pin (``PinX`` / ``PinY``)
convention internally.

Units
-----

The default unit is **feet** — matches Visio's default drawing scale
on the Office floor-plan template family. Per-element ``"unit"``
overrides are supported; passing ``"meters"`` (or the alias ``"m"``)
on a room scales that room's geometry to feet via the
:data:`METERS_PER_FOOT` factor. Furniture / fixture coordinates inherit
the *plan-wide* unit (set on :func:`build_floor_plan` via the ``unit``
kwarg, default ``"feet"``); per-room unit overrides only affect the
room's own geometry, never furniture placed inside it.

Furniture kinds
---------------

The recognised :data:`FURNITURE_KINDS` are ``desk``, ``chair``,
``sofa``, ``bed``, ``table``, ``bookshelf``. Each is rendered as a
scaled rectangle at the per-kind default footprint (see
:data:`FURNITURE_DEFAULT_SIZES`); a per-element ``width`` / ``height``
override is honoured when supplied. The shape's text label is the
furniture kind so the diagram remains readable in Visio's outline
view.

Fixture kinds
-------------

The recognised :data:`FIXTURE_KINDS` are ``door`` and ``window``.
Both are drawn as **openings on a wall** — a thin rectangle whose
long edge is parallel to the wall it pierces. The ``wall`` field
(``"left"`` / ``"right"`` / ``"top"`` / ``"bottom"``) picks which
edge of the room the opening sits on; the ``width`` field sets the
opening size along the wall.

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
from vsdx.shapes.base import Shape

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Furniture kind tokens recognised by :func:`build_floor_plan`. Every
#: kind renders as a labelled rectangle scaled to the corresponding
#: entry in :data:`FURNITURE_DEFAULT_SIZES`.
FURNITURE_KIND_DESK: str = "desk"
FURNITURE_KIND_CHAIR: str = "chair"
FURNITURE_KIND_SOFA: str = "sofa"
FURNITURE_KIND_BED: str = "bed"
FURNITURE_KIND_TABLE: str = "table"
FURNITURE_KIND_BOOKSHELF: str = "bookshelf"

#: Frozen tuple of every recognised furniture-kind token.
FURNITURE_KINDS: Tuple[str, ...] = (
    FURNITURE_KIND_DESK,
    FURNITURE_KIND_CHAIR,
    FURNITURE_KIND_SOFA,
    FURNITURE_KIND_BED,
    FURNITURE_KIND_TABLE,
    FURNITURE_KIND_BOOKSHELF,
)

#: Per-kind default footprint in **feet** (the canonical floor-plan
#: unit). When ``width`` / ``height`` are omitted from a furniture
#: dict, these dimensions are used; per-element overrides are honoured
#: as-given (in the plan's unit).
FURNITURE_DEFAULT_SIZES: Dict[str, Tuple[float, float]] = {
    FURNITURE_KIND_DESK: (5.0, 2.5),
    FURNITURE_KIND_CHAIR: (1.5, 1.5),
    FURNITURE_KIND_SOFA: (6.0, 3.0),
    FURNITURE_KIND_BED: (5.0, 6.5),
    FURNITURE_KIND_TABLE: (4.0, 3.0),
    FURNITURE_KIND_BOOKSHELF: (3.0, 1.0),
}

#: Fixture kind tokens recognised by :func:`build_floor_plan`. Both are
#: drawn as thin rectangles (openings) on the wall picked by the
#: ``wall`` field.
FIXTURE_KIND_DOOR: str = "door"
FIXTURE_KIND_WINDOW: str = "window"

#: Frozen tuple of every recognised fixture-kind token.
FIXTURE_KINDS: Tuple[str, ...] = (
    FIXTURE_KIND_DOOR,
    FIXTURE_KIND_WINDOW,
)

#: Wall side tokens accepted on a fixture's ``wall`` field.
FIXTURE_WALL_SIDES: Tuple[str, ...] = ("left", "right", "top", "bottom")

#: Conversion factor — ``1 metre == 3.28084 feet``. Used when a room
#: declares ``"unit": "meters"`` (or ``"m"``) to scale that room's
#: geometry into the plan's underlying foot grid.
METERS_PER_FOOT: float = 3.280839895013123

#: Recognised unit tokens. The default plan-wide unit is ``"feet"`` —
#: matches Microsoft Visio's stock floor-plan template.
UNIT_FEET: str = "feet"
UNIT_METERS: str = "meters"
UNIT_TOKENS: Tuple[str, ...] = (UNIT_FEET, UNIT_METERS, "ft", "m")

# Default page geometry — landscape suits a typical office floor plan.
_DEFAULT_PAGE_WIDTH: float = 30.0
_DEFAULT_PAGE_HEIGHT: float = 20.0
_PAGE_MARGIN: float = 1.0
_TITLE_BAND_HEIGHT: float = 1.2

# Fixture cosmetics — wall openings render as thin rectangles. The
# "thickness" axis (perpendicular to the wall) is small so the opening
# reads as an architectural notch, not a full-height shape.
_FIXTURE_THICKNESS: float = 0.4

# Public types — described loosely with Mapping[str, Any] so callers
# can pass dataclasses / TypedDicts / plain dicts interchangeably.
RoomLike = Mapping[str, Any]
FurnitureLike = Mapping[str, Any]
FixtureLike = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def _normalise_unit(raw: Any, *, what: str, ix: Optional[int] = None) -> str:
    """Return the canonical unit token for *raw*.

    Accepts ``"feet"`` / ``"ft"`` / ``"meters"`` / ``"m"``; raises a
    :class:`ValueError` otherwise. *what* and *ix* feed the error
    message so a caller sees which dict the bad token came from.
    """
    if not isinstance(raw, str):
        loc = "" if ix is None else " %d" % ix
        raise ValueError(
            "%s%s 'unit' must be a str (got %r)" % (what, loc, raw)
        )
    lowered = raw.strip().lower()
    if lowered in ("feet", "ft"):
        return UNIT_FEET
    if lowered in ("meters", "metres", "m"):
        return UNIT_METERS
    loc = "" if ix is None else " %d" % ix
    raise ValueError(
        "%s%s 'unit' must be one of %r (got %r)"
        % (what, loc, UNIT_TOKENS, raw)
    )


def _to_feet(value: float, unit: str) -> float:
    """Return *value* converted from *unit* into feet."""
    if unit == UNIT_FEET:
        return value
    if unit == UNIT_METERS:
        return value * METERS_PER_FOOT
    # _normalise_unit funnels every accepted token to feet/meters.
    raise AssertionError("unreachable: unknown canonical unit %r" % unit)


# ---------------------------------------------------------------------------
# Dict-shape validation helpers
# ---------------------------------------------------------------------------


def _required_float(
    obj: Mapping[str, Any], key: str, *, what: str, ix: int
) -> float:
    """Return ``float(obj[key])``; raise on absent or non-numeric."""
    if key not in obj:
        raise ValueError(
            "%s %d is missing a required %r key" % (what, ix, key)
        )
    raw = obj[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(
            "%s %d %r must be a number (got %r)" % (what, ix, key, raw)
        )
    return float(raw)


def _optional_float(
    obj: Mapping[str, Any], key: str, *, what: str, ix: int
) -> Optional[float]:
    """Return ``float(obj[key])`` or ``None`` when *key* is absent."""
    if key not in obj or obj[key] is None:
        return None
    raw = obj[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(
            "%s %d %r must be a number or None (got %r)"
            % (what, ix, key, raw)
        )
    return float(raw)


def _required_string(
    obj: Mapping[str, Any], key: str, *, what: str, ix: int
) -> str:
    """Return non-empty ``str(obj[key])``; raise otherwise."""
    if key not in obj:
        raise ValueError(
            "%s %d is missing a required %r key" % (what, ix, key)
        )
    raw = obj[key]
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(
            "%s %d %r must be a non-empty str (got %r)"
            % (what, ix, key, raw)
        )
    return raw


# ---------------------------------------------------------------------------
# Per-element parsers — return a normalised tuple of feet-coordinates
# ---------------------------------------------------------------------------


# A parsed room: (name, x_ft, y_ft, w_ft, h_ft, capacity_or_None).
ParsedRoom = Tuple[str, float, float, float, float, Optional[int]]

# A parsed furniture item: (kind, x_ft, y_ft, w_ft, h_ft, rotation_deg).
ParsedFurniture = Tuple[str, float, float, float, float, float]

# A parsed fixture: (kind, room_name, wall_side, position_ft, width_ft).
# room_name resolves to ``None`` when the fixture sits on a wall not
# bordering any room (rare; we still emit the shape for fidelity).
ParsedFixture = Tuple[str, str, float, float]


def _parse_room(
    room: RoomLike, *, ix: int, plan_unit: str
) -> ParsedRoom:
    """Validate and return a normalised room tuple in feet."""
    if not isinstance(room, Mapping):
        raise ValueError(
            "room %d must be a Mapping (got %r)" % (ix, type(room).__name__)
        )
    name = _required_string(room, "name", what="room", ix=ix)
    x = _required_float(room, "x", what="room", ix=ix)
    y = _required_float(room, "y", what="room", ix=ix)
    w = _required_float(room, "width", what="room", ix=ix)
    h = _required_float(room, "height", what="room", ix=ix)
    if w <= 0:
        raise ValueError("room %d 'width' must be > 0 (got %r)" % (ix, w))
    if h <= 0:
        raise ValueError("room %d 'height' must be > 0 (got %r)" % (ix, h))
    unit = (
        _normalise_unit(room["unit"], what="room", ix=ix)
        if "unit" in room and room["unit"] is not None
        else plan_unit
    )
    x_ft = _to_feet(x, unit)
    y_ft = _to_feet(y, unit)
    w_ft = _to_feet(w, unit)
    h_ft = _to_feet(h, unit)
    capacity: Optional[int] = None
    if "capacity" in room and room["capacity"] is not None:
        raw_cap = room["capacity"]
        if isinstance(raw_cap, bool) or not isinstance(raw_cap, int):
            raise ValueError(
                "room %d 'capacity' must be an int or None (got %r)"
                % (ix, raw_cap)
            )
        if raw_cap < 0:
            raise ValueError(
                "room %d 'capacity' must be >= 0 (got %r)" % (ix, raw_cap)
            )
        capacity = raw_cap
    return (name, x_ft, y_ft, w_ft, h_ft, capacity)


def _parse_furniture(
    item: FurnitureLike, *, ix: int, plan_unit: str
) -> ParsedFurniture:
    """Validate and return a normalised furniture tuple in feet."""
    if not isinstance(item, Mapping):
        raise ValueError(
            "furniture %d must be a Mapping (got %r)"
            % (ix, type(item).__name__)
        )
    kind = _required_string(item, "kind", what="furniture", ix=ix)
    if kind not in FURNITURE_KINDS:
        raise ValueError(
            "furniture %d 'kind' must be one of %r (got %r)"
            % (ix, FURNITURE_KINDS, kind)
        )
    x = _required_float(item, "x", what="furniture", ix=ix)
    y = _required_float(item, "y", what="furniture", ix=ix)
    unit = (
        _normalise_unit(item["unit"], what="furniture", ix=ix)
        if "unit" in item and item["unit"] is not None
        else plan_unit
    )
    default_w, default_h = FURNITURE_DEFAULT_SIZES[kind]
    raw_w = _optional_float(item, "width", what="furniture", ix=ix)
    raw_h = _optional_float(item, "height", what="furniture", ix=ix)
    w = default_w if raw_w is None else raw_w
    h = default_h if raw_h is None else raw_h
    if w <= 0:
        raise ValueError(
            "furniture %d 'width' must be > 0 (got %r)" % (ix, w)
        )
    if h <= 0:
        raise ValueError(
            "furniture %d 'height' must be > 0 (got %r)" % (ix, h)
        )
    rotation = _optional_float(item, "rotation", what="furniture", ix=ix)
    rotation_deg = 0.0 if rotation is None else rotation
    x_ft = _to_feet(x, unit)
    y_ft = _to_feet(y, unit)
    # When a custom width/height is given, it's already in the same unit
    # as x/y. Default sizes are stated in feet so they don't need
    # converting.
    if raw_w is None:
        w_ft = w
    else:
        w_ft = _to_feet(w, unit)
    if raw_h is None:
        h_ft = h
    else:
        h_ft = _to_feet(h, unit)
    return (kind, x_ft, y_ft, w_ft, h_ft, rotation_deg)


def _parse_fixture(
    fixture: FixtureLike, *, ix: int, plan_unit: str
) -> Tuple[str, str, float, float, float, float]:
    """Return (kind, wall, x_ft, y_ft, width_ft, unit_used).

    Fixtures sit on a wall — their ``x`` / ``y`` is the *position*
    along that wall, expressed at the wall's running edge. We keep the
    geometry mostly raw at this stage and resolve the centre-pin
    coordinates in :func:`_drop_fixture` once the wall side is known.
    """
    if not isinstance(fixture, Mapping):
        raise ValueError(
            "fixture %d must be a Mapping (got %r)"
            % (ix, type(fixture).__name__)
        )
    kind = _required_string(fixture, "kind", what="fixture", ix=ix)
    if kind not in FIXTURE_KINDS:
        raise ValueError(
            "fixture %d 'kind' must be one of %r (got %r)"
            % (ix, FIXTURE_KINDS, kind)
        )
    wall = _required_string(fixture, "wall", what="fixture", ix=ix)
    if wall not in FIXTURE_WALL_SIDES:
        raise ValueError(
            "fixture %d 'wall' must be one of %r (got %r)"
            % (ix, FIXTURE_WALL_SIDES, wall)
        )
    x = _required_float(fixture, "x", what="fixture", ix=ix)
    y = _required_float(fixture, "y", what="fixture", ix=ix)
    width = _required_float(fixture, "width", what="fixture", ix=ix)
    if width <= 0:
        raise ValueError(
            "fixture %d 'width' must be > 0 (got %r)" % (ix, width)
        )
    unit = (
        _normalise_unit(fixture["unit"], what="fixture", ix=ix)
        if "unit" in fixture and fixture["unit"] is not None
        else plan_unit
    )
    x_ft = _to_feet(x, unit)
    y_ft = _to_feet(y, unit)
    width_ft = _to_feet(width, unit)
    return (kind, wall, x_ft, y_ft, width_ft, 0.0)


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_floor_plan(
    *,
    title: str = "",
    rooms: Sequence[RoomLike],
    furniture: Iterable[FurnitureLike] = (),
    fixtures: Iterable[FixtureLike] = (),
    unit: str = UNIT_FEET,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Author a floor-plan diagram and return the document.

    :param title: optional caption rendered above the floor plan in a
        fat banner. Pass ``""`` (the default) to suppress.
    :param rooms: ordered iterable of room descriptors. Each room is a
        ``Mapping[str, Any]`` with the keys:

        * ``"name"`` (required) — non-empty room label.
        * ``"x"`` / ``"y"`` (required) — bottom-left corner of the room
          in plan coordinates.
        * ``"width"`` / ``"height"`` (required) — room footprint.
        * ``"unit"`` (optional) — per-room unit override; one of
          ``"feet"`` / ``"ft"`` / ``"meters"`` / ``"m"``. Defaults to
          the plan-wide *unit*.
        * ``"capacity"`` (optional) — non-negative integer. Stored on
          the room's shape data as ``"Capacity"`` so a downstream
          data-graphic / Visio's shape-data pane can pick it up.

    :param furniture: iterable of furniture descriptors. Each is a
        ``Mapping[str, Any]`` with the keys:

        * ``"kind"`` (required) — one of :data:`FURNITURE_KINDS`.
        * ``"x"`` / ``"y"`` (required) — bottom-left corner of the
          piece.
        * ``"width"`` / ``"height"`` (optional) — overrides the
          per-kind default in :data:`FURNITURE_DEFAULT_SIZES`.
        * ``"rotation"`` (optional) — rotation in degrees (default 0).
        * ``"unit"`` (optional) — per-element unit override.

    :param fixtures: iterable of fixture descriptors. Each is a
        ``Mapping[str, Any]`` with the keys:

        * ``"kind"`` (required) — one of :data:`FIXTURE_KINDS`.
        * ``"x"`` / ``"y"`` (required) — anchor point on the wall.
        * ``"width"`` (required) — opening size along the wall.
        * ``"wall"`` (required) — one of :data:`FIXTURE_WALL_SIDES`.
        * ``"unit"`` (optional) — per-element unit override.

    :param unit: plan-wide default unit. Default: ``"feet"``.
    :param page_width: page width in inches (Visio's drawing unit at
        the OXML layer). When ``None``, the builder picks a width that
        fits the rooms' bounding box plus margins.
    :param page_height: page height in inches. When ``None``, the
        builder picks a height that fits the bounding box plus
        margins.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title* (whitespace-trimmed); falls back to ``"Floor plan"``
        when *title* is empty.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *title* is not a ``str``.
    :raises ValueError: when *rooms* is empty, when any element fails
        the per-key validation rules above, when a fixture's ``wall``
        is not in :data:`FIXTURE_WALL_SIDES`, or when the page would
        have non-positive dimensions.

    .. versionadded:: 0.4.0
    """
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)
    plan_unit = _normalise_unit(unit, what="plan unit")

    room_list = list(rooms)
    if not room_list:
        raise ValueError("rooms must contain at least one room")
    parsed_rooms: List[ParsedRoom] = [
        _parse_room(r, ix=ix, plan_unit=plan_unit)
        for ix, r in enumerate(room_list)
    ]
    seen_room_names: Dict[str, int] = {}
    for ix, (rname, *_rest) in enumerate(parsed_rooms):
        if rname in seen_room_names:
            raise ValueError(
                "room name %r duplicated (entries %d and %d) — names must "
                "be unique" % (rname, seen_room_names[rname], ix)
            )
        seen_room_names[rname] = ix

    parsed_furniture: List[ParsedFurniture] = [
        _parse_furniture(f, ix=ix, plan_unit=plan_unit)
        for ix, f in enumerate(furniture)
    ]
    parsed_fixtures: List[Tuple[str, str, float, float, float, float]] = [
        _parse_fixture(fx, ix=ix, plan_unit=plan_unit)
        for ix, fx in enumerate(fixtures)
    ]

    # -- Plan bounding box ------------------------------------------------
    max_x_ft = max(rx + rw for _n, rx, _ry, rw, _rh, _c in parsed_rooms)
    max_y_ft = max(ry + rh for _n, _rx, ry, _rw, rh, _c in parsed_rooms)

    # The page is sized in inches at the OXML layer. We treat the
    # "drawing units" as 1 inch = 1 foot of plan — that's how Visio's
    # stock floor-plan template is wired (drawing scale 1' = 1'' in
    # imperial mode). Auto-sized pages add a small margin on every side
    # plus a title band when a title is present.
    title_offset = _TITLE_BAND_HEIGHT if title else 0.0
    inferred_w = max_x_ft + 2 * _PAGE_MARGIN
    inferred_h = max_y_ft + 2 * _PAGE_MARGIN + title_offset
    page_w = (
        _DEFAULT_PAGE_WIDTH
        if page_width is None and inferred_w <= _DEFAULT_PAGE_WIDTH
        else (inferred_w if page_width is None else float(page_width))
    )
    page_h = (
        _DEFAULT_PAGE_HEIGHT
        if page_height is None and inferred_h <= _DEFAULT_PAGE_HEIGHT
        else (inferred_h if page_height is None else float(page_height))
    )
    if page_w <= 0:
        raise ValueError("page_width must be > 0 (got %r)" % page_w)
    if page_h <= 0:
        raise ValueError("page_height must be > 0 (got %r)" % page_h)

    # -- Document + page --------------------------------------------------
    doc = Visio()
    name = page_name or title.strip() or "Floor plan"
    page = doc.pages.add_page(name=name, width=page_w, height=page_h)

    # Origin of the plan inside the page — bottom-left corner of the
    # rooms region. Leaves a margin all round and keeps the title band
    # above when present. Visio's coordinate system has Y growing
    # upwards from the bottom edge, which matches the plan convention
    # so no Y-flip is needed.
    origin_x = _PAGE_MARGIN
    origin_y = _PAGE_MARGIN

    # -- Title band -------------------------------------------------------
    if title:
        title_pin_x = page_w / 2
        title_pin_y = page_h - _PAGE_MARGIN - _TITLE_BAND_HEIGHT / 2
        title_w = page_w - 2 * _PAGE_MARGIN
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(title_w, _TITLE_BAND_HEIGHT),
            text=title,
        )

    # -- Rooms ------------------------------------------------------------
    room_proxies: Dict[str, Shape] = {}
    room_geometry: Dict[str, Tuple[float, float, float, float]] = {}
    for rname, rx, ry, rw, rh, capacity in parsed_rooms:
        pin_x = origin_x + rx + rw / 2
        pin_y = origin_y + ry + rh / 2
        proxy = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(pin_x, pin_y),
            size=(rw, rh),
            text=rname,
        )
        if capacity is not None:
            proxy.data.add_field("Capacity", str(capacity), label="Capacity")
        room_proxies[rname] = proxy
        # Record the room's page-coordinate bounding box (bottom-left
        # corner + width/height) so fixtures-on-wall can resolve their
        # geometry without re-reading the proxy's pin/size.
        room_geometry[rname] = (
            origin_x + rx,
            origin_y + ry,
            rw,
            rh,
        )

    # -- Furniture --------------------------------------------------------
    for kind, fx, fy, fw, fh, rotation in parsed_furniture:
        pin_x = origin_x + fx + fw / 2
        pin_y = origin_y + fy + fh / 2
        proxy = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(pin_x, pin_y),
            size=(fw, fh),
            text=kind,
        )
        if rotation:
            # Visio's Angle cell takes radians.
            try:
                proxy.angle = rotation * 3.141592653589793 / 180.0
            except Exception:
                # Fallback path: store rotation on shape data for
                # round-trip preservation if the proxy doesn't expose
                # an angle setter at this version.
                proxy.data.add_field(
                    "Rotation", str(rotation), label="Rotation (deg)"
                )

    # -- Fixtures ---------------------------------------------------------
    for kind, wall, fx, fy, fwidth, _unused in parsed_fixtures:
        _drop_fixture(
            page=page,
            kind=kind,
            wall=wall,
            x_ft=fx,
            y_ft=fy,
            width_ft=fwidth,
            origin=(origin_x, origin_y),
        )

    return doc


# ---------------------------------------------------------------------------
# Fixture rendering — wall openings drawn as thin rectangles
# ---------------------------------------------------------------------------


def _drop_fixture(
    *,
    page: Any,
    kind: str,
    wall: str,
    x_ft: float,
    y_ft: float,
    width_ft: float,
    origin: Tuple[float, float],
) -> Shape:
    """Drop a fixture (door / window) on *page* and return the proxy.

    The fixture is rendered as a thin rectangle whose long axis runs
    parallel to the wall it sits on. Top / bottom walls give a
    horizontal opening (long axis = X); left / right walls give a
    vertical opening (long axis = Y). The (x_ft, y_ft) anchor is the
    fixture's *bottom-left corner* in plan coordinates, matching the
    room-corner convention.
    """
    origin_x, origin_y = origin
    if wall in ("top", "bottom"):
        # Horizontal opening — the wall runs along X, so the opening's
        # long axis is also along X.
        long_axis = width_ft
        short_axis = _FIXTURE_THICKNESS
        pin_x = origin_x + x_ft + long_axis / 2
        pin_y = origin_y + y_ft + short_axis / 2
        size = (long_axis, short_axis)
    else:
        # Vertical opening — left / right walls run along Y, so the
        # opening's long axis is along Y.
        long_axis = width_ft
        short_axis = _FIXTURE_THICKNESS
        pin_x = origin_x + x_ft + short_axis / 2
        pin_y = origin_y + y_ft + long_axis / 2
        size = (short_axis, long_axis)
    label = kind  # Keep the label compact so it reads well in Visio.
    proxy = page.shapes.add_shape(
        VS_SHAPE_TYPE.RECTANGLE,
        at=(pin_x, pin_y),
        size=size,
        text=label,
    )
    # Tag the opening with its fixture kind + wall on shape data so a
    # downstream consumer can filter doors-vs-windows without having to
    # parse the on-shape text.
    proxy.data.add_field("Kind", kind, label="Kind")
    proxy.data.add_field("Wall", wall, label="Wall")
    return proxy


__all__ = [
    "FIXTURE_KIND_DOOR",
    "FIXTURE_KIND_WINDOW",
    "FIXTURE_KINDS",
    "FIXTURE_WALL_SIDES",
    "FURNITURE_DEFAULT_SIZES",
    "FURNITURE_KINDS",
    "FURNITURE_KIND_BED",
    "FURNITURE_KIND_BOOKSHELF",
    "FURNITURE_KIND_CHAIR",
    "FURNITURE_KIND_DESK",
    "FURNITURE_KIND_SOFA",
    "FURNITURE_KIND_TABLE",
    "FixtureLike",
    "FurnitureLike",
    "METERS_PER_FOOT",
    "RoomLike",
    "UNIT_FEET",
    "UNIT_METERS",
    "UNIT_TOKENS",
    "build_floor_plan",
]
