# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.process` — issue #128."""

from __future__ import annotations

from io import BytesIO

import pytest

import vsdx
from vsdx.kit import (
    PROCESS_KIND_DECISION,
    PROCESS_KIND_END,
    PROCESS_KIND_START,
    PROCESS_KIND_TASK,
    PROCESS_STEP_KINDS,
    SIPOC_COLUMN_ORDER,
    build_process_map,
    build_sipoc,
)
from vsdx.shapes.connector import Connector


# ---------------------------------------------------------------------------
# SIPOC fixture + helpers
# ---------------------------------------------------------------------------


_SIPOC_KWARGS = dict(
    title="Order fulfilment",
    suppliers=["Supplier A", "Supplier B"],
    inputs=["Raw materials", "Labour"],
    process_steps=["Receive order", "Manufacture", "Ship"],
    outputs=["Finished product"],
    customers=["Retail", "Wholesale"],
)


def _build_sipoc():
    return build_sipoc(**_SIPOC_KWARGS)


# ---------------------------------------------------------------------------
# DescribeBuildSipoc — table layout + content
# ---------------------------------------------------------------------------


class DescribeBuildSipoc:
    def it_returns_a_VisioDocument(self):
        diagram = _build_sipoc()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page_named_after_the_title(self):
        diagram = _build_sipoc()
        assert len(diagram.pages) == 1
        assert diagram.pages[0].name == "Order fulfilment"

    def it_falls_back_to_SIPOC_for_an_empty_title(self):
        diagram = build_sipoc(
            title="",
            suppliers=["s"],
            inputs=["i"],
            process_steps=["p"],
            outputs=["o"],
            customers=["c"],
        )
        assert diagram.pages[0].name == "SIPOC"

    def it_honours_an_explicit_page_name(self):
        diagram = build_sipoc(
            title="t",
            suppliers=["s"],
            inputs=["i"],
            process_steps=["p"],
            outputs=["o"],
            customers=["c"],
            page_name="Override",
        )
        assert diagram.pages[0].name == "Override"

    def it_emits_the_expected_total_shape_count(self):
        # 1 title + 5 headers + cells (2+2+3+1+2 = 10) = 16
        diagram = _build_sipoc()
        shapes = list(diagram.pages[0].shapes)
        assert len(shapes) == 1 + 5 + (2 + 2 + 3 + 1 + 2)

    def it_emits_the_five_canonical_column_headers_in_order(self):
        diagram = _build_sipoc()
        page = diagram.pages[0]
        # Headers are the 5 rectangles whose text is one of the canonical
        # column names. They sit on the same y (header band centre).
        header_shapes = [s for s in page.shapes if s.text in SIPOC_COLUMN_ORDER]
        assert len(header_shapes) == len(SIPOC_COLUMN_ORDER)
        # Sorted left-to-right by pin_x, the texts match the canonical
        # order.
        ordered = sorted(header_shapes, key=lambda s: float(s.pin_x))
        assert [s.text for s in ordered] == list(SIPOC_COLUMN_ORDER)

    def it_lays_out_columns_with_equal_widths(self):
        diagram = _build_sipoc()
        page = diagram.pages[0]
        widths = [
            float(s.width)
            for s in page.shapes
            if s.text in SIPOC_COLUMN_ORDER
        ]
        assert max(widths) - min(widths) < 1e-6

    def it_renders_each_column_value_as_a_rectangle_under_its_header(self):
        diagram = _build_sipoc()
        page = diagram.pages[0]
        # Map header pin_x -> column name.
        header_x_by_name = {
            s.text: float(s.pin_x)
            for s in page.shapes
            if s.text in SIPOC_COLUMN_ORDER
        }
        # Each value should appear as a rectangle aligned with its
        # column's pin_x.
        column_values = {
            "Suppliers": _SIPOC_KWARGS["suppliers"],
            "Inputs": _SIPOC_KWARGS["inputs"],
            "Process": _SIPOC_KWARGS["process_steps"],
            "Outputs": _SIPOC_KWARGS["outputs"],
            "Customers": _SIPOC_KWARGS["customers"],
        }
        all_texts = {s.text: s for s in page.shapes}
        for col_name, values in column_values.items():
            expected_x = header_x_by_name[col_name]
            for v in values:
                assert v in all_texts, f"missing cell {v!r}"
                shape = all_texts[v]
                assert shape.master_name_u == "Rectangle"
                assert abs(float(shape.pin_x) - expected_x) < 1e-6

    def it_stacks_cells_top_to_bottom_in_declaration_order(self):
        diagram = _build_sipoc()
        page = diagram.pages[0]
        all_texts = {s.text: s for s in page.shapes}
        # Process column has three entries — verify they descend.
        receive = all_texts["Receive order"]
        manufacture = all_texts["Manufacture"]
        ship = all_texts["Ship"]
        assert float(receive.pin_y) > float(manufacture.pin_y)
        assert float(manufacture.pin_y) > float(ship.pin_y)

    def it_round_trips_through_save_and_reload(self, tmp_path):
        diagram = _build_sipoc()
        out = tmp_path / "sipoc.vsdx"
        diagram.save(str(out))
        reloaded = vsdx.Visio(str(out))
        assert len(reloaded.pages) == 1
        assert reloaded.pages[0].name == "Order fulfilment"
        original = len(list(diagram.pages[0].shapes))
        assert len(list(reloaded.pages[0].shapes)) == original

    def it_round_trips_through_an_in_memory_buffer(self):
        diagram = _build_sipoc()
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        texts = {s.text for s in reloaded.pages[0].shapes}
        # Every column value should survive the round trip.
        for v in _SIPOC_KWARGS["suppliers"]:
            assert v in texts
        for v in _SIPOC_KWARGS["customers"]:
            assert v in texts
        assert "Order fulfilment" in texts


