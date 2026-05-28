# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.swim_lanes` — issue #121."""

from __future__ import annotations

from io import BytesIO

import pytest

import vsdx
from vsdx.kit import (
    SWIM_LANE_KIND_DECISION,
    SWIM_LANE_KIND_END,
    SWIM_LANE_KIND_START,
    SWIM_LANE_STEP_KINDS,
    build_swim_lane_diagram,
)
from vsdx.shapes.connector import Connector


# ---------------------------------------------------------------------------
# A small canonical fixture used by most tests
# ---------------------------------------------------------------------------


_FIXTURE_LANES = ["Customer", "Sales", "Warehouse"]
_FIXTURE_STEPS = [
    {"lane": "Customer", "text": "Place order", "kind": "start"},
    {"lane": "Sales", "text": "Validate order"},
    {"lane": "Sales", "text": "Approve?", "kind": "decision"},
    {"lane": "Warehouse", "text": "Pick + pack"},
    {"lane": "Customer", "text": "Receive shipment", "kind": "end"},
]
_FIXTURE_FLOWS = [
    ("Place order", "Validate order"),
    ("Validate order", "Approve?"),
    ("Approve?", "Pick + pack"),
    ("Pick + pack", "Receive shipment"),
]


def _build_fixture():
    return build_swim_lane_diagram(
        title="Order processing",
        lanes=_FIXTURE_LANES,
        steps=_FIXTURE_STEPS,
        flows=_FIXTURE_FLOWS,
    )


# ---------------------------------------------------------------------------
# DescribeBuildSwimLaneDiagram
# ---------------------------------------------------------------------------


