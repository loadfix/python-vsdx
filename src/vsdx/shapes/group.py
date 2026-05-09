"""``GroupShape`` — user-authored group shapes (``<Shape Type="Group">``).

A Visio group shape carries its own ``PinX`` / ``PinY`` / ``Width`` /
``Height`` pin-and-size cells and wraps its members inside a nested
``<Shapes>`` child. Member PinX/PinY values are **relative to the
group's top-left** (not the page), so group / ungroup operations must
convert coordinates in both directions.

The 0.1.0 oxml layer already supports the recursive nesting — this
module adds the proxy-layer authoring surface on top per scoping-doc
§4.2.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, List, Sequence

from vsdx.enum.cells import ST_Unit
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shapes.base import (
    Shape,
    TextShape,
    _cell_float,
    _set_cell_float,
)

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Shape  # TODO(vsdx/track-1)
    from vsdx.shapes.shapetree import ShapeTree

__all__ = ["GroupShape"]


# ---------------------------------------------------------------------------
# Coordinate conversion helpers — pure functions so they round-trip
# under fixture regressions without proxy instantiation.
# ---------------------------------------------------------------------------


def _shape_bounding_box(shapes: Sequence[Shape]) -> "tuple[float, float, float, float]":
    """Return ``(min_x, min_y, width, height)`` covering every *shape*.

    Each shape's ``pin`` is its centre and ``width/height`` cover full
    extent, so the bounding box spans from ``pin - size/2`` to
    ``pin + size/2``. Used to size a newly-minted group shape around
    its member shapes.
    """
    if not shapes:
        return (0.0, 0.0, 0.0, 0.0)
    xs_min: List[float] = []
    ys_min: List[float] = []
    xs_max: List[float] = []
    ys_max: List[float] = []
    for shape in shapes:
        # ``shape.pin_x`` / ``shape.width`` are :class:`vsdx.util.Inches`
        # subclasses of ``float`` that already report their value in
        # inches — no EMU conversion required. (The ``.emu`` attribute
        # exists for interoperation with packages that use the shared
        # EMU-denominated :class:`ooxml_opc.Length`.)
        px = float(shape.pin_x)
        py = float(shape.pin_y)
        w = float(shape.width)
        h = float(shape.height)
        xs_min.append(px - w / 2.0)
        ys_min.append(py - h / 2.0)
        xs_max.append(px + w / 2.0)
        ys_max.append(py + h / 2.0)
    x0, y0 = min(xs_min), min(ys_min)
    x1, y1 = max(xs_max), max(ys_max)
    return (x0, y0, x1 - x0, y1 - y0)


def _to_group_local(
    shape: Shape,
    group_origin_x: float,
    group_origin_y: float,
) -> None:
    """Convert *shape*'s page-scoped PinX/PinY to group-local.

    Subtracts the group's top-left corner. Called when a shape is
    aggregated into a newly-authored group.
    """
    px = float(shape.pin_x)
    py = float(shape.pin_y)
    _set_cell_float(
        shape._element, "PinX", px - group_origin_x, ST_Unit.INCHES.value
    )
    _set_cell_float(
        shape._element, "PinY", py - group_origin_y, ST_Unit.INCHES.value
    )


def _to_page_coords(
    shape: Shape,
    group_origin_x: float,
    group_origin_y: float,
) -> None:
    """Convert *shape*'s group-local PinX/PinY back to page-scoped."""
    px = float(shape.pin_x)
    py = float(shape.pin_y)
    _set_cell_float(
        shape._element, "PinX", px + group_origin_x, ST_Unit.INCHES.value
    )
    _set_cell_float(
        shape._element, "PinY", py + group_origin_y, ST_Unit.INCHES.value
    )


# ---------------------------------------------------------------------------
# GroupShape proxy — ``<Shape Type="Group">`` with nested <Shapes>.
# ---------------------------------------------------------------------------


