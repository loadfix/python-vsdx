# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.fishbone` — issue #129."""

from __future__ import annotations

import math
from io import BytesIO

import pytest

import vsdx
from vsdx.kit import (
    FISHBONE_BRANCH_ANGLE_DEG,
    FISHBONE_DEFAULT_CATEGORIES,
    build_fishbone,
)


# ---------------------------------------------------------------------------
# Canonical fixture used by the bulk of the tests
# ---------------------------------------------------------------------------


_PROBLEM = "Customer churn higher than target"

_CATEGORIES = {
    "People": ["Insufficient training", "Turnover in CS team"],
    "Process": ["Slow ticket triage", "Manual onboarding"],
    "Product": ["Confusing pricing page", "Missing dashboards"],
    "Technology": ["API errors during peak", "Outdated docs"],
    "Environment": ["Recession headwinds"],
    "Measurement": ["NPS sample too small"],
}


def _build():
    return build_fishbone(problem=_PROBLEM, categories=_CATEGORIES)


# ---------------------------------------------------------------------------
# DescribeBuildFishbone — the document / page / shape contract
# ---------------------------------------------------------------------------


class DescribeBuildFishbone:
    def it_returns_a_VisioDocument(self):
        diagram = _build()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page(self):
        diagram = _build()
        assert len(diagram.pages) == 1

    def it_names_the_page_after_the_problem_by_default(self):
        diagram = _build()
        assert diagram.pages[0].name == _PROBLEM

    def it_honours_an_explicit_title(self):
        diagram = build_fishbone(
            problem="P", categories=_CATEGORIES, title="Workshop"
        )
        assert diagram.pages[0].name == "Workshop"

    def it_honours_an_explicit_page_name(self):
        diagram = build_fishbone(
            problem="P",
            categories=_CATEGORIES,
            page_name="Override",
        )
        assert diagram.pages[0].name == "Override"

    def it_falls_back_to_Fishbone_for_an_empty_title(self):
        diagram = build_fishbone(
            problem="P", categories=_CATEGORIES, title=""
        )
        assert diagram.pages[0].name == "Fishbone"

    def it_renders_the_problem_statement_as_a_rectangle(self):
        diagram = _build()
        page = diagram.pages[0]
        # Two rectangles carry the problem text — the title band
        # (full-width) and the head-of-the-fish problem box. Either
        # way both are Rectangle masters.
        problem_shapes = [s for s in page.shapes if s.text == _PROBLEM]
        assert problem_shapes
        for s in problem_shapes:
            assert s.master_name_u == "Rectangle"

    def it_anchors_the_problem_box_at_the_right_of_the_page(self):
        diagram = _build()
        page = diagram.pages[0]
        page_w = float(page.width)
        # The head-of-the-fish problem box is the *narrow* one — the
        # title band spans the inner width.
        problem_shapes = [s for s in page.shapes if s.text == _PROBLEM]
        head = min(problem_shapes, key=lambda s: float(s.width))
        # Problem-box centre lives in the right third of the page.
        assert float(head.pin_x) > page_w * 2 / 3

    def it_renders_a_rectangle_for_each_category_label(self):
        diagram = _build()
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        for cat in _CATEGORIES:
            assert cat in texts, f"missing category label {cat!r}"

    def it_renders_a_label_for_each_sub_cause(self):
        diagram = _build()
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        for subs in _CATEGORIES.values():
            for sub in subs:
                assert sub in texts, f"missing sub-cause label {sub!r}"


# ---------------------------------------------------------------------------
# DescribeFishboneLayout — the geometric contract that makes it a fishbone
# ---------------------------------------------------------------------------


