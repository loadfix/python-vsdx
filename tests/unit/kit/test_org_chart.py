# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.org_chart` — issue #122."""

from __future__ import annotations

from io import BytesIO

import pytest

import vsdx
from vsdx.kit import (
    DEFAULT_MANAGER_COL,
    DEFAULT_NAME_COL,
    DEFAULT_PHOTO_COL,
    DEFAULT_TEAM_COL,
    DEFAULT_TITLE_COL,
    build_org_chart,
    build_org_chart_from_csv,
)
from vsdx.shapes.connector import Connector

# ---------------------------------------------------------------------------
# Canonical fixture — a four-person org with two branches off the CEO
# ---------------------------------------------------------------------------


_FIXTURE_EMPLOYEES = [
    {"name": "CEO", "title": "Chief Exec", "manager": None},
    {"name": "CTO", "title": "Chief Tech", "manager": "CEO"},
    {"name": "CFO", "title": "Chief Fin", "manager": "CEO"},
    {"name": "VPE", "title": "VP Engineering", "manager": "CTO"},
]


def _build_fixture(**kwargs):
    return build_org_chart(employees=_FIXTURE_EMPLOYEES, **kwargs)


# ---------------------------------------------------------------------------
# DescribeBuildOrgChart — happy-path acceptance
# ---------------------------------------------------------------------------


class DescribeBuildOrgChart:
    def it_returns_a_VisioDocument(self):
        diagram = _build_fixture()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page(self):
        diagram = _build_fixture()
        assert len(diagram.pages) == 1

    def it_defaults_the_page_name_to_Org_chart_when_no_title(self):
        diagram = _build_fixture()
        assert diagram.pages[0].name == "Org chart"

    def it_uses_the_title_as_the_page_name(self):
        diagram = _build_fixture(title="ACME 2026")
        assert diagram.pages[0].name == "ACME 2026"

    def it_honours_an_explicit_page_name_over_the_title(self):
        diagram = _build_fixture(title="ACME", page_name="Org chart v2")
        assert diagram.pages[0].name == "Org chart v2"

    def it_emits_one_box_per_employee(self):
        diagram = _build_fixture()
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        # Four employee boxes; no title band because title was empty.
        assert len(boxes) == len(_FIXTURE_EMPLOYEES)

    def it_emits_a_title_band_when_title_is_non_empty(self):
        diagram = _build_fixture(title="ACME 2026")
        non_connector = [
            s for s in diagram.pages[0].shapes if not isinstance(s, Connector)
        ]
        # 1 title band + 4 employees
        assert len(non_connector) == 1 + len(_FIXTURE_EMPLOYEES)
        # The title shape's text matches the caller's title.
        title_shape = next(s for s in non_connector if s.text == "ACME 2026")
        assert title_shape is not None

    def it_renders_each_box_with_name_and_title_on_two_lines(self):
        diagram = _build_fixture()
        labels = {
            s.text
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
        }
        assert "CEO\nChief Exec" in labels
        assert "CTO\nChief Tech" in labels
        assert "CFO\nChief Fin" in labels
        assert "VPE\nVP Engineering" in labels

    def it_renders_a_box_with_only_a_name_when_title_is_omitted(self):
        diagram = build_org_chart(
            employees=[{"name": "Solo"}],
        )
        labels = {
            s.text
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
        }
        assert "Solo" in labels
        # No newline — only-name boxes have a single text line.
        assert "Solo\n" not in labels


# ---------------------------------------------------------------------------
# DescribeOrgChartConnectors — manager → report wiring
# ---------------------------------------------------------------------------


class DescribeOrgChartConnectors:
    def it_emits_one_connector_per_manager_link(self):
        diagram = _build_fixture()
        conns = [
            s
            for s in diagram.pages[0].shapes
            if isinstance(s, Connector)
        ]
        # CEO has two reports (CTO, CFO), CTO has one (VPE) — 3 edges.
        assert len(conns) == 3

    def it_emits_no_connector_for_a_root_only_roster(self):
        diagram = build_org_chart(
            employees=[{"name": "CEO"}],
        )
        conns = [
            s
            for s in diagram.pages[0].shapes
            if isinstance(s, Connector)
        ]
        assert conns == []

    def it_routes_connectors_with_right_angle_routing_by_default(self):
        diagram = _build_fixture()
        page = diagram.pages[0]
        # Right-angle routing produces a multi-segment polyline; the
        # connector's geometry section has at least one moveto + lineto.
        for conn in (s for s in page.shapes if isinstance(s, Connector)):
            # Sanity — both endpoints must be set.
            assert conn.begin_x is not None
            assert conn.end_x is not None


# ---------------------------------------------------------------------------
# DescribeOrgChartLayout — hierarchy placer outputs
# ---------------------------------------------------------------------------


