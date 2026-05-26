"""``ShapeTree`` — the ``shapes`` collection on a :class:`~vsdx.page.Page`.

Mirrors ``pptx.shapes.shapetree.SlideShapes`` in shape and spirit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional, Union

from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shapes.autoshape import (
    AUTOSHAPE_REGISTRY,
    Ellipse,
    Rectangle,
    Triangle,
    _BuiltInAutoShape,
    autoshape_cls_for,
)
from vsdx.shapes.base import Shape, TextShape
from vsdx.shapes.connector import Connector
from vsdx.shapes.group import GroupShape, group_shapes as _group_shapes_impl
from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_PageContents, CT_Shape  # TODO(vsdx/track-1)
    from vsdx.page import Page


# Coordinate-tuple type for ``at=`` / ``size=`` keyword arguments.
PointLike = Union[tuple[float, float], tuple[int, int]]


class ShapeTree(ParentedElementProxy):
    """Collection of shapes on a page.

    Iteration yields :class:`Shape` proxies in document order. Add
    shapes via :meth:`add_shape` / :meth:`add_connector` /
    :meth:`add_shape_from_master`.
    """

    _element: "CT_PageContents"

    def __init__(self, page_contents: "CT_PageContents", parent: "Page") -> None:
        super().__init__(page_contents, parent)

    # -- container ------------------------------------------------------

    def __iter__(self) -> Iterator[Shape]:
        for el in self._element.shapes_element.shape_lst:
            yield self._proxy_for(el)

    def __len__(self) -> int:
        return len(self._element.shapes_element.shape_lst)

    def __getitem__(self, idx: int) -> Shape:
        return self._proxy_for(self._element.shapes_element.shape_lst[idx])

    # -- authoring ------------------------------------------------------

    def add_shape(
        self,
        shape_type: Union[VS_SHAPE_TYPE, str],
        at: PointLike = (0.0, 0.0),
        size: PointLike = (1.0, 1.0),
        text: Optional[str] = None,
    ) -> _BuiltInAutoShape:
        """Add a built-in autoshape and return its proxy.

        :param shape_type: Either a :class:`VS_SHAPE_TYPE` member or the
            raw NameU string of a built-in master (``"Rectangle"``,
            ``"Ellipse"``, ``"Triangle"``).
        :param at: ``(pin_x, pin_y)`` tuple in inches — the shape's
            centre-pin position.
        :param size: ``(width, height)`` tuple in inches.
        :param text: optional initial text content.
        """
        name_u = shape_type.value if isinstance(shape_type, VS_SHAPE_TYPE) else str(shape_type)
        shape_el = self._element.shapes_element.add_shape(master_name_u=name_u)

        # Allocate a shape ID via the owning page.
        page = self._parent
        shape_el.shape_id = page.next_shape_id()

        cls = autoshape_cls_for(name_u)
        proxy: _BuiltInAutoShape = cls(shape_el, self)
        pin_x, pin_y = float(at[0]), float(at[1])
        w, h = float(size[0]), float(size[1])
        proxy.set_geometry(pin_x, pin_y, w, h)
        if text is not None:
            proxy.text = text
        return proxy

    def add_shape_from_master(
        self,
        master_name_u: str,
        at: PointLike = (0.0, 0.0),
        size: Optional[PointLike] = None,
    ) -> Shape:
        """Add a shape that references an arbitrary master by NameU.

        The master must already exist in the document's masters
        collection — use ``doc.masters.add_master(name_u)`` first if
        it's not one of the built-ins.
        """
        shape_el = self._element.shapes_element.add_shape(master_name_u=master_name_u)
        page = self._parent
        shape_el.shape_id = page.next_shape_id()

        proxy = TextShape(shape_el, self)
        pin_x, pin_y = float(at[0]), float(at[1])
        proxy.pin_x = pin_x
        proxy.pin_y = pin_y
        if size is not None:
            proxy.width = float(size[0])
            proxy.height = float(size[1])
        return proxy

    def add_master_instance(
        self,
        master: "object",
        at: PointLike = (0.0, 0.0),
        size: Optional[PointLike] = None,
    ) -> Shape:
        """Drop an instance of *master* on this page.

        *master* may be a :class:`~vsdx.master.Master` from this
        document **or from any other** :class:`~vsdx.document.VisioDocument`
        / :class:`~vsdx.stencil.Stencil`. If the master does not yet
        exist in this document's :class:`~vsdx.master.Masters`
        collection (matched by ``@BaseID`` when supplied, then by
        NameU as a fallback), it is *copied* into the destination
        first — its index entry attributes (``Name``, ``NameU``,
        ``BaseID``, ``UniqueID`` if present), its master-contents
        part bytes (the ``<MasterContents>`` shape tree), and its
        ``<PageSheet>`` cells from the index entry. A fresh master
        ``@ID`` is allocated by the destination's
        :meth:`~vsdx.parts.master.MastersPart.add_master_part` so
        the import does not collide with existing IDs.

        After registration, a new ``<Shape>`` is dropped on this page
        with ``@Master=<NameU>`` and *at* / *size* applied.

        :param master: a :class:`~vsdx.master.Master` proxy.
        :param at: ``(pin_x, pin_y)`` in inches.
        :param size: optional ``(width, height)``; when ``None`` the
            instance inherits its size from the master's PageSheet.
        :returns: the newly-dropped :class:`Shape` proxy.

        .. versionadded:: 0.3.0
        """
        # -- local import to dodge cycle ----------------------------------
        from vsdx.master import Master

        if not isinstance(master, Master):
            raise TypeError(
                "add_master_instance expected a vsdx.master.Master, got %r"
                % type(master).__name__
            )

        page = self._parent
        # Walk up to the owning VisioDocument via Page → Pages → doc.
        # ``Page._parent`` is the Pages collection, whose ``_parent``
        # is the VisioDocument.
        dest_doc = page._parent._parent  # type: ignore[attr-defined]
        dest_masters = dest_doc.masters

        # 1. Find or import the master in destination masters.
        local = self._find_local_master(dest_masters, master)
        if local is None:
            local = self._import_master(dest_masters, master)

        # 2. Drop the shape referencing the (now-local) master.
        return self.add_shape_from_master(local.name_u, at=at, size=size)

    @staticmethod
    def _find_local_master(dest_masters, source_master):
        """Return the destination master matching *source_master*, or None.

        Match priority: ``@BaseID`` (if both have one) → NameU.
        ``@BaseID`` is the canonical lineage marker so we prefer it
        when available; NameU is the friendly fallback.
        """
        src_base_id = source_master.base_id
        if src_base_id:
            for m in dest_masters:
                if m.base_id == src_base_id:
                    return m
        return dest_masters.by_name(source_master.name_u)

    @staticmethod
    def _import_master(dest_masters, source_master):
        """Copy *source_master* into *dest_masters*.

        Three coordinated copies:
        * the ``<Master>`` index entry's optional attributes
          (``BaseID`` / ``UniqueID`` / ``MasterType`` / ``Hidden`` /
          ``IconSize`` / ``PatternFlags`` / ``Prompt`` / ``AlignName``);
        * the ``<PageSheet>`` child carrying default-cell data;
        * the master-contents part's root element (``<MasterContents>``)
          — deep-cloned so the destination has its own tree, not a
          live reference into the source document's parts graph.
        """
        from copy import deepcopy

        new_master = dest_masters.add_master(
            source_master.name_u,
            base_id=source_master.base_id,
            unique_id=source_master.unique_id,
        )

        # -- propagate index-entry attributes --
        src_index_el = source_master._element  # noqa: SLF001
        for attr in (
            "MasterType",
            "Hidden",
            "MatchByName",
            "IconSize",
            "PatternFlags",
            "Prompt",
            "AlignName",
            "IconUpdate",
        ):
            v = src_index_el.get(attr)
            if v is not None:
                new_master._element.set(attr, v)

        # -- copy the <PageSheet> default-cells from the index entry --
        src_page_sheet = getattr(src_index_el, "pageSheet", None)
        if src_page_sheet is not None:
            cloned_ps = deepcopy(src_page_sheet)
            # Replace whatever PageSheet exists on the new master entry.
            existing_ps = getattr(new_master._element, "pageSheet", None)
            if existing_ps is not None:
                new_master._element.remove(existing_ps)
            new_master._element.append(cloned_ps)

        # -- copy the <Icon> if present --
        src_icon = getattr(src_index_el, "icon", None)
        if src_icon is not None:
            new_master._element.append(deepcopy(src_icon))

        # -- copy the master-contents shape tree --
        src_contents_part = source_master._master_part  # noqa: SLF001
        src_contents_el = src_contents_part.element
        # Replace the destination master-contents element wholesale.
        cloned_contents = deepcopy(src_contents_el)
        new_master._master_part._element = cloned_contents  # noqa: SLF001

        return new_master

    def add_connector(
        self,
        from_shape: Shape,
        to_shape: Shape,
    ) -> Connector:
        """Add a dynamic connector between *from_shape* and *to_shape*.

        Creates the connector ``<Shape>`` on the page, sets its
        ``BeginX`` / ``EndX`` / ``BeginY`` / ``EndY`` cells to the two
        anchor-shape pins, and adds two ``<Connect>`` entries to the
        page's ``<Connects>`` element.
        """
        shape_el = self._element.shapes_element.add_shape(
            master_name_u=VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value
        )
        page = self._parent
        shape_el.shape_id = page.next_shape_id()

        conn = Connector(shape_el, self)
        conn._anchor_to(from_shape, to_shape)

        connects = self._element.connects_element
        connects.add_connect(
            from_sheet=str(conn.shape_id),
            to_sheet=str(from_shape.shape_id),
            from_cell="BeginX",
            to_cell="PinX",
        )
        connects.add_connect(
            from_sheet=str(conn.shape_id),
            to_sheet=str(to_shape.shape_id),
            from_cell="EndX",
            to_cell="PinX",
        )
        return conn

    def group(self, shapes: "list[Shape]") -> GroupShape:
        """Aggregate *shapes* into a new :class:`GroupShape`.

        The returned group carries a page-scoped PinX / PinY that is
        the centre of the bounding box of *shapes*; each member's
        PinX / PinY is rewritten to group-local coordinates so a
        Visio-desktop re-open sees the members at their original
        positions.

        Every shape in *shapes* must currently belong to this tree
        (it is not validated that membership — a future 0.2.x may
        add the guard).

        .. versionadded:: 0.2.0
        """
        return _group_shapes_impl(self, shapes)

    # -- helpers --------------------------------------------------------

    def _proxy_for(self, shape_el: "CT_Shape") -> Shape:
        """Return the best-fit :class:`Shape` proxy subclass for *shape_el*."""
        # Group shapes are detected by ``@Type="Group"`` — they may or
        # may not carry a ``@Master`` attribute (user-authored groups
        # typically don't; master-instance groups do).
        if shape_el.get("Type") == VS_SHAPE_TYPE.GROUP.value:
            return GroupShape(shape_el, self)
        name_u = shape_el.get("Master") or ""
        if name_u == VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value:
            return Connector(shape_el, self)
        if name_u in AUTOSHAPE_REGISTRY:
            return AUTOSHAPE_REGISTRY[name_u](shape_el, self)
        return TextShape(shape_el, self)


__all__ = ["ShapeTree"]