class DescribeBuildSwimLaneDiagram:
    def it_returns_a_VisioDocument(self):
        diagram = _build_fixture()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page_with_the_title_as_the_page_name(self):
        diagram = _build_fixture()
        assert len(diagram.pages) == 1
        assert diagram.pages[0].name == "Order processing"

    def it_emits_the_expected_total_shape_count(self):
        # 1 title + (3 header + 3 body) outlines + 5 steps + 4 connectors
        # = 16 shapes top-level.
        diagram = _build_fixture()
        shapes = list(diagram.pages[0].shapes)
        assert len(shapes) == 1 + (2 * 3) + 5 + 4

    def it_lays_lanes_out_with_equal_widths(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # Header rectangles are emitted in lane-order — pick them out
        # by their text label.
        header_widths = []
        for shape in page.shapes:
            if shape.text in _FIXTURE_LANES:
                header_widths.append(float(shape.width))
        assert len(header_widths) == len(_FIXTURE_LANES)
        # Equal widths within float tolerance.
        assert max(header_widths) - min(header_widths) < 1e-6

    def it_stacks_steps_top_to_bottom_inside_their_lane(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # Find the two steps in the Sales lane.
        sales_steps = [
            s for s in page.shapes if s.text in ("Validate order", "Approve?")
        ]
        # Same lane => same pin_x.
        assert abs(float(sales_steps[0].pin_x) - float(sales_steps[1].pin_x)) < 1e-6
        # First-declared step sits above the second (higher pin_y).
        validate = next(s for s in sales_steps if s.text == "Validate order")
        approve = next(s for s in sales_steps if s.text == "Approve?")
        assert float(validate.pin_y) > float(approve.pin_y)

    def it_aligns_each_step_with_its_lane_centre(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # Map lane_name -> header pin_x.
        lane_x_by_name = {
            s.text: float(s.pin_x) for s in page.shapes if s.text in _FIXTURE_LANES
        }
        # Map step.text -> declared lane.
        lane_by_step = {st["text"]: st["lane"] for st in _FIXTURE_STEPS}
        for shape in page.shapes:
            text = shape.text
            if text not in lane_by_step:
                continue
            expected_lane_x = lane_x_by_name[lane_by_step[text]]
            assert abs(float(shape.pin_x) - expected_lane_x) < 1e-6

    def it_renders_start_and_end_steps_as_ellipses(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        start_shape = next(s for s in page.shapes if s.text == "Place order")
        end_shape = next(s for s in page.shapes if s.text == "Receive shipment")
        assert start_shape.master_name_u == "Ellipse"
        assert end_shape.master_name_u == "Ellipse"

    def it_renders_a_decision_step_as_a_diamond_path(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        decision = next(s for s in page.shapes if s.text == "Approve?")
        # Diamond geometry: MoveTo + 3 LineTo + 1 closing LineTo = 5 rows.
        geometry = decision.geometry
        assert geometry is not None
        rows = list(geometry.rows)
        assert len(rows) == 5
        # First row is a MoveTo to (0.5, 1.0); the remaining four are
        # LineTos closing the diamond.
        from vsdx.geometry import LineTo, MoveTo

        assert isinstance(rows[0], MoveTo)
        for r in rows[1:]:
            assert isinstance(r, LineTo)

    def it_renders_default_steps_as_rectangles(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        validate = next(s for s in page.shapes if s.text == "Validate order")
        assert validate.master_name_u == "Rectangle"

    def it_emits_one_connector_per_flow_tuple(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        connectors = [s for s in page.shapes if isinstance(s, Connector)]
        assert len(connectors) == len(_FIXTURE_FLOWS)

    def it_round_trips_the_document_through_save_and_reload(self, tmp_path):
        diagram = _build_fixture()
        out = tmp_path / "swim.vsdx"
        diagram.save(str(out))

        reloaded = vsdx.Visio(str(out))
        assert len(reloaded.pages) == 1
        assert reloaded.pages[0].name == "Order processing"
        # Same shape count survives the round trip.
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
        # Round-tripped texts include all five step labels.
        texts = {s.text for s in reloaded.pages[0].shapes}
        for st in _FIXTURE_STEPS:
            assert st["text"] in texts

    def it_keeps_step_geometry_inside_the_page(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        page_w = float(page.width)
        page_h = float(page.height)
        for shape in page.shapes:
            if isinstance(shape, Connector):
                # Connectors don't carry pin_x/pin_y in the same way.
                continue
            x = float(shape.pin_x)
            y = float(shape.pin_y)
            assert 0 <= x <= page_w
            assert 0 <= y <= page_h


# ---------------------------------------------------------------------------
# DescribeFlowConnectors — connector wiring details
# ---------------------------------------------------------------------------


class DescribeFlowConnectors:
    def it_glues_each_flow_to_the_named_steps(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # Walk the <Connects> element directly to verify glue targets.
        # Each flow becomes two <Connect> entries (BeginX + EndX).
        connects_el = page.shapes._element.connects_element  # noqa: SLF001
        # Map shape id -> step text for assertion.
        text_by_id = {
            int(s.shape_id): s.text
            for s in page.shapes
            if not isinstance(s, Connector) and s.text
        }
        # Collect (begin-text, end-text) pairs from the <Connect> entries.
        seen_pairs = []
        # connect_lst yields raw <Connect> elements.
        from_pair: dict = {}
        for connect_el in connects_el.connect_lst:
            from_sheet = int(connect_el.get("FromSheet") or 0)
            to_sheet = int(connect_el.get("ToSheet") or 0)
            from_cell = connect_el.get("FromCell") or ""
            target_text = text_by_id.get(to_sheet)
            from_pair.setdefault(from_sheet, {})[from_cell] = target_text
        for cells in from_pair.values():
            begin = cells.get("BeginX")
            end = cells.get("EndX")
            if begin and end:
                seen_pairs.append((begin, end))
        # Every declared flow should appear in the seen pairs.
        for from_text, to_text in _FIXTURE_FLOWS:
            assert (from_text, to_text) in seen_pairs


# ---------------------------------------------------------------------------
# DescribeValidation — argument validation
# ---------------------------------------------------------------------------


class DescribeValidation:
    def it_rejects_an_empty_lanes_list(self):
        with pytest.raises(ValueError, match="lanes must contain at least one"):
            build_swim_lane_diagram(
                title="x",
                lanes=[],
                steps=[{"lane": "A", "text": "t"}],
            )

    def it_rejects_duplicate_lane_names(self):
        with pytest.raises(ValueError, match="lanes must be unique"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A", "A"],
                steps=[{"lane": "A", "text": "t"}],
            )

    def it_rejects_an_empty_steps_list(self):
        with pytest.raises(ValueError, match="steps must contain at least one"):
            build_swim_lane_diagram(title="x", lanes=["A"], steps=[])

    def it_rejects_a_step_referencing_an_unknown_lane(self):
        with pytest.raises(ValueError, match="not in lanes"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[{"lane": "B", "text": "t"}],
            )

    def it_rejects_steps_with_duplicate_text(self):
        with pytest.raises(ValueError, match="duplicated"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[
                    {"lane": "A", "text": "t"},
                    {"lane": "A", "text": "t"},
                ],
            )

    def it_rejects_a_flow_with_an_unknown_endpoint(self):
        with pytest.raises(ValueError, match="unknown step"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[{"lane": "A", "text": "t"}],
                flows=[("t", "missing")],
            )

    def it_rejects_a_step_with_an_invalid_kind(self):
        with pytest.raises(ValueError, match="must be one of"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[{"lane": "A", "text": "t", "kind": "ufo"}],
            )

    def it_rejects_a_step_missing_text(self):
        with pytest.raises(ValueError, match="missing a required 'text'"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[{"lane": "A"}],
            )

    def it_rejects_a_step_missing_lane(self):
        with pytest.raises(ValueError, match="missing a required 'lane'"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[{"text": "t"}],
            )

    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError, match="title must be a str"):
            build_swim_lane_diagram(
                title=42,  # type: ignore[arg-type]
                lanes=["A"],
                steps=[{"lane": "A", "text": "t"}],
            )

    def it_rejects_a_page_too_small_for_the_bands(self):
        with pytest.raises(ValueError, match="too small for the title"):
            build_swim_lane_diagram(
                title="x",
                lanes=["A"],
                steps=[{"lane": "A", "text": "t"}],
                page_width=4.0,
                page_height=1.5,  # smaller than title + header bands + margin
            )


# ---------------------------------------------------------------------------
# DescribeKitConstants — small, but cheap to verify
# ---------------------------------------------------------------------------


class DescribeKitConstants:
    def it_lists_every_recognised_step_kind(self):
        assert set(SWIM_LANE_STEP_KINDS) == {
            SWIM_LANE_KIND_START,
            SWIM_LANE_KIND_END,
            SWIM_LANE_KIND_DECISION,
            "step",
        }

    def it_re_exports_the_builder_from_the_kit_package(self):
        # Importing from the public namespace works the same as the
        # submodule path.
        from vsdx.kit import build_swim_lane_diagram as via_pkg
        from vsdx.kit.swim_lanes import build_swim_lane_diagram as via_module

        assert via_pkg is via_module