# ---------------------------------------------------------------------------
# DescribeBuildSipocValidation
# ---------------------------------------------------------------------------


class DescribeBuildSipocValidation:
    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError, match="title must be a str"):
            build_sipoc(
                title=42,  # type: ignore[arg-type]
                suppliers=["s"],
                inputs=["i"],
                process_steps=["p"],
                outputs=["o"],
                customers=["c"],
            )

    def it_rejects_a_non_string_column_entry(self):
        with pytest.raises(ValueError, match="must be a non-empty str"):
            build_sipoc(
                title="t",
                suppliers=["", "x"],
                inputs=["i"],
                process_steps=["p"],
                outputs=["o"],
                customers=["c"],
            )

    def it_rejects_a_None_column(self):
        with pytest.raises(TypeError, match="must be a sequence"):
            build_sipoc(
                title="t",
                suppliers=None,  # type: ignore[arg-type]
                inputs=["i"],
                process_steps=["p"],
                outputs=["o"],
                customers=["c"],
            )

    def it_rejects_a_page_too_small_for_the_bands(self):
        with pytest.raises(ValueError, match="too small for the title"):
            build_sipoc(
                title="t",
                suppliers=["s"],
                inputs=["i"],
                process_steps=["p"],
                outputs=["o"],
                customers=["c"],
                page_height=1.0,
            )

    def it_accepts_an_empty_column(self):
        # A SIPOC column with no entries is rare but legal — the column
        # still gets a header, just no body cells.
        diagram = build_sipoc(
            title="t",
            suppliers=[],
            inputs=["i"],
            process_steps=["p"],
            outputs=["o"],
            customers=["c"],
        )
        # Headers still emitted; no cells under "Suppliers".
        assert isinstance(diagram, vsdx.VisioDocument)


# ---------------------------------------------------------------------------
# Process-map fixture + DescribeBuildProcessMap
# ---------------------------------------------------------------------------


_PMAP_STEPS = [
    {"kind": "start", "text": "Application"},
    {"kind": "task", "text": "Background check"},
    {"kind": "decision", "text": "Approved?"},
    {"kind": "task", "text": "Provision accounts", "on": "yes"},
    {"kind": "end", "text": "Reject", "on": "no"},
    {"kind": "end", "text": "Onboarded"},
]


def _build_pmap():
    return build_process_map(title="Onboarding", steps=_PMAP_STEPS)