class DescribeOrgChartLayout:
    def it_places_the_root_above_the_reports(self):
        diagram = _build_fixture()
        boxes = {
            s.text.split("\n", 1)[0]: s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        }
        # In Visio coordinates Y increases upward, so the root has the
        # largest pin_y on the page.
        ceo_y = float(boxes["CEO"].pin_y)
        cto_y = float(boxes["CTO"].pin_y)
        cfo_y = float(boxes["CFO"].pin_y)
        vpe_y = float(boxes["VPE"].pin_y)
        assert ceo_y > cto_y
        assert ceo_y > cfo_y
        assert cto_y > vpe_y

    def it_spreads_siblings_horizontally(self):
        diagram = _build_fixture()
        boxes = {
            s.text.split("\n", 1)[0]: s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        }
        cto_x = float(boxes["CTO"].pin_x)
        cfo_x = float(boxes["CFO"].pin_x)
        # CTO and CFO are sibling reports of CEO — they must not overlap
        # on the cross axis.
        assert cto_x != cfo_x

    def it_lays_out_disjoint_trees_side_by_side(self):
        diagram = build_org_chart(
            employees=[
                {"name": "Alice"},
                {"name": "Bob"},
                {"name": "Carol", "manager": "Bob"},
            ],
        )
        boxes = {
            s.text: s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        }
        # Two disjoint roots get distinct cross-axis positions.
        assert float(boxes["Alice"].pin_x) != float(boxes["Bob"].pin_x)


# ---------------------------------------------------------------------------
# DescribeOrgChartShapeData — optional photo + team
# ---------------------------------------------------------------------------


class DescribeOrgChartShapeData:
    def it_records_the_photo_path_on_the_box_shape_data(self):
        diagram = build_org_chart(
            employees=[
                {"name": "Alice", "photo": "https://example.com/a.png"},
            ],
        )
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text == "Alice"
        ]
        assert len(boxes) == 1
        assert boxes[0].data["Photo"] == "https://example.com/a.png"

    def it_records_the_team_label_on_the_box_shape_data(self):
        diagram = build_org_chart(
            employees=[
                {"name": "Alice", "team": "Platform"},
            ],
        )
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text == "Alice"
        ]
        assert boxes[0].data["Team"] == "Platform"

    def it_omits_optional_fields_when_absent(self):
        diagram = build_org_chart(
            employees=[{"name": "Alice"}],
        )
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text == "Alice"
        ]
        # Asking for a missing field raises KeyError rather than
        # silently returning an empty string.
        with pytest.raises(KeyError):
            boxes[0].data["Photo"]


# ---------------------------------------------------------------------------
# DescribeOrgChartValidation — rejection paths
# ---------------------------------------------------------------------------


class DescribeOrgChartValidation:
    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError):
            build_org_chart(employees=_FIXTURE_EMPLOYEES, title=123)  # type: ignore[arg-type]

    def it_rejects_an_empty_roster(self):
        with pytest.raises(ValueError, match="at least one"):
            build_org_chart(employees=[])

    def it_rejects_an_employee_with_no_name(self):
        with pytest.raises(ValueError, match="missing a required 'name'"):
            build_org_chart(employees=[{"title": "no name"}])

    def it_rejects_a_blank_name(self):
        with pytest.raises(ValueError, match="non-empty str"):
            build_org_chart(employees=[{"name": "   "}])

    def it_rejects_duplicate_names(self):
        with pytest.raises(ValueError, match="duplicated"):
            build_org_chart(
                employees=[
                    {"name": "Alice"},
                    {"name": "Alice", "manager": "Alice"},
                ],
            )

    def it_rejects_a_manager_not_in_the_roster(self):
        with pytest.raises(ValueError, match="not in the roster"):
            build_org_chart(
                employees=[
                    {"name": "Alice", "manager": "Bob"},
                ],
            )

    def it_rejects_a_self_managed_employee(self):
        with pytest.raises(ValueError, match="own manager"):
            build_org_chart(
                employees=[
                    {"name": "Alice", "manager": "Alice"},
                ],
            )

    def it_rejects_a_manager_cycle(self):
        with pytest.raises(ValueError, match="cycle"):
            build_org_chart(
                employees=[
                    {"name": "A", "manager": "B"},
                    {"name": "B", "manager": "A"},
                ],
            )

    def it_rejects_a_non_mapping_employee(self):
        with pytest.raises(ValueError, match="must be a Mapping"):
            build_org_chart(employees=[("name", "Alice")])  # type: ignore[list-item]

    def it_rejects_a_non_string_title_field_on_an_employee(self):
        with pytest.raises(ValueError, match="must be a str"):
            build_org_chart(
                employees=[{"name": "Alice", "title": 42}],
            )


# ---------------------------------------------------------------------------
# DescribeBuildOrgChartFromCsv — CSV reader
# ---------------------------------------------------------------------------


