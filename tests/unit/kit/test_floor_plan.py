# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.floor_plan` — issue #127."""

from __future__ import annotations

from io import BytesIO

import pytest

import vsdx
from vsdx.kit import (
    FIXTURE_KIND_DOOR,
    FIXTURE_KIND_WINDOW,
    FIXTURE_KINDS,
    FIXTURE_WALL_SIDES,
    FURNITURE_DEFAULT_SIZES,
    FURNITURE_KIND_BED,
    FURNITURE_KIND_BOOKSHELF,
    FURNITURE_KIND_CHAIR,
    FURNITURE_KIND_DESK,
    FURNITURE_KIND_SOFA,
    FURNITURE_KIND_TABLE,
    FURNITURE_KINDS,
    METERS_PER_FOOT,
    UNIT_FEET,
    UNIT_METERS,
    build_floor_plan,
)


# ---------------------------------------------------------------------------
# Canonical fixture — the roughly-realistic office floor plan from #127
# ---------------------------------------------------------------------------


_FIXTURE_ROOMS = [
    {"name": "Reception", "x": 0, "y": 0, "width": 4, "height": 3, "unit": "meters"},
    {"name": "Open office", "x": 4, "y": 0, "width": 12, "height": 8},
    {"name": "Meeting room A", "x": 16, "y": 0, "width": 4, "height": 3, "capacity": 6},
    {"name": "Kitchen", "x": 0, "y": 3, "width": 4, "height": 3},
    {"name": "Bathroom", "x": 0, "y": 6, "width": 2, "height": 2},
]
_FIXTURE_FURNITURE = [
    {"kind": "desk", "x": 5, "y": 1, "rotation": 0},
    {"kind": "desk", "x": 8, "y": 1, "rotation": 0},
    {"kind": "chair", "x": 5.5, "y": 1.7, "rotation": 0},
    {"kind": "sofa", "x": 1, "y": 0.5, "rotation": 0},
]
_FIXTURE_FIXTURES = [
    {"kind": "door", "x": 4, "y": 1.5, "wall": "left", "width": 1},
    {"kind": "window", "x": 8, "y": 0, "wall": "top", "width": 2},
]