class DescribeBuildProcessMap:
    def it_returns_a_VisioDocument(self):
        diagram = _build_pmap()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page_named_after_the_title(self):
        diagram = _build_pmap()
        assert len(diagram.pages) == 1
        assert diagram.pages[0].name == "Onboarding"

    def it_falls_back_to_default_for_an_empty_title(self):
        diagram = build_process_map(
            title="",
            steps=[{"kind": "start", "text": "x"}],
        )
        assert diagram.pages[0].name == "Process map"

    def it_emits_a_title_band_and_one_shape_per_step(self):
        # 1 title + 6 step shapes + (6-1) auto-wired connectors = 12
        diagram = _build_pmap()
        shapes = list(diagram.pages[0].shapes)
        assert len(shapes) == 1 + len(_PMAP_STEPS) + (len(_PMAP_STEPS) - 1)

    def it_renders_start_and_end_steps_as_ellipses(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        application = next(s for s in page.shapes if s.text == "Application")
        reject = next(s for s in page.shapes if s.text == "Reject")
        onboarded = next(s for s in page.shapes if s.text == "Onboarded")
        assert application.master_name_u == "Ellipse"
        assert reject.master_name_u == "Ellipse"
        assert onboarded.master_name_u == "Ellipse"

    def it_renders_task_steps_as_rectangles(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        bg = next(s for s in page.shapes if s.text == "Background check")
        provision = next(s for s in page.shapes if s.text == "Provision accounts")
        assert bg.master_name_u == "Rectangle"
        assert provision.master_name_u == "Rectangle"

    def it_renders_a_decision_step_as_a_diamond_path(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        decision = next(s for s in page.shapes if s.text == "Approved?")
        # Diamond geometry: MoveTo + 3 LineTo + 1 closing LineTo = 5 rows.
        from vsdx.geometry import LineTo, MoveTo

        geometry = decision.geometry
        assert geometry is not None
        rows = list(geometry.rows)
        assert len(rows) == 5
        assert isinstance(rows[0], MoveTo)
        for r in rows[1:]:
            assert isinstance(r, LineTo)

    def it_stacks_steps_top_to_bottom_in_declaration_order(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        ys = []
        for step in _PMAP_STEPS:
            shape = next(s for s in page.shapes if s.text == step["text"])
            ys.append(float(shape.pin_y))
        # Strictly descending — each step sits below the previous.
        for prev, curr in zip(ys, ys[1:]):
            assert prev > curr

    def it_aligns_every_step_on_a_shared_centre_x(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        xs = []
        for step in _PMAP_STEPS:
            shape = next(s for s in page.shapes if s.text == step["text"])
            xs.append(float(shape.pin_x))
        assert max(xs) - min(xs) < 1e-6

    def it_auto_wires_consecutive_steps_when_flows_is_omitted(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        connectors = [s for s in page.shapes if isinstance(s, Connector)]
        # n-1 connectors for n steps under the auto-wire default.
        assert len(connectors) == len(_PMAP_STEPS) - 1

    def it_honours_an_explicit_flows_argument(self):
        # Override default sequential wiring with a custom edge set.
        diagram = build_process_map(
            title="Custom",
            steps=[
                {"kind": "start", "text": "a"},
                {"kind": "task", "text": "b"},
                {"kind": "end", "text": "c"},
            ],
            flows=[("a", "c")],  # skip b
        )
        page = diagram.pages[0]
        connectors = [s for s in page.shapes if isinstance(s, Connector)]
        assert len(connectors) == 1

    def it_keeps_step_geometry_inside_the_page(self):
        diagram = _build_pmap()
        page = diagram.pages[0]
        page_w = float(page.width)
        page_h = float(page.height)
        for shape in page.shapes:
            if isinstance(shape, Connector):
                continue
            x = float(shape.pin_x)
            y = float(shape.pin_y)
            assert 0 <= x <= page_w
            assert 0 <= y <= page_h

    def it_round_trips_through_save_and_reload(self, tmp_path):
        diagram = _build_pmap()
        out = tmp_path / "process.vsdx"
        diagram.save(str(out))
        reloaded = vsdx.Visio(str(out))
        assert len(reloaded.pages) == 1
        assert reloaded.pages[0].name == "Onboarding"

    def it_round_trips_through_an_in_memory_buffer(self):
        diagram = _build_pmap()
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        texts = {s.text for s in reloaded.pages[0].shapes}
        for step in _PMAP_STEPS:
            assert step["text"] in texts


# ---------------------------------------------------------------------------
# DescribeBuildProcessMapFlowGlue — verify connector glue targets
# ---------------------------------------------------------------------------


class DescribeBuildProcessMapFlowGlue:
    def it_glues_consecutive_steps_in_the_default_wiring(self):
        diagram = build_process_map(
            title="g",
            steps=[
                {"kind": "start", "text": "A"},
                {"kind": "task", "text": "B"},
                {"kind": "end", "text": "C"},
            ],
        )
        page = diagram.pages[0]
        connects_el = page.shapes._element.connects_element  # noqa: SLF001
        text_by_id = {
            int(s.shape_id): s.text
            for s in page.shapes
            if not isinstance(s, Connector) and s.text
        }
        from_pair: dict = {}
        for connect_el in connects_el.connect_lst:
            from_sheet = int(connect_el.get("FromSheet") or 0)
            to_sheet = int(connect_el.get("ToSheet") or 0)
            from_cell = connect_el.get("FromCell") or ""
            target_text = text_by_id.get(to_sheet)
            from_pair.setdefault(from_sheet, {})[from_cell] = target_text
        seen_pairs = []
        for cells in from_pair.values():
            begin = cells.get("BeginX")
            end = cells.get("EndX")
            if begin and end:
                seen_pairs.append((begin, end))
        # Default wiring: A->B and B->C.
        assert ("A", "B") in seen_pairs
        assert ("B", "C") in seen_pairs


# ---------------------------------------------------------------------------
# DescribeBuildProcessMapValidation
# ---------------------------------------------------------------------------


class DescribeBuildProcessMapValidation:
    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError, match="title must be a str"):
            build_process_map(
                title=1,  # type: ignore[arg-type]
                steps=[{"kind": "start", "text": "x"}],
            )

    def it_rejects_an_empty_steps_list(self):
        with pytest.raises(ValueError, match="at least one step"):
            build_process_map(title="t", steps=[])

    def it_rejects_a_step_missing_kind(self):
        with pytest.raises(ValueError, match="missing a required 'kind'"):
            build_process_map(title="t", steps=[{"text": "x"}])

    def it_rejects_a_step_missing_text(self):
        with pytest.raises(ValueError, match="missing a required 'text'"):
            build_process_map(title="t", steps=[{"kind": "start"}])

    def it_rejects_an_unrecognised_kind(self):
        with pytest.raises(ValueError, match="must be one of"):
            build_process_map(
                title="t", steps=[{"kind": "ufo", "text": "x"}]
            )

    def it_rejects_duplicate_step_text(self):
        with pytest.raises(ValueError, match="duplicated"):
            build_process_map(
                title="t",
                steps=[
                    {"kind": "start", "text": "x"},
                    {"kind": "end", "text": "x"},
                ],
            )

    def it_rejects_a_flow_with_an_unknown_endpoint(self):
        with pytest.raises(ValueError, match="unknown step"):
            build_process_map(
                title="t",
                steps=[
                    {"kind": "start", "text": "a"},
                    {"kind": "end", "text": "b"},
                ],
                flows=[("a", "missing")],
            )

    def it_rejects_a_non_string_on_label(self):
        with pytest.raises(ValueError, match="'on' must be a non-empty str"):
            build_process_map(
                title="t",
                steps=[{"kind": "start", "text": "x", "on": ""}],
            )

    def it_rejects_a_page_too_small_for_the_title(self):
        with pytest.raises(ValueError, match="too small for the title"):
            build_process_map(
                title="t",
                steps=[{"kind": "start", "text": "x"}],
                page_height=0.5,
            )


# ---------------------------------------------------------------------------
# DescribeKitConstants
# ---------------------------------------------------------------------------


class DescribeKitConstants:
    def it_lists_every_recognised_process_step_kind(self):
        assert set(PROCESS_STEP_KINDS) == {
            PROCESS_KIND_START,
            PROCESS_KIND_TASK,
            PROCESS_KIND_DECISION,
            PROCESS_KIND_END,
        }

    def it_lists_the_canonical_sipoc_column_order(self):
        assert SIPOC_COLUMN_ORDER == (
            "Suppliers",
            "Inputs",
            "Process",
            "Outputs",
            "Customers",
        )

    def it_re_exports_the_builders_from_the_kit_package(self):
        from vsdx.kit import build_process_map as via_pkg_pm
        from vsdx.kit import build_sipoc as via_pkg_sipoc
        from vsdx.kit.process import build_process_map as via_module_pm
        from vsdx.kit.process import build_sipoc as via_module_sipoc

        assert via_pkg_pm is via_module_pm
        assert via_pkg_sipoc is via_module_sipoc