class DescribeFishboneLayout:
    def it_alternates_categories_top_and_bottom_around_the_spine(self):
        diagram = _build()
        page = diagram.pages[0]
        page_h = float(page.height)
        # The spine sits at roughly the body's vertical midline; we
        # don't need its exact y, just to compare each category's pin_y
        # against the previous one.
        ys: list = []
        for cat in _CATEGORIES:
            shape = next(s for s in page.shapes if s.text == cat)
            ys.append(float(shape.pin_y))
        # First category goes above the page midline; the second goes
        # below; the third above; etc.
        midline = page_h / 2
        for ix, y in enumerate(ys):
            if ix % 2 == 0:
                assert y > midline, (
                    f"category #{ix} should sit above the spine, got y={y}"
                )
            else:
                assert y < midline, (
                    f"category #{ix} should sit below the spine, got y={y}"
                )

    def it_arranges_categories_left_to_right_in_mapping_order(self):
        diagram = _build()
        page = diagram.pages[0]
        # For top branches (alternating, starting at index 0), the
        # category-label x-coords increase as we move through the
        # mapping. We only assert top vs top and bottom vs bottom —
        # adjacent categories alternate sides so their direct x order
        # isn't meaningful.
        cat_names = list(_CATEGORIES)
        xs = {
            cat: float(next(s for s in page.shapes if s.text == cat).pin_x)
            for cat in cat_names
        }
        top_xs = [xs[cat_names[i]] for i in range(0, len(cat_names), 2)]
        bot_xs = [xs[cat_names[i]] for i in range(1, len(cat_names), 2)]
        for prev, curr in zip(top_xs, top_xs[1:]):
            assert prev < curr
        for prev, curr in zip(bot_xs, bot_xs[1:]):
            assert prev < curr

    def it_keeps_every_shape_inside_the_page(self):
        diagram = _build()
        page = diagram.pages[0]
        page_w = float(page.width)
        page_h = float(page.height)
        for shape in page.shapes:
            x = float(shape.pin_x)
            y = float(shape.pin_y)
            assert 0 <= x <= page_w, (
                f"shape {shape.text!r} pin_x={x} outside page width {page_w}"
            )
            assert 0 <= y <= page_h, (
                f"shape {shape.text!r} pin_y={y} outside page height {page_h}"
            )

    def it_emits_a_horizontal_spine_running_across_the_page(self):
        diagram = _build()
        page = diagram.pages[0]
        page_w = float(page.width)
        # The spine is the widest master-less line shape on the page.
        # All custom-shape lines have master_name_u == None (or empty).
        line_widths = [
            float(s.width)
            for s in page.shapes
            if not s.master_name_u
        ]
        assert line_widths, "no master-less line shapes were authored"
        # Spine should be wider than any individual branch — it spans
        # most of the inner page.
        assert max(line_widths) > page_w / 2

    def it_uses_a_60_degree_branch_angle(self):
        # Sanity-check the public constant — keeps the layout's
        # signature contract pinned.
        assert FISHBONE_BRANCH_ANGLE_DEG == 60.0
        # And confirm a top branch's slope matches sin(60°)/cos(60°).
        diagram = _build()
        page = diagram.pages[0]
        # Find the first category-label shape (top branch).
        first_cat_name = next(iter(_CATEGORIES))
        cat_shape = next(s for s in page.shapes if s.text == first_cat_name)
        # We can't easily recover the joint x without rebuilding the
        # geometry, but we can confirm the label was lifted *above* the
        # vertical mid-line by an amount consistent with sin(60°) being
        # > 0.5 — i.e. a healthy, non-trivial vertical offset.
        page_h = float(page.height)
        midline = page_h / 2
        assert float(cat_shape.pin_y) - midline > 0.5

    def it_renders_each_sub_cause_with_a_whisker_segment(self):
        # Sub-causes ship with a short horizontal whisker line plus a
        # text caption; counting line shapes vs labels gives a quick
        # parity check.
        diagram = _build()
        page = diagram.pages[0]
        n_subs = sum(len(v) for v in _CATEGORIES.values())
        # Master-less line segments: 1 spine + 1 per category branch +
        # 1 per sub-cause whisker.
        line_shapes = [s for s in page.shapes if not s.master_name_u]
        expected = 1 + len(_CATEGORIES) + n_subs
        assert len(line_shapes) == expected


