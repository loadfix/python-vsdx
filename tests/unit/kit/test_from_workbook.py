# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.from_workbook` — issue #136."""

from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable

import pytest

import vsdx
from vsdx.kit.from_workbook import (
    DIAGRAM_KINDS,
    KIND_ERD,
    KIND_ORG_CHART,
    KIND_PROCESS_MAP,
    KIND_SWIM_LANE,
    diagram_from_xlsx,
)
from vsdx.shapes.connector import Connector

# Skip the whole module unless the sibling xlsx package is installed.
xlsx = pytest.importorskip("xlsx")
from xlsx import Workbook  # noqa: E402  — guarded by importorskip above


# ---------------------------------------------------------------------------
# Workbook fixture helpers — every test starts from a freshly-built
# in-memory xlsx so we never depend on a pre-baked binary fixture.
# ---------------------------------------------------------------------------


def _wb_to_bytes(wb: Workbook) -> BytesIO:
    """Serialise *wb* to a seek-rewound BytesIO for diagram_from_xlsx()."""
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _build_org_chart_workbook(
    *,
    sheet_title: str = "employees",
    headers: Iterable[str] = ("Name", "Title", "Manager", "Photo", "Team"),
    rows: Iterable[Iterable[Any]] = (
        ("CEO", "Chief Exec", None, "/photos/ceo.png", "Exec"),
        ("CTO", "Chief Tech", "CEO", "/photos/cto.png", "Exec"),
        ("CFO", "Chief Fin", "CEO", None, "Finance"),
        ("VPE", "VP Engineering", "CTO", None, "Engineering"),
    ),
) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    return _wb_to_bytes(wb)


def _build_erd_workbook(
    *,
    sheet_title: str = "columns",
    headers: Iterable[str] = ("Table", "Column", "Type", "Constraint"),
    rows: Iterable[Iterable[Any]] = (
        ("users", "id", "int", "PK"),
        ("users", "email", "varchar", "UNIQUE"),
        ("orders", "id", "int", "PK"),
        ("orders", "user_id", "int", "FK->users.id"),
    ),
) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    return _wb_to_bytes(wb)


def _build_process_workbook(
    *,
    steps_title: str = "Steps",
    flows_title: str = "Flows",
    step_headers: Iterable[str] = ("Text", "Kind", "On"),
    step_rows: Iterable[Iterable[Any]] = (
        ("Begin", "start", None),
        ("Validate", "task", None),
        ("Decide", "decision", None),
        ("Approve", "task", "yes"),
        ("Reject", "task", "no"),
        ("Done", "end", None),
    ),
    flow_rows: Iterable[Iterable[Any]] = (
        ("Begin", "Validate"),
        ("Validate", "Decide"),
        ("Decide", "Approve"),
        ("Approve", "Done"),
    ),
) -> BytesIO:
    wb = Workbook()
    steps = wb.active
    steps.title = steps_title
    steps.append(list(step_headers))
    for r in step_rows:
        steps.append(list(r))
    if flow_rows is not None:
        flows = wb.create_sheet(flows_title)
        flows.append(["From", "To"])
        for r in flow_rows:
            flows.append(list(r))
    return _wb_to_bytes(wb)


def _build_swim_lane_workbook(
    *,
    steps_title: str = "Steps",
    flows_title: str = "Flows",
    lanes_title: str = "Lanes",
    step_headers: Iterable[str] = ("Text", "Kind", "Lane"),
    step_rows: Iterable[Iterable[Any]] = (
        ("Order", "start", "Customer"),
        ("Validate", "step", "Sales"),
        ("Pick + Pack", "step", "Warehouse"),
        ("Receive", "end", "Customer"),
    ),
    flow_rows: Iterable[Iterable[Any]] = (
        ("Order", "Validate"),
        ("Validate", "Pick + Pack"),
        ("Pick + Pack", "Receive"),
    ),
    include_lanes_sheet: bool = False,
) -> BytesIO:
    wb = Workbook()
    steps = wb.active
    steps.title = steps_title
    steps.append(list(step_headers))
    for r in step_rows:
        steps.append(list(r))
    if include_lanes_sheet:
        lanes = wb.create_sheet(lanes_title)
        lanes.append(["Lane"])
        for name in ("Customer", "Sales", "Warehouse", "Finance"):
            lanes.append([name])
    if flow_rows is not None:
        flows = wb.create_sheet(flows_title)
        flows.append(["From", "To"])
        for r in flow_rows:
            flows.append(list(r))
    return _wb_to_bytes(wb)