def _build_fixture(**kwargs):
    return build_floor_plan(
        title=kwargs.pop("title", "Office floor plan — level 3"),
        rooms=kwargs.pop("rooms", _FIXTURE_ROOMS),
        furniture=kwargs.pop("furniture", _FIXTURE_FURNITURE),
        fixtures=kwargs.pop("fixtures", _FIXTURE_FIXTURES),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# DescribeBuildFloorPlan — happy-path acceptance
# ---------------------------------------------------------------------------


class DescribeBuildFloorPlan:
    def it_returns_a_VisioDocument(self):
        diagram = _build_fixture()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page_named_after_the_title(self):
        diagram = _build_fixture()
        assert len(diagram.pages) == 1
        assert diagram.pages[0].name == "Office floor plan — level 3"

    def it_defaults_the_page_name_to_Floor_plan_when_no_title(self):
        diagram = _build_fixture(title="")
        assert diagram.pages[0].name == "Floor plan"

    def it_emits_one_shape_per_room(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        room_names = {r["name"] for r in _FIXTURE_ROOMS}
        page_room_shapes = [s for s in page.shapes if s.text in room_names]
        assert len(page_room_shapes) == len(_FIXTURE_ROOMS)

    def it_emits_one_shape_per_furniture_item(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # Furniture shapes carry their kind as the on-shape text.
        labels = [s.text for s in page.shapes]
        # 2 desks + 1 chair + 1 sofa
        assert labels.count("desk") == 2
        assert labels.count("chair") == 1
        assert labels.count("sofa") == 1

    def it_emits_one_shape_per_fixture(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        labels = [s.text for s in page.shapes]
        assert labels.count("door") == 1
        assert labels.count("window") == 1

    def it_emits_a_title_band_when_title_is_provided(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        title_text = "Office floor plan — level 3"
        title_shapes = [s for s in page.shapes if s.text == title_text]
        assert len(title_shapes) == 1

    def it_skips_the_title_band_when_title_is_empty(self):
        diagram = _build_fixture(title="")
        page = diagram.pages[0]
        # No title shape means the title band is suppressed entirely.
        room_names = {r["name"] for r in _FIXTURE_ROOMS}
        for shape in page.shapes:
            if shape.text:
                assert shape.text in (
                    list(room_names) + list(FURNITURE_KINDS) + list(FIXTURE_KINDS)
                )

    def it_centres_each_room_on_its_geometry_centre(self):
        diagram = _build_fixture(title="")
        page = diagram.pages[0]
        # The "Open office" room — bottom-left (4, 0), 12x8. Its
        # centre-pin in plan units sits at (10, 4) plus the page
        # margin (1.0).
        room = next(s for s in page.shapes if s.text == "Open office")
        assert abs(float(room.pin_x) - (1.0 + 10.0)) < 1e-6
        assert abs(float(room.pin_y) - (1.0 + 4.0)) < 1e-6
        assert abs(float(room.width) - 12.0) < 1e-6
        assert abs(float(room.height) - 8.0) < 1e-6

    def it_converts_meters_to_feet_for_per_room_unit_overrides(self):
        diagram = _build_fixture(title="")
        page = diagram.pages[0]
        # Reception is declared in meters: 4m x 3m. Expect feet on the
        # rendered shape.
        room = next(s for s in page.shapes if s.text == "Reception")
        assert abs(float(room.width) - 4.0 * METERS_PER_FOOT) < 1e-6
        assert abs(float(room.height) - 3.0 * METERS_PER_FOOT) < 1e-6

    def it_renders_furniture_with_per_kind_default_sizes(self):
        diagram = build_floor_plan(
            title="",
            rooms=[{"name": "R", "x": 0, "y": 0, "width": 30, "height": 30}],
            furniture=[{"kind": "bed", "x": 0, "y": 0}],
        )
        page = diagram.pages[0]
        bed = next(s for s in page.shapes if s.text == "bed")
        default_w, default_h = FURNITURE_DEFAULT_SIZES["bed"]
        assert abs(float(bed.width) - default_w) < 1e-6
        assert abs(float(bed.height) - default_h) < 1e-6

    def it_honours_explicit_furniture_width_and_height(self):
        diagram = build_floor_plan(
            title="",
            rooms=[{"name": "R", "x": 0, "y": 0, "width": 20, "height": 20}],
            furniture=[
                {"kind": "table", "x": 1, "y": 1, "width": 7.5, "height": 4.25},
            ],
        )
        page = diagram.pages[0]
        table = next(s for s in page.shapes if s.text == "table")
        assert abs(float(table.width) - 7.5) < 1e-6
        assert abs(float(table.height) - 4.25) < 1e-6

    def it_records_a_capacity_value_on_the_room_shape_data(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        meeting = next(s for s in page.shapes if s.text == "Meeting room A")
        capacity_field = meeting.data.get_field("Capacity")
        assert capacity_field is not None
        assert capacity_field.value == "6"

    def it_skips_capacity_data_when_not_provided(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        kitchen = next(s for s in page.shapes if s.text == "Kitchen")
        # No Capacity field on a room that didn't ask for one.
        assert kitchen.data.get_field("Capacity") is None

    def it_tags_fixtures_with_kind_and_wall_shape_data(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        door = next(s for s in page.shapes if s.text == "door")
        kind = door.data.get_field("Kind")
        wall = door.data.get_field("Wall")
        assert kind is not None and kind.value == "door"
        assert wall is not None and wall.value == "left"

    def it_orients_horizontal_wall_fixtures_along_x(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # The window is on a "top" wall — horizontal opening.
        window = next(s for s in page.shapes if s.text == "window")
        assert float(window.width) > float(window.height)

    def it_orients_vertical_wall_fixtures_along_y(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # The door is on a "left" wall — vertical opening.
        door = next(s for s in page.shapes if s.text == "door")
        assert float(door.height) > float(door.width)

    def it_keeps_every_shape_inside_the_page_bounds(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        page_w = float(page.width)
        page_h = float(page.height)
        for shape in page.shapes:
            x = float(shape.pin_x)
            y = float(shape.pin_y)
            assert 0 <= x <= page_w
            assert 0 <= y <= page_h

    def it_round_trips_through_save_and_reload(self, tmp_path):
        diagram = _build_fixture()
        out = tmp_path / "floor.vsdx"
        diagram.save(str(out))
        reloaded = vsdx.Visio(str(out))
        assert len(reloaded.pages) == 1
        assert reloaded.pages[0].name == "Office floor plan — level 3"
        original_count = len(list(diagram.pages[0].shapes))
        reloaded_count = len(list(reloaded.pages[0].shapes))
        assert reloaded_count == original_count

    def it_round_trips_through_an_in_memory_buffer(self):
        diagram = _build_fixture()
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        assert len(reloaded.pages) == 1
        # The five room names survive the save/reload cycle.
        texts = {s.text for s in reloaded.pages[0].shapes}
        for room in _FIXTURE_ROOMS:
            assert room["name"] in texts

    def it_accepts_a_plan_wide_meters_unit(self):
        diagram = build_floor_plan(
            title="",
            rooms=[{"name": "R", "x": 0, "y": 0, "width": 5, "height": 4}],
            unit="meters",
        )
        page = diagram.pages[0]
        room = next(s for s in page.shapes if s.text == "R")
        assert abs(float(room.width) - 5.0 * METERS_PER_FOOT) < 1e-6
        assert abs(float(room.height) - 4.0 * METERS_PER_FOOT) < 1e-6

    def it_honours_explicit_page_dimensions(self):
        diagram = build_floor_plan(
            title="",
            rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 3}],
            page_width=42.0,
            page_height=30.0,
        )
        page = diagram.pages[0]
        assert abs(float(page.width) - 42.0) < 1e-6
        assert abs(float(page.height) - 30.0) < 1e-6


# ---------------------------------------------------------------------------
# DescribeValidation — guard rails on input data
# ---------------------------------------------------------------------------


class DescribeValidation:
    def it_rejects_an_empty_rooms_list(self):
        with pytest.raises(ValueError, match="rooms must contain at least one"):
            build_floor_plan(rooms=[])

    def it_rejects_a_room_missing_a_required_key(self):
        with pytest.raises(ValueError, match="missing a required"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4}],
            )

    def it_rejects_a_room_with_non_positive_width(self):
        with pytest.raises(ValueError, match="'width' must be > 0"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 0, "height": 3}],
            )

    def it_rejects_a_room_with_non_positive_height(self):
        with pytest.raises(ValueError, match="'height' must be > 0"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 3, "height": -1}],
            )

    def it_rejects_duplicate_room_names(self):
        with pytest.raises(ValueError, match="duplicated"):
            build_floor_plan(
                rooms=[
                    {"name": "R", "x": 0, "y": 0, "width": 4, "height": 3},
                    {"name": "R", "x": 0, "y": 4, "width": 4, "height": 3},
                ],
            )

    def it_rejects_a_furniture_item_with_an_unknown_kind(self):
        with pytest.raises(ValueError, match="'kind' must be one of"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                furniture=[{"kind": "ufo", "x": 1, "y": 1}],
            )

    def it_rejects_a_fixture_with_an_unknown_kind(self):
        with pytest.raises(ValueError, match="'kind' must be one of"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                fixtures=[{"kind": "skylight", "x": 1, "y": 0, "wall": "top", "width": 1}],
            )

    def it_rejects_a_fixture_with_an_unknown_wall(self):
        with pytest.raises(ValueError, match="'wall' must be one of"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                fixtures=[{"kind": "door", "x": 1, "y": 0, "wall": "diagonal", "width": 1}],
            )

    def it_rejects_a_fixture_with_non_positive_width(self):
        with pytest.raises(ValueError, match="'width' must be > 0"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                fixtures=[{"kind": "door", "x": 1, "y": 0, "wall": "top", "width": 0}],
            )

    def it_rejects_an_unknown_unit_token(self):
        with pytest.raises(ValueError, match="must be one of"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                unit="furlongs",
            )

    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError, match="title must be a str"):
            build_floor_plan(
                title=42,  # type: ignore[arg-type]
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
            )

    def it_rejects_a_non_numeric_room_coordinate(self):
        with pytest.raises(ValueError, match="must be a number"):
            build_floor_plan(
                rooms=[{"name": "R", "x": "zero", "y": 0, "width": 4, "height": 4}],
            )

    def it_rejects_a_negative_room_capacity(self):
        with pytest.raises(ValueError, match="'capacity' must be >= 0"):
            build_floor_plan(
                rooms=[
                    {
                        "name": "R",
                        "x": 0,
                        "y": 0,
                        "width": 4,
                        "height": 4,
                        "capacity": -1,
                    }
                ],
            )

    def it_rejects_a_non_integer_room_capacity(self):
        with pytest.raises(ValueError, match="'capacity' must be an int"):
            build_floor_plan(
                rooms=[
                    {
                        "name": "R",
                        "x": 0,
                        "y": 0,
                        "width": 4,
                        "height": 4,
                        "capacity": 6.5,
                    }
                ],
            )

    def it_rejects_a_non_mapping_room(self):
        with pytest.raises(ValueError, match="must be a Mapping"):
            build_floor_plan(rooms=["not a dict"])  # type: ignore[list-item]

    def it_rejects_a_non_mapping_furniture(self):
        with pytest.raises(ValueError, match="must be a Mapping"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                furniture=["bench"],  # type: ignore[list-item]
            )

    def it_rejects_a_non_mapping_fixture(self):
        with pytest.raises(ValueError, match="must be a Mapping"):
            build_floor_plan(
                rooms=[{"name": "R", "x": 0, "y": 0, "width": 4, "height": 4}],
                fixtures=["window"],  # type: ignore[list-item]
            )


# ---------------------------------------------------------------------------
# DescribeKitConstants — small, but cheap to verify
# ---------------------------------------------------------------------------


class DescribeKitConstants:
    def it_lists_every_recognised_furniture_kind(self):
        assert set(FURNITURE_KINDS) == {
            FURNITURE_KIND_DESK,
            FURNITURE_KIND_CHAIR,
            FURNITURE_KIND_SOFA,
            FURNITURE_KIND_BED,
            FURNITURE_KIND_TABLE,
            FURNITURE_KIND_BOOKSHELF,
        }

    def it_lists_every_recognised_fixture_kind(self):
        assert set(FIXTURE_KINDS) == {
            FIXTURE_KIND_DOOR,
            FIXTURE_KIND_WINDOW,
        }

    def it_provides_default_sizes_for_every_furniture_kind(self):
        for kind in FURNITURE_KINDS:
            assert kind in FURNITURE_DEFAULT_SIZES
            w, h = FURNITURE_DEFAULT_SIZES[kind]
            assert w > 0
            assert h > 0

    def it_lists_the_four_cardinal_wall_sides(self):
        assert set(FIXTURE_WALL_SIDES) == {"left", "right", "top", "bottom"}

    def it_re_exports_the_builder_from_the_kit_package(self):
        from vsdx.kit import build_floor_plan as via_pkg
        from vsdx.kit.floor_plan import build_floor_plan as via_module

        assert via_pkg is via_module

    def it_exposes_the_unit_tokens(self):
        assert UNIT_FEET == "feet"
        assert UNIT_METERS == "meters"
