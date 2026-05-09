"""Unit tests for the 0.2.0 ``GroupShape`` proxy + group / ungroup ops.

The round-trip invariant under test is coordinate relativity:
``group()`` rewrites member PinX/PinY to group-local; ``ungroup()``
hoists them back. The pre/post pair must be idempotent for a single
pair of calls, with one round-trip of float rounding acceptable.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.shapes.group import _shape_bounding_box, GroupShape


def _page_with_three_rectangles():
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Page-1")
    r1 = page.shapes.add_shape(
        vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1), size=(2, 1)
    )
    r2 = page.shapes.add_shape(
        vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(4, 2), size=(1, 1)
    )
    r3 = page.shapes.add_shape(
        vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(2, 5), size=(1, 2)
    )
    return doc, page, r1, r2, r3


class DescribeBoundingBox:
    def it_covers_a_single_shape(self) -> None:
        _, _, r1, _, _ = _page_with_three_rectangles()
        x0, y0, w, h = _shape_bounding_box([r1])
        # centre (1,1), size (2,1) → bbox (0, 0.5)..(2, 1.5)
        assert abs(x0 - 0.0) < 1e-6
        assert abs(y0 - 0.5) < 1e-6
        assert abs(w - 2.0) < 1e-6
        assert abs(h - 1.0) < 1e-6

    def it_covers_all_shapes(self) -> None:
        _, _, r1, r2, r3 = _page_with_three_rectangles()
        x0, y0, w, h = _shape_bounding_box([r1, r2, r3])
        # r1: (0, 0.5)..(2, 1.5); r2: (3.5, 1.5)..(4.5, 2.5);
        # r3: (1.5, 4)..(2.5, 6)
        assert abs(x0 - 0.0) < 1e-6
        assert abs(y0 - 0.5) < 1e-6
        assert abs(x0 + w - 4.5) < 1e-6
        assert abs(y0 + h - 6.0) < 1e-6


class DescribeShapesGroupOp:
    def it_creates_a_group_shape(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        group = page.shapes.group([r1, r2, r3])
        assert isinstance(group, vsdx.GroupShape)
        assert group.shape_type == "Group"

    def it_removes_members_from_page_shape_tree(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        before = len(page.shapes)
        page.shapes.group([r1, r2, r3])
        # The three members are no longer top-level — only the group
        # itself remains (net decrease of 2).
        assert len(page.shapes) == before - 2

    def it_sizes_the_group_to_the_bounding_box(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        group = page.shapes.group([r1, r2, r3])
        # bbox is 4.5 wide, 5.5 tall.
        assert abs(float(group.width) - 4.5) < 1e-3
        assert abs(float(group.height) - 5.5) < 1e-3

    def it_rewrites_members_to_group_local_coordinates(self) -> None:
        # r1 at (1, 1) in page; bbox top-left is (0, 0.5) so r1's
        # group-local pin is (1, 0.5).
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        group = page.shapes.group([r1, r2, r3])
        member = group.member_shapes[0]
        assert abs(float(member.pin_x) - 1.0) < 1e-3
        assert abs(float(member.pin_y) - 0.5) < 1e-3

    def it_refuses_to_group_an_empty_shape_list(self) -> None:
        _, page, _, _, _ = _page_with_three_rectangles()
        with pytest.raises(ValueError):
            page.shapes.group([])

    def it_allocates_a_fresh_shape_id_for_the_group(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        group = page.shapes.group([r1, r2, r3])
        assert group.shape_id > max(r1.shape_id, r2.shape_id, r3.shape_id)


class DescribeGroupShapeUngroup:
    def it_hoists_members_back_to_page_scope(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        group = page.shapes.group([r1, r2, r3])
        assert len(page.shapes) == 1  # just the group
        members = group.ungroup()
        # Now the page should have 3 shapes again.
        assert len(page.shapes) == 3
        assert len(members) == 3

    def it_restores_original_page_coordinates(self) -> None:
        # Round-trip: page coords -> group-local -> page coords
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        orig_r1_pin = (float(r1.pin_x), float(r1.pin_y))
        group = page.shapes.group([r1, r2, r3])
        group.ungroup()
        # r1 should be back at its original coordinates (one round-trip
        # through float is rounding-acceptable to ~1e-6 inches).
        page_shapes = list(page.shapes)
        r1_again = next(s for s in page_shapes if s.shape_id == r1.shape_id)
        assert abs(float(r1_again.pin_x) - orig_r1_pin[0]) < 1e-3
        assert abs(float(r1_again.pin_y) - orig_r1_pin[1]) < 1e-3

    def it_removes_the_group_shape_element(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        group = page.shapes.group([r1, r2, r3])
        group.ungroup()
        for shape in page.shapes:
            assert shape.shape_type != "Group"


class DescribeUngroupOnNonGroup:
    def it_refuses_to_ungroup_a_rectangle(self) -> None:
        _, page, r1, _, _ = _page_with_three_rectangles()
        with pytest.raises(TypeError):
            r1.ungroup()


class DescribeGroupProxyDispatch:
    def it_returns_a_groupshape_from_shapetree_iteration(self) -> None:
        _, page, r1, r2, r3 = _page_with_three_rectangles()
        page.shapes.group([r1, r2, r3])
        shapes = list(page.shapes)
        assert isinstance(shapes[0], GroupShape)
