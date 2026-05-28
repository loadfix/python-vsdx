"""Unit tests for ``Page.lint`` and the eight 0.3.0 lint rules.

Each rule has dedicated coverage — a positive case (the rule fires) and
either a negative case (the rule stays quiet) or a sibling rule check
that confirms the dispatcher honours the ``rules=`` filter.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import io

import pytest

import vsdx
from vsdx.lint import (
    DEFAULT_RULES,
    Finding,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    lint,
)


def _new_page(name: str = "P"):
    doc = vsdx.Visio()
    return doc, doc.pages.add_page(name=name, width=10, height=10)


class DescribeLintAPI:
    def it_is_reachable_via_page_lint(self) -> None:
        _, page = _new_page()
        assert page.lint() == []

    def it_returns_a_list_of_findings(self) -> None:
        _, page = _new_page()
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(3, 3))
        page.shapes.add_shape("Rectangle", at=(2.5, 2), size=(3, 3))
        result = page.lint(rules=["shape-overlap"])
        assert isinstance(result, list)
        assert all(isinstance(f, Finding) for f in result)

    def it_respects_the_rules_filter(self) -> None:
        _, page = _new_page()
        # An unconnected shape would fire `disconnected-node` if the
        # default rules were active. With only `shape-overlap` selected,
        # the result should be empty.
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(2, 2))
        assert page.lint(rules=["shape-overlap"]) == []

    def it_lists_eight_default_rules(self) -> None:
        assert len(DEFAULT_RULES) == 8

    def it_silently_ignores_unknown_rule_ids(self) -> None:
        _, page = _new_page()
        # No raise.
        assert page.lint(rules=["does-not-exist"]) == []


class DescribeShapeOverlapRule:
    def it_flags_overlapping_shapes(self) -> None:
        _, page = _new_page()
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(3, 3))
        page.shapes.add_shape("Rectangle", at=(3, 2), size=(3, 3))
        result = lint(page, rules=["shape-overlap"])
        assert any(
            f.rule_id == "shape-overlap" and f.severity == SEVERITY_ERROR
            for f in result
        )

    def it_ignores_shapes_that_only_touch(self) -> None:
        _, page = _new_page()
        # Two 2x2 rectangles whose right / left edges share x=3.
        page.shapes.add_shape("Rectangle", at=(2, 5), size=(2, 2))
        page.shapes.add_shape("Rectangle", at=(4, 5), size=(2, 2))
        result = lint(page, rules=["shape-overlap"])
        assert result == []

    def it_ignores_overlap_below_5_percent(self) -> None:
        _, page = _new_page()
        # 4x4 + 4x4 overlap of 0.1x4 = 0.4 sq-in vs 16 sq-in = 2.5%.
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(4, 4))
        page.shapes.add_shape("Rectangle", at=(5.9, 2), size=(4, 4))
        result = lint(page, rules=["shape-overlap"])
        assert result == []


class DescribeDisconnectedNodeRule:
    def it_flags_a_shape_with_no_connectors(self) -> None:
        _, page = _new_page()
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        result = lint(page, rules=["disconnected-node"])
        assert len(result) == 1
        assert result[0].rule_id == "disconnected-node"
        assert result[0].severity == SEVERITY_WARNING

    def it_does_not_flag_a_connected_shape(self) -> None:
        _, page = _new_page()
        a = page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        b = page.shapes.add_shape("Rectangle", at=(6, 2), size=(1, 1))
        page.connect(a, b)
        result = lint(page, rules=["disconnected-node"])
        assert result == []


class DescribeUnlabeledConnectorRule:
    def it_flags_a_connector_without_text(self) -> None:
        _, page = _new_page()
        a = page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        b = page.shapes.add_shape("Rectangle", at=(6, 2), size=(1, 1))
        page.connect(a, b)
        result = lint(page, rules=["unlabeled-connector"])
        assert len(result) == 1
        assert result[0].rule_id == "unlabeled-connector"

    def it_does_not_flag_a_labeled_connector(self) -> None:
        _, page = _new_page()
        a = page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        b = page.shapes.add_shape("Rectangle", at=(6, 2), size=(1, 1))
        conn = page.connect(a, b)
        conn.text = "step 1"
        result = lint(page, rules=["unlabeled-connector"])
        assert result == []


class DescribeConnectorCrossingsRule:
    def it_flags_a_busy_diagram(self) -> None:
        _, page = _new_page()
        # Build a fan: six shapes; one row at y=2 and another at y=8;
        # cross-connect every top to every bottom => up to 9 crossings
        # with a left-right shuffle.
        tops = [
            page.shapes.add_shape("Rectangle", at=(2 + i * 2, 2), size=(0.5, 0.5))
            for i in range(3)
        ]
        bots = [
            page.shapes.add_shape("Rectangle", at=(2 + i * 2, 8), size=(0.5, 0.5))
            for i in range(3)
        ]
        # Cross-connect: top[0]->bot[2], top[1]->bot[1], top[2]->bot[0]
        # plus the same set inverted to spike the count above the threshold.
        page.connect(tops[0], bots[2])
        page.connect(tops[2], bots[0])
        page.connect(tops[0], bots[1])
        page.connect(tops[1], bots[2])
        page.connect(tops[2], bots[1])
        page.connect(tops[1], bots[0])
        result = lint(page, rules=["connector-crossings"])
        assert len(result) == 1
        assert result[0].rule_id == "connector-crossings"
        assert result[0].severity == SEVERITY_INFO

    def it_does_not_flag_a_quiet_diagram(self) -> None:
        _, page = _new_page()
        a = page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        b = page.shapes.add_shape("Rectangle", at=(6, 2), size=(1, 1))
        page.connect(a, b)
        result = lint(page, rules=["connector-crossings"])
        assert result == []


class DescribeInconsistentShapeSizeRule:
    def it_flags_more_than_2x_variance(self) -> None:
        _, page = _new_page()
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        page.shapes.add_shape("Rectangle", at=(4, 4), size=(3, 3))
        result = lint(page, rules=["inconsistent-shape-size"])
        assert len(result) == 1
        assert result[0].rule_id == "inconsistent-shape-size"

    def it_does_not_flag_a_consistent_set(self) -> None:
        _, page = _new_page()
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        page.shapes.add_shape("Rectangle", at=(4, 4), size=(1.2, 1.2))
        result = lint(page, rules=["inconsistent-shape-size"])
        assert result == []


class DescribeOffGridRule:
    def it_skips_when_no_grid_is_set(self) -> None:
        _, page = _new_page()
        page.shapes.add_shape("Rectangle", at=(2.37, 2.81), size=(1, 1))
        result = lint(page, rules=["off-grid"])
        assert result == []

    def it_flags_off_grid_pins_when_grid_is_set(self) -> None:
        _, page = _new_page()
        # 1-inch grid.
        page._set_sheet_cell_v("XGridSpacing", "1", unit="IN")
        page._set_sheet_cell_v("YGridSpacing", "1", unit="IN")
        page.shapes.add_shape("Rectangle", at=(2.37, 2.81), size=(1, 1))
        result = lint(page, rules=["off-grid"])
        assert len(result) == 1
        assert result[0].severity == SEVERITY_INFO

    def it_does_not_flag_aligned_pins(self) -> None:
        _, page = _new_page()
        page._set_sheet_cell_v("XGridSpacing", "1", unit="IN")
        page._set_sheet_cell_v("YGridSpacing", "1", unit="IN")
        page.shapes.add_shape("Rectangle", at=(3, 4), size=(1, 1))
        result = lint(page, rules=["off-grid"])
        assert result == []


class DescribeTextOverflowRule:
    def it_flags_overflowing_text(self) -> None:
        _, page = _new_page()
        rect = page.shapes.add_shape("Rectangle", at=(2, 2), size=(0.5, 0.3))
        rect.text = "this label is far too long to fit in a tiny rectangle"
        result = lint(page, rules=["text-overflow"])
        assert len(result) == 1
        assert result[0].rule_id == "text-overflow"

    def it_does_not_flag_a_well_sized_label(self) -> None:
        _, page = _new_page()
        rect = page.shapes.add_shape("Rectangle", at=(2, 2), size=(4, 2))
        rect.text = "ok"
        result = lint(page, rules=["text-overflow"])
        assert result == []


class DescribeLabelReadabilityRule:
    def it_flags_a_too_small_label(self) -> None:
        _, page = _new_page()
        rect = page.shapes.add_shape("Rectangle", at=(2, 2), size=(2, 1))
        rect.text = "tiny"
        # Stamp a 6pt size on the Character section.
        section = rect._element._add_section()
        section.set("N", "Character")
        row = section._add_row()
        row.set("IX", "0")
        cell = row._add_cell()
        cell.set("N", "Size")
        cell.set("V", "6")
        cell.set("U", "PT")
        result = lint(page, rules=["label-readability"])
        assert len(result) == 1
        assert result[0].rule_id == "label-readability"

    def it_does_not_flag_a_normal_label(self) -> None:
        _, page = _new_page()
        rect = page.shapes.add_shape("Rectangle", at=(2, 2), size=(2, 1))
        rect.text = "ok"
        result = lint(page, rules=["label-readability"])
        assert result == []


class DescribeFindingRepr:
    def it_renders_with_the_target_shape_id(self) -> None:
        _, page = _new_page()
        rect = page.shapes.add_shape("Rectangle", at=(2, 2), size=(1, 1))
        finding = Finding(
            rule_id="x", severity=SEVERITY_WARNING, message="hi", target=rect
        )
        s = str(finding)
        assert "[warning]" in s
        assert "x" in s
        assert "shape %d" % rect.shape_id in s

    def it_renders_without_a_target(self) -> None:
        finding = Finding(rule_id="x", severity=SEVERITY_INFO, message="hi")
        assert "shape" not in str(finding)


class DescribeCLI:
    def it_prints_clean_for_a_clean_page(self, capsys, tmp_path) -> None:
        from vsdx.__main__ import main

        doc = vsdx.Visio()
        doc.pages.add_page(name="Page-1")
        path = tmp_path / "clean.vsdx"
        doc.save(str(path))
        rc = main(["lint", str(path)])
        captured = capsys.readouterr()
        assert rc == 0
        assert "clean" in captured.out

    def it_returns_nonzero_on_an_error_finding(self, capsys, tmp_path) -> None:
        from vsdx.__main__ import main

        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1", width=10, height=10)
        page.shapes.add_shape("Rectangle", at=(2, 2), size=(3, 3))
        page.shapes.add_shape("Rectangle", at=(3, 2), size=(3, 3))
        path = tmp_path / "overlap.vsdx"
        doc.save(str(path))
        rc = main(["lint", str(path)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "shape-overlap" in captured.out