_FULL_CSV = (
    "name,title,manager,photo,team\n"
    "CEO,Chief Exec,,/photos/ceo.png,Exec\n"
    "CTO,Chief Tech,CEO,/photos/cto.png,Exec\n"
    "VPE,VP Engineering,CTO,,Engineering\n"
)


class DescribeBuildOrgChartFromCsv:
    def it_reads_the_default_columns(self, tmp_path):
        path = tmp_path / "roster.csv"
        path.write_text(_FULL_CSV, encoding="utf-8")

        diagram = build_org_chart_from_csv(str(path))
        labels = {
            s.text
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
        }
        assert "CEO\nChief Exec" in labels
        assert "CTO\nChief Tech" in labels
        assert "VPE\nVP Engineering" in labels

    def it_accepts_a_PathLike_path(self, tmp_path):
        path = tmp_path / "roster.csv"
        path.write_text(_FULL_CSV, encoding="utf-8")

        # pathlib.Path is os.PathLike — should work without str().
        diagram = build_org_chart_from_csv(path)
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_propagates_photo_and_team_to_shape_data(self, tmp_path):
        path = tmp_path / "roster.csv"
        path.write_text(_FULL_CSV, encoding="utf-8")

        diagram = build_org_chart_from_csv(str(path))
        ceo = next(
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text.startswith("CEO")
        )
        assert ceo.data["Photo"] == "/photos/ceo.png"
        assert ceo.data["Team"] == "Exec"

    def it_treats_blank_manager_cells_as_a_root(self, tmp_path):
        path = tmp_path / "roster.csv"
        path.write_text(_FULL_CSV, encoding="utf-8")

        diagram = build_org_chart_from_csv(str(path))
        conns = [
            s
            for s in diagram.pages[0].shapes
            if isinstance(s, Connector)
        ]
        # CEO is a root (blank manager), so two connectors: CEO->CTO,
        # CTO->VPE. CEO with blank manager must NOT be wired to itself.
        assert len(conns) == 2

    def it_skips_optional_columns_when_absent_from_the_header(self, tmp_path):
        path = tmp_path / "two_col.csv"
        path.write_text(
            "name,manager\nCEO,\nCTO,CEO\n",
            encoding="utf-8",
        )

        diagram = build_org_chart_from_csv(str(path))
        labels = {
            s.text
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
        }
        # No title column → label is just the name.
        assert "CEO" in labels
        assert "CTO" in labels

    def it_honours_custom_column_names(self, tmp_path):
        path = tmp_path / "alt.csv"
        path.write_text(
            "Employee,Role,ReportsTo\n"
            "CEO,Chief Exec,\n"
            "CTO,Chief Tech,CEO\n",
            encoding="utf-8",
        )

        diagram = build_org_chart_from_csv(
            str(path),
            name_col="Employee",
            title_col="Role",
            manager_col="ReportsTo",
        )
        labels = {
            s.text
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
        }
        assert "CEO\nChief Exec" in labels
        assert "CTO\nChief Tech" in labels

    def it_rejects_a_csv_missing_the_name_column(self, tmp_path):
        path = tmp_path / "no_name.csv"
        path.write_text("title,manager\nChief,\n", encoding="utf-8")
        with pytest.raises(ValueError, match="required 'name' header"):
            build_org_chart_from_csv(str(path))

    def it_skips_rows_with_a_blank_name(self, tmp_path):
        path = tmp_path / "blank.csv"
        path.write_text(
            "name,manager\n"
            ",\n"  # blank name — ignored
            "CEO,\n"
            "CTO,CEO\n",
            encoding="utf-8",
        )
        diagram = build_org_chart_from_csv(str(path))
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
        ]
        # Two real employees only.
        assert len(boxes) == 2

    def it_propagates_cycle_validation_through_csv(self, tmp_path):
        path = tmp_path / "cycle.csv"
        path.write_text(
            "name,manager\n"
            "A,B\n"
            "B,A\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="cycle"):
            build_org_chart_from_csv(str(path))


# ---------------------------------------------------------------------------
# DescribeOrgChartRoundTrip — save / open
# ---------------------------------------------------------------------------


class DescribeOrgChartRoundTrip:
    def it_serialises_and_re_opens_cleanly(self):
        diagram = _build_fixture(title="ACME 2026")
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.VisioPackageOpener.open(buf)
        assert len(reloaded.pages) == 1


# ---------------------------------------------------------------------------
# DescribeKitConstants — re-export sanity
# ---------------------------------------------------------------------------


class DescribeKitConstants:
    def it_exposes_the_default_csv_column_names(self):
        assert DEFAULT_NAME_COL == "name"
        assert DEFAULT_TITLE_COL == "title"
        assert DEFAULT_MANAGER_COL == "manager"
        assert DEFAULT_PHOTO_COL == "photo"
        assert DEFAULT_TEAM_COL == "team"