class GroupShape(TextShape):
    """A user-authored group shape.

    Inherits from :class:`~vsdx.shapes.base.TextShape` so groups can
    carry optional group-level text (rare but legal per MS Learn).
    The defining feature is the nested ``<Shapes>`` child — iterate
    :attr:`member_shapes` to walk the group contents.

    .. versionadded:: 0.2.0
    """

    def __init__(self, shape_element: "CT_Shape", parent: "ShapeTree") -> None:
        super().__init__(shape_element, parent)

    # -- members --------------------------------------------------------

    @property
    def member_shapes(self) -> List[Shape]:
        """The shapes inside this group, each wrapped in a proxy.

        Returns an empty list when the group is freshly created; the
        list updates as :meth:`add_member` / :meth:`ungroup` run.

        .. versionadded:: 0.2.0
        """
        shapes_el = self._element.shapes
        if shapes_el is None:
            return []
        # Reuse the ShapeTree proxy-dispatch so autoshape subclasses
        # (Rectangle / Ellipse / Triangle) still resolve correctly for
        # shapes inside a group.
        tree = self._parent
        return [tree._proxy_for(el) for el in shapes_el.shape_lst]

    def __iter__(self) -> Iterator[Shape]:
        return iter(self.member_shapes)

    def __len__(self) -> int:
        shapes_el = self._element.shapes
        return 0 if shapes_el is None else len(shapes_el.shape_lst)

    # -- ungroup --------------------------------------------------------

    def ungroup(self) -> List[Shape]:
        """Disband the group and hoist each member back to page scope.

        Converts each member's PinX / PinY back to page-scoped
        coordinates, detaches the nested ``<Shapes>`` container, and
        removes the ``<Shape Type="Group">`` wrapper from the page.
        Returns the list of member shapes (now with page-scoped
        coordinates and reparented ``<Shape>`` elements).

        .. versionadded:: 0.2.0
        """
        origin_x = float(self.pin_x) - float(self.width) / 2.0
        origin_y = float(self.pin_y) - float(self.height) / 2.0
        shapes_el = self._element.shapes
        members: List[Shape] = []
        if shapes_el is not None:
            tree = self._parent
            # Collect members first; the reparent mutates the iterator.
            child_els = list(shapes_el.shape_lst)
            # The group's owning <Shapes> element is the grandparent.
            # group self._element is <Shape Type="Group">; its parent is
            # the page's <Shapes>.
            page_shapes_parent = self._element.getparent()
            for child in child_els:
                # Convert child coordinates back to page-scope.
                proxy = tree._proxy_for(child)
                _to_page_coords(proxy, origin_x, origin_y)
                # Reparent the child under the page's <Shapes>.
                shapes_el.remove(child)
                if page_shapes_parent is not None:
                    page_shapes_parent.append(child)
                members.append(tree._proxy_for(child))
        # Remove the now-empty group element.
        parent_el = self._element.getparent()
        if parent_el is not None:
            parent_el.remove(self._element)
        return members


# ---------------------------------------------------------------------------
# ShapeTree.group — aggregate shapes into a new GroupShape
# ---------------------------------------------------------------------------


def group_shapes(
    tree: "ShapeTree", shapes: Sequence[Shape]
) -> GroupShape:
    """Aggregate *shapes* into a new :class:`GroupShape` and return it.

    Implementation of :meth:`~vsdx.shapes.shapetree.ShapeTree.group`.
    Lives in this module to keep the coordinate-conversion helpers
    co-located with the :class:`GroupShape` proxy.

    * Computes the bounding box of *shapes* — that's the group's
      page-scoped PinX / PinY / Width / Height.
    * Reparents each shape under the group's nested ``<Shapes>`` and
      rewrites its PinX / PinY to group-local coordinates.
    * Assigns a fresh page-scoped ``@ID`` to the group.

    .. versionadded:: 0.2.0
    """
    if not shapes:
        raise ValueError("group() requires at least one member shape")
    page_shapes = tree._element.shapes_element
    # Snapshot the bounding box before we mutate anything.
    x0, y0, w, h = _shape_bounding_box(shapes)
    # Create the group <Shape Type="Group">.
    group_el = page_shapes._add_shape()
    group_el.set("Type", VS_SHAPE_TYPE.GROUP.value)
    group_el.set("ID", str(tree._parent.next_shape_id()))
    # Nested <Shapes> for the group's children.
    nested = group_el.get_or_add_shapes()
    # Set group's own pin/size (pin is centre of bbox).
    _set_cell_float(
        group_el, "PinX", x0 + w / 2.0, ST_Unit.INCHES.value
    )
    _set_cell_float(
        group_el, "PinY", y0 + h / 2.0, ST_Unit.INCHES.value
    )
    _set_cell_float(group_el, "Width", w, ST_Unit.INCHES.value)
    _set_cell_float(group_el, "Height", h, ST_Unit.INCHES.value)
    # Reparent members (origin is bbox top-left).
    for shape in shapes:
        _to_group_local(shape, x0, y0)
        shape_el = shape._element
        shape_parent = shape_el.getparent()
        if shape_parent is not None:
            shape_parent.remove(shape_el)
        nested.append(shape_el)
    return GroupShape(group_el, tree)


# -- unused-import guard --
_ = _cell_float