# ---------------------------------------------------------------------------
# DescribeFishboneDefaults — the 6Ms fallback
# ---------------------------------------------------------------------------


class DescribeFishboneDefaults:
    def it_uses_the_six_Ms_when_categories_is_omitted(self):
        diagram = build_fishbone(problem="Why?")
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        for cat in FISHBONE_DEFAULT_CATEGORIES:
            assert cat in texts, f"missing default category {cat!r}"

    def it_uses_the_six_Ms_when_categories_is_None(self):
        diagram = build_fishbone(problem="Why?", categories=None)
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        for cat in FISHBONE_DEFAULT_CATEGORIES:
            assert cat in texts

    def it_lists_the_canonical_six_Ms_in_order(self):
        assert FISHBONE_DEFAULT_CATEGORIES == (
            "People",
            "Process",
            "Product",
            "Technology",
            "Environment",
            "Measurement",
        )

    def it_renders_a_default_fishbone_with_no_subcauses(self):
        # The 6Ms default is an empty-list-per-category schema —
        # branches render but no whiskers hang off them.
        diagram = build_fishbone(problem="Why?")
        page = diagram.pages[0]
        line_shapes = [s for s in page.shapes if not s.master_name_u]
        # 1 spine + 6 branches, no whiskers.
        assert len(line_shapes) == 1 + len(FISHBONE_DEFAULT_CATEGORIES)


# ---------------------------------------------------------------------------
# DescribeFishboneCustomCategories — arbitrary keys + ordering
# ---------------------------------------------------------------------------


class DescribeFishboneCustomCategories:
    def it_accepts_arbitrary_category_keys(self):
        diagram = build_fishbone(
            problem="Site outage",
            categories={
                "Hardware": ["Disk failure"],
                "Software": ["Race condition"],
                "Operator": ["Bad config push"],
            },
        )
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        for cat in ("Hardware", "Software", "Operator"):
            assert cat in texts

    def it_preserves_the_order_of_the_categories_mapping(self):
        # Insertion order on the mapping → left-to-right placement on
        # the page.
        cats = {
            "Z": ["a"],
            "A": ["b"],
            "M": ["c"],
            "B": ["d"],
        }
        diagram = build_fishbone(problem="P", categories=cats)
        page = diagram.pages[0]
        # Z and M are top branches (indices 0 and 2); their pin_x
        # values should ascend.
        z_x = float(next(s for s in page.shapes if s.text == "Z").pin_x)
        m_x = float(next(s for s in page.shapes if s.text == "M").pin_x)
        assert z_x < m_x

    def it_accepts_a_category_with_no_subcauses(self):
        diagram = build_fishbone(
            problem="P",
            categories={
                "Has subs": ["a", "b"],
                "Empty": [],
                "Also has": ["c"],
            },
        )
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        # All three category labels render; the empty category just
        # has no whiskers.
        for cat in ("Has subs", "Empty", "Also has"):
            assert cat in texts

    def it_supports_a_single_category(self):
        diagram = build_fishbone(
            problem="One thing",
            categories={"Solo": ["sub-1", "sub-2"]},
        )
        page = diagram.pages[0]
        texts = {s.text for s in page.shapes}
        assert "Solo" in texts
        assert "sub-1" in texts
        assert "sub-2" in texts


# ---------------------------------------------------------------------------
# DescribeFishboneRoundTrip — save / reload integrity
# ---------------------------------------------------------------------------


