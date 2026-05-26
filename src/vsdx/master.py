"""``Master`` + ``Masters`` proxies.

A master is a reusable shape template stored in ``/visio/masters``.
0.1.0 ships a tiny catalog of built-in masters (Rectangle, Ellipse,
Triangle, Dynamic connector) and supports *instantiating* them on a
page — full custom master creation lands in 0.2.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Optional

from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shared import ParentedElementProxy, PartElementProxy

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.parts._stubs import MasterPart, MastersPart  # TODO(vsdx/track-2)


#: Names of the masters that are bundled / synthesised by default so
#: ``doc.pages[0].shapes.add_shape('Rectangle')`` just works without
#: the caller having to populate ``doc.masters``.
BUILT_IN_MASTER_NAMES: tuple[str, ...] = (
    VS_SHAPE_TYPE.RECTANGLE.value,
    VS_SHAPE_TYPE.ELLIPSE.value,
    VS_SHAPE_TYPE.TRIANGLE.value,
    VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value,
)


class Master(PartElementProxy):
    """A single master (reusable shape template).

    0.1.0 surface is deliberately shallow — ``name_u`` / ``base_id`` /
    ``unique_id`` readers and not much else. Shape authoring happens
    at the *page* level; masters exist here only to satisfy the
    ``<Shape Master="…">`` reference.
    """

    def __init__(self, master_part: "MasterPart", parent: "Masters") -> None:
        super().__init__(master_part.master_element, master_part)
        self._master_part = master_part
        self._parent = parent

    @property
    def name_u(self) -> Optional[str]:
        return self._element.get("NameU")

    @property
    def name(self) -> Optional[str]:
        return self._element.get("Name") or self._element.get("NameU")

    @property
    def base_id(self) -> Optional[str]:
        return self._element.get("BaseID")

    @property
    def unique_id(self) -> Optional[str]:
        return self._element.get("UniqueID")

    @property
    def master_id(self) -> Optional[str]:
        return self._element.get("ID")

    @property
    def part(self):  # type: ignore[override]
        return self._master_part

    # -- inheritance-chain support -------------------------------------

    @property
    def parent_master_ref(self) -> Optional[str]:
        """Raw ``@Master`` attribute on this master's index entry, or ``None``.

        When a master is itself derived from another master (``<Master
        Master="Parent">``), that pointer tells
        :attr:`~vsdx.shapes.base.Shape.master_chain` where to continue
        the walk. Per this library's convention the reference is a
        NameU string; a spec-conformant integer ID also works because
        the resolver falls back to ID-based lookup.

        .. versionadded:: 0.3.0
        """
        return self._element.get("Master")

    @property
    def _content_shape_element(self) -> Optional[Any]:
        """First ``<Shape>`` inside this master's ``<MasterContents>``.

        Master shape-sheet cells (``PinX``, ``Width``, geometry, text,
        …) live on this shape. Returns ``None`` when the master part
        carries no shapes, or is an index-only entry with no contents
        part wired through yet.

        Private helper used by the inheritance resolver.
        """
        part = self._master_part
        contents = getattr(part, "element", None) if part is not None else None
        if contents is None:
            return None
        shapes_el = getattr(contents, "shapes", None)
        if shapes_el is None:
            return None
        shape_lst = getattr(shapes_el, "shape_lst", None)
        if not shape_lst:
            return None
        return shape_lst[0]

    def get_cell(self, name: str) -> Optional[Any]:
        """Return the master's ``<Cell N=name>`` proxy, or ``None``.

        Consults first the master-index ``<PageSheet>`` (Visio's home
        for default shape cells on a master) and then the first shape
        inside ``<MasterContents>``. The proxy layer's
        :meth:`~vsdx.shapes.base.Shape.effective_prop` calls this on
        every master in the chain.

        .. versionadded:: 0.3.0
        """
        page_sheet = getattr(self._element, "pageSheet", None)
        if page_sheet is not None:
            for cell in getattr(page_sheet, "cell_lst", []):
                if cell.get("N") == name:
                    return cell
        content_shape = self._content_shape_element
        if content_shape is not None:
            for cell in getattr(content_shape, "cell_lst", []):
                if cell.get("N") == name:
                    return cell
        return None

    @property
    def text(self) -> Optional[str]:
        """Text carried by the master's first shape, or ``None``.

        Read only — masters are templates, so setting text belongs on
        the instance. Used by :attr:`~vsdx.shapes.base.Shape.effective_text`
        when the instance shape itself carries no text.

        .. versionadded:: 0.3.0
        """
        content_shape = self._content_shape_element
        if content_shape is None:
            return None
        text_el = getattr(content_shape, "text", None)
        if text_el is None:
            return None
        return text_el.text or None

    # -- build-time shape authoring -------------------------------------

    @property
    def shapes(self) -> "MasterShapeTree":
        """Shape-tree wrapper over this master's ``<MasterContents>``.

        Mirrors :attr:`~vsdx.page.Page.shapes` so callers can author
        masters with the familiar ``add_shape("Rectangle", at=(0,0),
        size=(1,1))`` keyword form. The thin :class:`MasterShapeTree`
        wrapper delegates to :meth:`add_shape` underneath, allocating
        a fresh shape ID per call.

        Example::

            stencil = vsdx.Stencil.new()
            m = stencil.masters.add_master("MyBox")
            m.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))

        .. versionadded:: 0.3.0
        """
        return MasterShapeTree(self)

    def add_shape(
        self,
        name: str,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> Any:
        """Append a ``<Shape>`` to this master's ``<MasterContents>``.

        Build-time complement of :meth:`~vsdx.shapes.shapetree.ShapeTree.add_shape`
        — where that method drops a shape on a page, this one stamps a
        shape into the master's own shape tree so it appears every time
        the master is instantiated.

        :param name: NameU / Name attribute for the shape (Visio's
            master-contents shapes are usually named after the master,
            e.g. ``"Sheet.1"``; *name* is written into both ``@Name``
            and ``@NameU``).
        :param x: PinX in inches.
        :param y: PinY in inches.
        :param width: Width in inches.
        :param height: Height in inches.
        :returns: the raw ``CT_Shape`` element. The caller can stash it
            for further cell customisation; the element is live-bound
            to the master part's XML tree.

        .. versionadded:: 0.3.0
        """
        # -- local import: avoid cycle with vsdx.shapes → vsdx.master --
        from vsdx.shapes.base import _fmt_num

        part = self._master_part
        contents = part.element
        shape_el = contents.shapes_element.add_shape()
        shape_el.set("Name", name)
        shape_el.set("NameU", name)
        shape_el.shape_id = part.allocate_shape_id()

        # Stamp the four geometry cells. Use the named-cell convention
        # the proxy uses everywhere else — create ``<Cell N=... V=...
        # U="IN"/>`` children on the shape element, ordered PinX /
        # PinY / Width / Height to match what Visio desktop emits.
        for cell_name, value in (
            ("PinX", x),
            ("PinY", y),
            ("Width", width),
            ("Height", height),
        ):
            cell = shape_el.get_or_add_cell(cell_name)
            cell.set("N", cell_name)
            cell.set("V", _fmt_num(float(value)))
            cell.set("U", "IN")
        return shape_el


class MasterShapeTree:
    """Thin authoring wrapper over a :class:`Master`'s ``<MasterContents>``.

    Mirrors :class:`vsdx.shapes.shapetree.ShapeTree`'s ``add_shape``
    keyword form so the stencil-authoring surface reads symmetrically
    with the page-authoring surface. The wrapper delegates back to
    :meth:`Master.add_shape` for the heavy lifting; iteration / index
    access yield the raw ``CT_Shape`` elements (the master-shape proxy
    layer is intentionally shallow at 0.3.0 — masters are templates,
    not fully-typed editable surfaces).

    .. versionadded:: 0.3.0
    """

    def __init__(self, master: "Master") -> None:
        self._master = master

    def add_shape(
        self,
        shape_type,
        at: tuple[float, float] = (0.0, 0.0),
        size: tuple[float, float] = (1.0, 1.0),
    ) -> Any:
        """Stamp a built-in autoshape into the master's contents.

        :param shape_type: a :class:`~vsdx.enum.shapes.VS_SHAPE_TYPE`
            member or a NameU string. The string is written into both
            the shape's ``@Name`` and ``@NameU``.
        :param at: ``(pin_x, pin_y)`` in inches.
        :param size: ``(width, height)`` in inches.
        :returns: the raw ``CT_Shape`` element.
        """
        name = shape_type.value if hasattr(shape_type, "value") else str(shape_type)
        x, y = float(at[0]), float(at[1])
        w, h = float(size[0]), float(size[1])
        return self._master.add_shape(name, x=x, y=y, width=w, height=h)

    def __iter__(self):
        contents = self._master._master_part.element
        shapes_el = getattr(contents, "shapes", None)
        if shapes_el is None:
            return iter(())
        return iter(getattr(shapes_el, "shape_lst", []))

    def __len__(self) -> int:
        contents = self._master._master_part.element
        shapes_el = getattr(contents, "shapes", None)
        if shapes_el is None:
            return 0
        return len(getattr(shapes_el, "shape_lst", []))


class Masters(ParentedElementProxy):
    """Collection of masters on a :class:`~vsdx.document.VisioDocument`.

    Supports ``__iter__`` / ``__len__`` / ``__getitem__`` *and*
    dictionary-style lookup by NameU (``masters["Rectangle"]``). The
    latter mirrors ``dave-howard/vsdx``'s ``master_index`` idiom and
    is what the shape-tree uses when instantiating a shape by
    master-reference.
    """

    def __init__(self, masters_part: "MastersPart", parent: "VisioDocument") -> None:
        super().__init__(masters_part.element, parent)
        self._masters_part = masters_part
        self._master_cache: list[Master] = []
        self._rebuild_cache()

    # -- container ------------------------------------------------------

    def __iter__(self) -> Iterator[Master]:
        return iter(self._master_cache)

    def __len__(self) -> int:
        return len(self._master_cache)

    def __getitem__(self, key) -> Master:  # type: ignore[no-untyped-def]
        if isinstance(key, int):
            return self._master_cache[key]
        # Dict-style lookup by NameU.
        for m in self._master_cache:
            if m.name_u == key:
                return m
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        for m in self._master_cache:
            if m.name_u == key:
                return True
        return False

    def resolve(self, ref: Optional[str]) -> Optional[Master]:
        """Look up a master by NameU *or* by numeric ``@ID``.

        Handles both this library's NameU-based master references
        (authored via ``add_shape(master_name_u=...)``) and spec-literal
        integer IDs seen in Visio-desktop-authored packages. Returns
        ``None`` when *ref* is falsy or does not resolve — callers
        detect "no master chain" by the ``None`` return.

        .. versionadded:: 0.3.0
        """
        if ref is None or ref == "":
            return None
        # First, NameU match (this library's authoring convention).
        for m in self._master_cache:
            if m.name_u == ref:
                return m
        # Then, numeric ``@ID`` match (ECMA-literal convention).
        for m in self._master_cache:
            if m.master_id == ref:
                return m
        return None

    def by_name(self, name: str) -> Optional[Master]:
        """Return the master whose NameU matches *name*, or ``None``.

        Convenience wrapper around the dict-style ``__getitem__`` that
        avoids the ``KeyError`` when callers want a presence check
        rather than a lookup. Mirrors ``pptx.SlideLayouts.by_name``.

        :param name: NameU to match.
        :returns: the matching :class:`Master` or ``None`` when no
            master with that NameU exists.

        .. versionadded:: 0.3.0
        """
        for m in self._master_cache:
            if m.name_u == name:
                return m
        return None

    # -- authoring ------------------------------------------------------

    def add_master(
        self,
        name_u: Optional[str] = None,
        base_id: Optional[str] = None,
        unique_id: Optional[str] = None,
        *,
        name: Optional[str] = None,
    ) -> Master:
        """Add a new master and return its proxy.

        :param name_u: NameU (and Name) for the new master. Positional
            for back-compat with the 0.1.0 ``add_master("Foo")`` form.
        :param base_id: optional ``@BaseID`` GUID (``"{...}"``). When
            supplied, identifies the master's lineage so that copies of
            this master in other documents are recognised as siblings.
            ``None`` leaves the attribute off. ``[Added in 0.3.0]``
        :param unique_id: optional ``@UniqueID`` GUID. When supplied,
            stamped on the index entry; useful when reproducing a
            master from an external stencil. ``None`` leaves the
            attribute off. ``[Added in 0.3.0]``
        :param name: keyword-only alias for *name_u* — the stencil-
            authoring brief uses ``add_master(name="MyBox")`` so we
            accept either spelling. Supplying both raises
            :class:`TypeError`. ``[Added in 0.3.0]``
        """
        if name is not None:
            if name_u is not None:
                raise TypeError(
                    "add_master() received both 'name_u' and 'name' — "
                    "they're aliases; pass exactly one"
                )
            name_u = name
        if name_u is None:
            raise TypeError(
                "add_master() missing required argument 'name_u' (or 'name')"
            )
        mp = self._masters_part.add_master_part(name_u)
        master = Master(mp, self)
        if base_id is not None:
            master._element.set("BaseID", base_id)
        if unique_id is not None:
            master._element.set("UniqueID", unique_id)
        self._master_cache.append(master)
        return master

    def ensure(self, name_u: str) -> Master:
        """Return the master with *name_u*, creating it if absent.

        Used by the shape-tree during ``add_shape`` to make sure every
        referenced master is present in the index. The convention
        matches the "register-on-use" pattern python-pptx uses for
        chart styles.
        """
        for m in self._master_cache:
            if m.name_u == name_u:
                return m
        return self.add_master(name_u)

    # -- internal -------------------------------------------------------

    def _rebuild_cache(self) -> None:
        self._master_cache = [
            Master(mp, self) for mp in getattr(self._masters_part, "_master_parts", [])
        ]


__all__ = ["BUILT_IN_MASTER_NAMES", "Master", "MasterShapeTree", "Masters"]