def _shape_labels(diagram: vsdx.VisioDocument) -> set[str]:
    """Return the set of labels rendered on non-connector shapes."""
    return {
        s.text
        for page in diagram.pages
        for s in page.shapes
        if not isinstance(s, Connector) and s.text
    }


def _connector_count(diagram: vsdx.VisioDocument) -> int:
    return sum(
        1
        for page in diagram.pages
        for s in page.shapes
        if isinstance(s, Connector)
    )


# ---------------------------------------------------------------------------
# DescribeDispatcher — the kind selector
# ---------------------------------------------------------------------------


class DescribeDispatcher:
    def it_exposes_the_four_kind_tokens(self):
        assert KIND_ORG_CHART == "org-chart"
        assert KIND_ERD == "erd"
        assert KIND_PROCESS_MAP == "process-map"
        assert KIND_SWIM_LANE == "swim-lane"
        assert set(DIAGRAM_KINDS) == {
            "org-chart",
            "erd",
            "process-map",
            "swim-lane",
        }

    def it_rejects_an_unknown_kind(self):
        wb = _build_org_chart_workbook()
        with pytest.raises(ValueError, match="must be one of"):
            diagram_from_xlsx(wb, sheet="employees", kind="not-a-real-kind")

    def it_rejects_a_non_string_kind(self):
        wb = _build_org_chart_workbook()
        with pytest.raises(TypeError, match="kind must be a str"):
            diagram_from_xlsx(wb, sheet="employees", kind=42)  # type: ignore[arg-type]

    def it_rejects_an_unknown_builder_kwarg(self):
        wb = _build_org_chart_workbook()
        with pytest.raises(TypeError, match="does not accept keyword"):
            diagram_from_xlsx(
                wb,
                sheet="employees",
                kind="org-chart",
                not_a_kwarg="boom",
            )

    def it_rejects_a_missing_sheet(self):
        wb = _build_org_chart_workbook()
        with pytest.raises(ValueError, match="no sheet named"):
            diagram_from_xlsx(wb, sheet="not-there", kind="org-chart")


# ---------------------------------------------------------------------------
# DescribeOrgChartDispatch — kind="org-chart"
# ---------------------------------------------------------------------------