class DescribeFishboneRoundTrip:
    def it_round_trips_through_save_and_reload(self, tmp_path):
        diagram = _build()
        out = tmp_path / "fishbone.vsdx"
        diagram.save(str(out))
        reloaded = vsdx.Visio(str(out))
        assert len(reloaded.pages) == 1
        assert reloaded.pages[0].name == _PROBLEM
        original_count = len(list(diagram.pages[0].shapes))
        assert len(list(reloaded.pages[0].shapes)) == original_count

    def it_round_trips_through_an_in_memory_buffer(self):
        diagram = _build()
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        texts = {s.text for s in reloaded.pages[0].shapes}
        # Problem + every category + every sub-cause survive.
        assert _PROBLEM in texts
        for cat, subs in _CATEGORIES.items():
            assert cat in texts
            for sub in subs:
                assert sub in texts


# ---------------------------------------------------------------------------
# DescribeBuildFishboneValidation
# ---------------------------------------------------------------------------


class DescribeBuildFishboneValidation:
    def it_rejects_a_non_string_problem(self):
        with pytest.raises(TypeError, match="problem must be a str"):
            build_fishbone(
                problem=42,  # type: ignore[arg-type]
                categories=_CATEGORIES,
            )

    def it_rejects_an_empty_problem(self):
        with pytest.raises(ValueError, match="problem must be a non-empty"):
            build_fishbone(problem="", categories=_CATEGORIES)

    def it_rejects_a_non_mapping_categories(self):
        with pytest.raises(TypeError, match="categories must be a Mapping"):
            build_fishbone(
                problem="P",
                categories=["People", "Process"],  # type: ignore[arg-type]
            )

    def it_rejects_an_empty_categories_mapping(self):
        with pytest.raises(ValueError, match="at least one category"):
            build_fishbone(problem="P", categories={})

    def it_rejects_an_empty_category_name(self):
        with pytest.raises(ValueError, match="non-empty str"):
            build_fishbone(
                problem="P", categories={"": ["sub"]}
            )

    def it_rejects_a_non_string_subcause(self):
        with pytest.raises(ValueError, match="non-empty str"):
            build_fishbone(
                problem="P",
                categories={"People": ["", "valid"]},
            )

    def it_rejects_a_None_subcause_list(self):
        with pytest.raises(TypeError, match="must be a sequence"):
            build_fishbone(
                problem="P",
                categories={"People": None},  # type: ignore[dict-item]
            )

    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError, match="title must be a str"):
            build_fishbone(
                problem="P",
                categories=_CATEGORIES,
                title=99,  # type: ignore[arg-type]
            )

    def it_rejects_a_page_too_small_for_the_title_band(self):
        with pytest.raises(ValueError, match="too small for the title"):
            build_fishbone(
                problem="P",
                categories=_CATEGORIES,
                page_height=0.5,
            )

    def it_rejects_a_page_too_narrow_for_the_spine_and_problem(self):
        with pytest.raises(ValueError, match="too small to fit the spine"):
            build_fishbone(
                problem="P",
                categories=_CATEGORIES,
                page_width=2.0,
            )


# ---------------------------------------------------------------------------
# DescribeFishboneKitWiring — re-exports from the package namespace
# ---------------------------------------------------------------------------


class DescribeFishboneKitWiring:
    def it_re_exports_build_fishbone_from_the_kit_package(self):
        from vsdx.kit import build_fishbone as via_pkg
        from vsdx.kit.fishbone import build_fishbone as via_module

        assert via_pkg is via_module

    def it_re_exports_the_default_categories_constant(self):
        from vsdx.kit import FISHBONE_DEFAULT_CATEGORIES as via_pkg
        from vsdx.kit.fishbone import (
            FISHBONE_DEFAULT_CATEGORIES as via_module,
        )

        assert via_pkg is via_module

    def it_re_exports_the_branch_angle_constant(self):
        from vsdx.kit import FISHBONE_BRANCH_ANGLE_DEG as via_pkg
        from vsdx.kit.fishbone import (
            FISHBONE_BRANCH_ANGLE_DEG as via_module,
        )

        assert via_pkg == via_module
        # And the angle is consistent with the conventional 60° rib.
        assert math.isclose(via_pkg, 60.0)