class DescribeOrgChartDispatch:
    def it_returns_a_VisioDocument(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_emits_one_box_per_employee(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        labels = _shape_labels(diagram)
        # Four employees, two-line "name\ntitle" labels.
        assert "CEO\nChief Exec" in labels
        assert "CTO\nChief Tech" in labels
        assert "CFO\nChief Fin" in labels
        assert "VPE\nVP Engineering" in labels

    def it_emits_one_connector_per_manager_link(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        # CTO->CEO, CFO->CEO, VPE->CTO.
        assert _connector_count(diagram) == 3

    def it_treats_blank_manager_cells_as_a_root(self):
        wb = _build_org_chart_workbook(
            rows=(
                ("Solo", "Founder", "", None, None),
                ("Helper", "Sidekick", "Solo", None, None),
            ),
        )
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        # Only Helper -> Solo edge; Solo's blank manager is a root marker.
        assert _connector_count(diagram) == 1

    def it_propagates_photo_and_team_to_shape_data(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        ceo = next(
            s
            for page in diagram.pages
            for s in page.shapes
            if not isinstance(s, Connector) and s.text.startswith("CEO")
        )
        assert ceo.data["Photo"] == "/photos/ceo.png"
        assert ceo.data["Team"] == "Exec"

    def it_honours_custom_column_names(self):
        wb = _build_org_chart_workbook(
            headers=("Employee", "Role", "ReportsTo", "Pic", "Dept"),
            rows=(
                ("CEO", "Chief Exec", None, None, None),
                ("CTO", "Chief Tech", "CEO", None, None),
            ),
        )
        diagram = diagram_from_xlsx(
            wb,
            sheet="employees",
            kind="org-chart",
            name_col="Employee",
            title_col="Role",
            manager_col="ReportsTo",
            photo_col="Pic",
            team_col="Dept",
        )
        labels = _shape_labels(diagram)
        assert "CEO\nChief Exec" in labels
        assert "CTO\nChief Tech" in labels

    def it_skips_optional_default_columns_absent_from_header(self):
        # Two-column sheet (just Name + Manager) — Title/Photo/Team
        # default-named columns aren't in the header, but because the
        # caller didn't explicitly name them they're treated as absent.
        wb = _build_org_chart_workbook(
            headers=("Name", "Manager"),
            rows=(
                ("CEO", None),
                ("CTO", "CEO"),
            ),
        )
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        labels = _shape_labels(diagram)
        # No Title column -> labels are just the names.
        assert "CEO" in labels
        assert "CTO" in labels

    def it_raises_when_an_explicit_column_is_missing(self):
        wb = _build_org_chart_workbook(
            headers=("Name", "Manager"),
            rows=(("CEO", None),),
        )
        with pytest.raises(ValueError, match="not found in sheet headers"):
            diagram_from_xlsx(
                wb,
                sheet="employees",
                kind="org-chart",
                title_col="JobTitle",  # explicit but not in header
            )

    def it_ignores_blank_rows_in_the_data_block(self):
        wb = _build_org_chart_workbook(
            headers=("Name", "Title", "Manager"),
            rows=(
                ("CEO", "Chief", None),
                (None, None, None),  # blank — skipped
                ("CTO", "Tech", "CEO"),
            ),
        )
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        labels = _shape_labels(diagram)
        # Only the two real employees rendered.
        assert "CEO\nChief" in labels
        assert "CTO\nTech" in labels

    def it_resolves_headers_case_insensitively(self):
        wb = _build_org_chart_workbook(
            headers=("name", "TITLE", "manager"),
            rows=(
                ("CEO", "Chief", None),
                ("CTO", "Tech", "CEO"),
            ),
        )
        # Caller defaults to "Name"/"Title"/"Manager" — should still match.
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        labels = _shape_labels(diagram)
        assert "CEO\nChief" in labels

    def it_forwards_title_to_the_builder(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(
            wb,
            sheet="employees",
            kind="org-chart",
            title="ACME 2026",
        )
        # Title band rectangle carries the caller's title.
        labels = _shape_labels(diagram)
        assert "ACME 2026" in labels

    def it_raises_on_an_empty_sheet(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "employees"
        ws.append(["Name", "Title"])
        # Header but no data rows.
        buf = _wb_to_bytes(wb)
        with pytest.raises(ValueError, match="contains no data rows"):
            diagram_from_xlsx(buf, sheet="employees", kind="org-chart")


# ---------------------------------------------------------------------------
# DescribeErdDispatch — kind="erd"
# ---------------------------------------------------------------------------


class DescribeErdDispatch:
    def it_collapses_rows_per_table(self):
        wb = _build_erd_workbook()
        diagram = diagram_from_xlsx(wb, sheet="columns", kind="erd")
        labels = _shape_labels(diagram)
        # Each table renders as a single rectangle whose body lists the
        # columns; tables show as "users\nid\tint  PK\n..." etc.
        assert any("users" in s for s in labels)
        assert any("orders" in s for s in labels)

    def it_emits_a_connector_per_fk(self):
        wb = _build_erd_workbook()
        diagram = diagram_from_xlsx(wb, sheet="columns", kind="erd")
        # orders.user_id -> users.id is the only FK.
        assert _connector_count(diagram) == 1

    def it_honours_custom_column_names(self):
        wb = _build_erd_workbook(
            headers=("TableName", "ColName", "ColType", "Cstr"),
            rows=(
                ("users", "id", "int", "PK"),
                ("users", "email", "varchar", ""),
            ),
        )
        diagram = diagram_from_xlsx(
            wb,
            sheet="columns",
            kind="erd",
            table_col="TableName",
            column_col="ColName",
            type_col="ColType",
            constraint_col="Cstr",
        )
        labels = _shape_labels(diagram)
        assert any("users" in s for s in labels)

    def it_falls_back_to_text_type_when_type_column_missing(self):
        wb = _build_erd_workbook(
            headers=("Table", "Column"),
            rows=(
                ("users", "id"),
                ("users", "email"),
            ),
        )
        diagram = diagram_from_xlsx(wb, sheet="columns", kind="erd")
        labels = _shape_labels(diagram)
        # The default "text" type must appear in the rendered label.
        assert any("text" in s for s in labels)

    def it_raises_when_the_table_column_is_explicit_but_missing(self):
        wb = _build_erd_workbook(
            headers=("Foo", "Column", "Type"),
            rows=(("x", "y", "z"),),
        )
        with pytest.raises(ValueError, match="not found in sheet headers"):
            diagram_from_xlsx(
                wb,
                sheet="columns",
                kind="erd",
                table_col="NotPresent",
            )

    def it_skips_rows_missing_either_required_field(self):
        wb = _build_erd_workbook(
            rows=(
                ("users", "id", "int", "PK"),
                (None, "orphan_col", "int", ""),  # no table — drop
                ("users", None, "int", ""),  # no column — drop
                ("users", "email", "varchar", ""),
            ),
        )
        diagram = diagram_from_xlsx(wb, sheet="columns", kind="erd")
        labels = _shape_labels(diagram)
        # Only the two valid columns appear in the users box.
        users_labels = [s for s in labels if "users" in s]
        assert any("id" in s and "email" in s for s in users_labels)


# ---------------------------------------------------------------------------
# DescribeProcessMapDispatch — kind="process-map"
# ---------------------------------------------------------------------------


class DescribeProcessMapDispatch:
    def it_emits_one_shape_per_step(self):
        wb = _build_process_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="process-map",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        labels = _shape_labels(diagram)
        for label in ("Begin", "Validate", "Decide", "Approve", "Reject", "Done"):
            assert label in labels

    def it_uses_the_explicit_flows_sheet(self):
        wb = _build_process_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="process-map",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        # Four explicit flow rows.
        assert _connector_count(diagram) == 4

    def it_falls_back_to_sequential_wiring_without_a_flows_sheet(self):
        # Re-build without the Flows sheet entirely.
        wb_buf = Workbook()
        ws = wb_buf.active
        ws.title = "Steps"
        ws.append(["Text", "Kind"])
        ws.append(["A", "start"])
        ws.append(["B", "task"])
        ws.append(["C", "end"])
        diagram = diagram_from_xlsx(
            _wb_to_bytes(wb_buf),
            kind="process-map",
            steps_sheet="Steps",
        )
        # Sequential wiring: A->B, B->C.
        assert _connector_count(diagram) == 2

    def it_defaults_step_kind_to_task(self):
        wb_buf = Workbook()
        ws = wb_buf.active
        ws.title = "Steps"
        ws.append(["Text"])  # No Kind column at all.
        ws.append(["Solo"])
        diagram = diagram_from_xlsx(
            _wb_to_bytes(wb_buf),
            kind="process-map",
            steps_sheet="Steps",
        )
        # One rectangle (task) — no error.
        labels = _shape_labels(diagram)
        assert "Solo" in labels

    def it_rejects_an_unrecognised_kind_token(self):
        wb_buf = Workbook()
        ws = wb_buf.active
        ws.title = "Steps"
        ws.append(["Text", "Kind"])
        ws.append(["A", "weird-kind"])
        with pytest.raises(ValueError, match="unrecognised kind"):
            diagram_from_xlsx(
                _wb_to_bytes(wb_buf),
                kind="process-map",
                steps_sheet="Steps",
            )

    def it_uses_the_active_sheet_when_no_steps_sheet_named(self):
        wb_buf = Workbook()
        ws = wb_buf.active
        ws.title = "Whatever"
        ws.append(["Text", "Kind"])
        ws.append(["A", "start"])
        ws.append(["B", "end"])
        diagram = diagram_from_xlsx(
            _wb_to_bytes(wb_buf),
            kind="process-map",
        )
        labels = _shape_labels(diagram)
        assert "A" in labels and "B" in labels


# ---------------------------------------------------------------------------
# DescribeSwimLaneDispatch — kind="swim-lane"
# ---------------------------------------------------------------------------


class DescribeSwimLaneDispatch:
    def it_auto_derives_lanes_from_step_rows(self):
        wb = _build_swim_lane_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="swim-lane",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        labels = _shape_labels(diagram)
        # Each lane name renders as its header rectangle's label.
        for lane in ("Customer", "Sales", "Warehouse"):
            assert lane in labels

    def it_uses_explicit_lanes_sheet_when_provided(self):
        wb = _build_swim_lane_workbook(include_lanes_sheet=True)
        diagram = diagram_from_xlsx(
            wb,
            kind="swim-lane",
            steps_sheet="Steps",
            flows_sheet="Flows",
            lanes_sheet="Lanes",
        )
        labels = _shape_labels(diagram)
        # Includes "Finance" — only on the Lanes sheet, not in the steps.
        assert "Finance" in labels

    def it_emits_one_connector_per_flow_row(self):
        wb = _build_swim_lane_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="swim-lane",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        # Three flow rows.
        assert _connector_count(diagram) == 3

    def it_renders_step_labels(self):
        wb = _build_swim_lane_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="swim-lane",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        labels = _shape_labels(diagram)
        for step in ("Order", "Validate", "Pick + Pack", "Receive"):
            assert step in labels

    def it_rejects_a_step_missing_its_lane_when_no_lanes_sheet(self):
        wb_buf = Workbook()
        ws = wb_buf.active
        ws.title = "Steps"
        ws.append(["Text", "Kind", "Lane"])
        ws.append(["A", "step", "Sales"])
        ws.append(["B", "step", None])  # blank lane
        with pytest.raises(ValueError, match="every step must"):
            diagram_from_xlsx(
                _wb_to_bytes(wb_buf),
                kind="swim-lane",
                steps_sheet="Steps",
            )


# ---------------------------------------------------------------------------
# DescribeWorkbookSourceHandling — paths / file-likes / pre-loaded
# ---------------------------------------------------------------------------


class DescribeWorkbookSourceHandling:
    def it_accepts_a_filesystem_path(self, tmp_path):
        wb = Workbook()
        ws = wb.active
        ws.title = "employees"
        ws.append(["Name", "Title", "Manager"])
        ws.append(["CEO", "Chief", None])
        ws.append(["CTO", "Tech", "CEO"])
        path = tmp_path / "roster.xlsx"
        wb.save(str(path))
        diagram = diagram_from_xlsx(str(path), sheet="employees", kind="org-chart")
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_accepts_a_PathLike(self, tmp_path):
        wb = Workbook()
        ws = wb.active
        ws.title = "employees"
        ws.append(["Name"])
        ws.append(["Solo"])
        path = tmp_path / "tiny.xlsx"
        wb.save(str(path))
        # pathlib.Path is os.PathLike.
        diagram = diagram_from_xlsx(path, sheet="employees", kind="org-chart")
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_accepts_a_file_like(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_accepts_a_preloaded_workbook(self):
        wb_buf = _build_org_chart_workbook()
        wb = xlsx.load_workbook(wb_buf, data_only=True)
        diagram = diagram_from_xlsx(wb, sheet="employees", kind="org-chart")
        assert isinstance(diagram, vsdx.VisioDocument)


# ---------------------------------------------------------------------------
# DescribeRoundTrip — save / re-open
# ---------------------------------------------------------------------------


class DescribeRoundTrip:
    def it_serialises_the_org_chart_dispatch_output(self):
        wb = _build_org_chart_workbook()
        diagram = diagram_from_xlsx(
            wb,
            sheet="employees",
            kind="org-chart",
            title="ACME",
        )
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.VisioPackageOpener.open(buf)
        assert len(reloaded.pages) == 1

    def it_serialises_the_erd_dispatch_output(self):
        wb = _build_erd_workbook()
        diagram = diagram_from_xlsx(wb, sheet="columns", kind="erd")
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.VisioPackageOpener.open(buf)
        assert len(reloaded.pages) == 1

    def it_serialises_the_process_map_dispatch_output(self):
        wb = _build_process_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="process-map",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.VisioPackageOpener.open(buf)
        assert len(reloaded.pages) == 1

    def it_serialises_the_swim_lane_dispatch_output(self):
        wb = _build_swim_lane_workbook()
        diagram = diagram_from_xlsx(
            wb,
            kind="swim-lane",
            steps_sheet="Steps",
            flows_sheet="Flows",
        )
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.VisioPackageOpener.open(buf)
        assert len(reloaded.pages) == 1


# ---------------------------------------------------------------------------
# DescribeKitReExports — `from vsdx.kit import diagram_from_xlsx`
# ---------------------------------------------------------------------------


class DescribeKitReExports:
    def it_reexports_diagram_from_xlsx_at_the_kit_namespace(self):
        from vsdx import kit
        assert kit.diagram_from_xlsx is diagram_from_xlsx

    def it_reexports_kind_constants_at_the_kit_namespace(self):
        from vsdx import kit
        assert kit.KIND_ORG_CHART == "org-chart"
        assert kit.KIND_ERD == "erd"
        assert kit.KIND_PROCESS_MAP == "process-map"
        assert kit.KIND_SWIM_LANE == "swim-lane"
        assert "diagram_from_xlsx" in kit.__all__
