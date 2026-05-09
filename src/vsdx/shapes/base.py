"""Base classes for the vsdx shape hierarchy.

``Shape`` wraps the generic Visio ``<Shape>`` element. Named-cell
access (``.pin_x``, ``.width``, ``.line_weight``, ...) is implemented
here as lookups into the shape's direct ``<Cell N="…">`` children
because, unlike DrawingML's one-element-per-property model, Visio
stores everything on a generic cell element distinguished by its
``@N`` attribute.

``TextShape`` adds ``.text`` / ``.text_frame`` accessors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from vsdx.enum.cells import ST_Unit
from vsdx.shared import ParentedElementProxy
from vsdx.text import TextFrame
from vsdx.util import Inches, Length

if TYPE_CHECKING:
    from vsdx.geometry import Geometries, Geometry
    from vsdx.hyperlinks import HyperlinkCollection
    from vsdx.oxml._stubs import CT_Cell, CT_Shape  # TODO(vsdx/track-1)
    from vsdx.shape_data import ShapeData
    from vsdx.shapes.shapetree import ShapeTree


# Named-cell accessor helpers ------------------------------------------------


def _cell_float(shape_el: "CT_Shape", name: str) -> Optional[float]:
    """Return the float value of ``<Cell N=name>`` or ``None`` if absent.

    Walks the xmlchemy-generated ``cell_lst`` so namespace-qualified
    ``{vsdx:}Cell`` children match. An unqualified ``findall("Cell")``
    returns nothing on a parsed Visio tree because every element lives
    under the default Visio namespace.
    """
    for cell in shape_el.cell_lst:
        if cell.get("N") == name:
            v = cell.get("V")
            if v is None or v == "":
                return None
            try:
                return float(v)
            except ValueError:
                return None
    return None


def _set_cell_float(
    shape_el: "CT_Shape", name: str, value: Optional[float], unit: str = "IN"
) -> None:
    """Create-or-update ``<Cell N=name V=value U=unit>`` on *shape_el*."""
    cell = shape_el.get_or_add_cell(name)
    if value is None:
        cell.attrib.pop("V", None)
        cell.attrib.pop("U", None)
        return
    cell.set("V", _fmt_num(value))
    cell.set("U", unit)


def _fmt_num(v: float) -> str:
    """Format a float the way Visio emits it — trim trailing zeros."""
    if v == int(v):
        return str(int(v))
    return ("%f" % v).rstrip("0").rstrip(".")


class Shape(ParentedElementProxy):
    """Base class for every shape on a page.

    Carries the named-cell convenience accessors that every concrete
    shape subclass inherits unchanged. Geometry cells (``PinX``,
    ``PinY``, ``Width``, ``Height``, ``Angle``) default to inches; line
    / fill cells carry unit-less values because they're colour indexes
    or weights.
    """

    _element: "CT_Shape"

    def __init__(self, shape_element: "CT_Shape", parent: "ShapeTree") -> None:
        super().__init__(shape_element, parent)

    # -- identity -------------------------------------------------------

    @property
    def shape_id(self) -> int:
        """The shape's unique ID within its page."""
        raw = self._element.shape_id
        return int(raw) if raw is not None else 0

    @property
    def name(self) -> Optional[str]:
        """The shape's display name (``@Name`` attribute)."""
        return self._element.get("Name") or self._element.get("NameU")

    @name.setter
    def name(self, value: str) -> None:
        self._element.set("Name", value)
        self._element.set("NameU", value)

    @property
    def master_name_u(self) -> Optional[str]:
        """The NameU of the master this shape was instantiated from, or None."""
        return self._element.get("Master") or self._element.get("MasterShape")

    @property
    def shape_type(self) -> Optional[str]:
        return self._element.get("Type")

    # -- position & size (all in inches via Length) ---------------------

    @property
    def pin_x(self) -> Length:
        """Pin X — horizontal location of the shape's pin, in inches."""
        return Inches(_cell_float(self._element, "PinX") or 0.0)

    @pin_x.setter
    def pin_x(self, value: Any) -> None:
        _set_cell_float(self._element, "PinX", float(value), ST_Unit.INCHES.value)

    @property
    def pin_y(self) -> Length:
        return Inches(_cell_float(self._element, "PinY") or 0.0)

    @pin_y.setter
    def pin_y(self, value: Any) -> None:
        _set_cell_float(self._element, "PinY", float(value), ST_Unit.INCHES.value)

    @property
    def width(self) -> Length:
        return Inches(_cell_float(self._element, "Width") or 0.0)

    @width.setter
    def width(self, value: Any) -> None:
        _set_cell_float(self._element, "Width", float(value), ST_Unit.INCHES.value)

    @property
    def height(self) -> Length:
        return Inches(_cell_float(self._element, "Height") or 0.0)

    @height.setter
    def height(self, value: Any) -> None:
        _set_cell_float(self._element, "Height", float(value), ST_Unit.INCHES.value)

    @property
    def angle(self) -> float:
        """Rotation angle in radians (Visio's native unit for Angle)."""
        return _cell_float(self._element, "Angle") or 0.0

    @angle.setter
    def angle(self, value: float) -> None:
        _set_cell_float(self._element, "Angle", float(value), ST_Unit.RADIANS.value)

    # -- line / fill (unit-less cells) ----------------------------------

    @property
    def line_weight(self) -> Optional[float]:
        return _cell_float(self._element, "LineWeight")

    @line_weight.setter
    def line_weight(self, value: Optional[float]) -> None:
        if value is None:
            return
        _set_cell_float(self._element, "LineWeight", float(value), ST_Unit.POINTS.value)

    @property
    def line_color(self) -> Optional[str]:
        """Raw LineColor cell value (typically a theme color index or RGB)."""
        cell = self._get_cell("LineColor")
        return cell.get("V") if cell is not None else None

    @line_color.setter
    def line_color(self, value: Optional[str]) -> None:
        cell = self._element.get_or_add_cell("LineColor")
        if value is None:
            cell.attrib.pop("V", None)
        else:
            cell.set("V", str(value))

    @property
    def fill_foregnd(self) -> Optional[str]:
        cell = self._get_cell("FillForegnd")
        return cell.get("V") if cell is not None else None

    @fill_foregnd.setter
    def fill_foregnd(self, value: Optional[str]) -> None:
        cell = self._element.get_or_add_cell("FillForegnd")
        if value is None:
            cell.attrib.pop("V", None)
        else:
            cell.set("V", str(value))

    # -- bulk geometry setter -------------------------------------------

    def set_geometry(self, pin_x: float, pin_y: float, width: float, height: float) -> None:
        """Set PinX / PinY / Width / Height in one call. Values in inches."""
        self.pin_x = pin_x
        self.pin_y = pin_y
        self.width = width
        self.height = height

    # -- group / layers -------------------------------------------------

    def ungroup(self):
        """Ungroup a :class:`~vsdx.shapes.group.GroupShape`.

        Raises :class:`TypeError` on a non-group shape.  Present on the
        base class to give every shape a uniform call-site; actual
        behaviour is polymorphic via :class:`GroupShape.ungroup`.

        .. versionadded:: 0.2.0
        """
        raise TypeError(
            "ungroup() only supported on GroupShape (got %s)"
            % type(self).__name__
        )

    @property
    def layers(self) -> "list":
        """The :class:`~vsdx.layers.Layer` proxies this shape belongs to.

        Reads the shape's ``<Cell N="LayerMember" V="…">`` and resolves
        each index against the owning page's layer section. Returns an
        empty list when the shape has no ``LayerMember`` cell.

        .. versionadded:: 0.2.0
        """
        from vsdx.layers import _shape_layers_proxy
        from vsdx.page import Page
        from vsdx.shapes.shapetree import ShapeTree

        # Walk up to the owning Page proxy. ShapeTree._parent is Page.
        parent = self._parent
        if isinstance(parent, ShapeTree):
            page = parent._parent
        elif isinstance(parent, Page):
            page = parent
        else:
            # Shapes inside a GroupShape use the group as parent; climb.
            climbing = parent
            while climbing is not None and not isinstance(climbing, Page):
                climbing = getattr(climbing, "_parent", None)
            page = climbing
        if page is None:
            return []
        return _shape_layers_proxy(self, page)

    def set_layers(self, layers) -> None:
        """Replace this shape's layer membership with *layers*.

        :param layers: iterable of :class:`~vsdx.layers.Layer` proxies.

        Writes a fresh ``<Cell N="LayerMember" V="0,2,5">`` on the
        shape (the scoping-doc round-trip invariant #3 requires
        ordering be callable-supplied; we serialise verbatim).

        .. versionadded:: 0.2.0
        """
        from vsdx.layers import _set_shape_layer_indices

        indices = [layer.index for layer in layers]
        _set_shape_layer_indices(self._element, indices)

    # -- data graphics --------------------------------------------------

    @property
    def data_graphic(self):
        """The :class:`~vsdx.data_graphics.DataGraphic` linked to this shape, or ``None``.

        Resolves ``<Cell N="DataGraphic" V="<id>">`` on the shape
        against the document's
        :attr:`~vsdx.document.VisioDocument.data_graphics` collection.
        Returns ``None`` when the cell is absent, empty, or points at
        an id no definition carries (a defensive guard against
        orphaned references in hand-edited packages).

        .. versionadded:: 0.2.0
        """
        from vsdx.data_graphics import _resolve_shape_data_graphic

        document = self._owning_document()
        if document is None:
            return None
        return _resolve_shape_data_graphic(self, document)

    @data_graphic.setter
    def data_graphic(self, value) -> None:
        """Link this shape to *value* (:class:`DataGraphic` or ``None``).

        Assigning ``None`` removes the ``<Cell N="DataGraphic">`` cell
        entirely — the shape reverts to plain rendering. Assigning a
        :class:`DataGraphic` proxy writes that graphic's ``id`` into
        the cell.

        .. versionadded:: 0.2.0
        """
        from vsdx.data_graphics import DataGraphic, _set_shape_data_graphic_id

        if value is None:
            _set_shape_data_graphic_id(self._element, None)
            return
        if not isinstance(value, DataGraphic):
            raise TypeError(
                "shape.data_graphic must be a DataGraphic or None, "
                "got %s" % type(value).__name__
            )
        _set_shape_data_graphic_id(self._element, value.id)

    def _owning_document(self):
        """Walk up the proxy tree to the :class:`VisioDocument` that owns
        this shape. Returns ``None`` when the shape was constructed
        without a parent chain (unit-test oxml-only fixtures).

        Private — exposed for :attr:`data_graphic` resolution.
        """
        from vsdx.document import VisioDocument
        from vsdx.page import Page
        from vsdx.shapes.shapetree import ShapeTree

        node = self._parent
        while node is not None:
            if isinstance(node, VisioDocument):
                return node
            if isinstance(node, Page):
                # Page._parent is the Pages collection, which carries
                # the document as its parent.
                pages = getattr(node, "_parent", None)
                doc = getattr(pages, "_parent", None)
                if isinstance(doc, VisioDocument):
                    return doc
                return None
            if isinstance(node, ShapeTree):
                node = node._parent
                continue
            node = getattr(node, "_parent", None)
        return None

    # -- custom geometry ------------------------------------------------

    @property
    def geometries(self) -> "Geometries":
        """The shape's :class:`~vsdx.geometry.Geometries` collection.

        Yields one :class:`~vsdx.geometry.Geometry` proxy per
        ``<Section N="Geometry">`` on the shape, in ``@IX`` order.
        Shapes without any Geometry sections expose an empty
        collection (``len(shape.geometries) == 0``).

        .. versionadded:: 0.3.0
        """
        from vsdx.geometry import Geometries

        return Geometries(self)

    @property
    def geometry(self) -> "Optional[Geometry]":
        """The shape's first Geometry section, or ``None``.

        Convenience shortcut for ``shape.geometries[0]`` when the
        caller only cares about the primary path. Returns ``None`` on
        shapes without any geometry sections — callers should consult
        :attr:`geometries` when they need to handle compound paths.

        .. versionadded:: 0.3.0
        """
        geometries = self.geometries
        if len(geometries) == 0:
            return None
        return geometries[0]

    def add_geometry(
        self,
        *,
        no_fill: bool = False,
        no_line: bool = False,
        no_show: bool = False,
    ) -> "Geometry":
        """Append a new :class:`~vsdx.geometry.Geometry` path and return it.

        Shortcut for ``shape.geometries.add(...)``. Flag-cell defaults
        match Visio desktop's "new path" dialog (all false → paint
        the path as both fill and stroke).

        .. versionadded:: 0.3.0
        """
        return self.geometries.add(
            no_fill=no_fill, no_line=no_line, no_show=no_show
        )

    # -- shape data / user-defined properties ---------------------------

    @property
    def data(self) -> "ShapeData":
        """The shape's :class:`~vsdx.shape_data.ShapeData` proxy.

        Dict-like over the shape's ``<Section N="Property">`` rows —
        ``shape.data["Cost"]`` returns the value, ``shape.data.field(
        "Cost")`` returns the full :class:`~vsdx.shape_data.ShapeDataField`
        with type / label / format metadata. Shapes without any
        Property section expose an empty mapping; the section is
        materialised on first ``add_field`` call.

        .. versionadded:: 0.3.0
        """
        from vsdx.shape_data import ShapeData

        return ShapeData(self)

    # -- hyperlinks ------------------------------------------------------

    @property
    def hyperlinks(self) -> "HyperlinkCollection":
        """The shape's :class:`~vsdx.hyperlinks.HyperlinkCollection` proxy.

        List-like + description-keyed wrapper over the shape's
        ``<Section N="Hyperlink">`` rows — ``shape.hyperlinks[0]``
        indexes by position, ``shape.hyperlinks["Support"]`` looks up
        by description. ``shape.hyperlinks.add(address=..., ...)``
        appends a new hyperlink. Shapes without any Hyperlink section
        expose an empty collection; the section is materialised on
        first ``add`` call.

        .. versionadded:: 0.3.0
        """
        from vsdx.hyperlinks import HyperlinkCollection

        return HyperlinkCollection(self)

    # -- helpers --------------------------------------------------------

    def _get_cell(self, name: str) -> Optional["CT_Cell"]:
        """Return the ``<Cell N=name>`` child, or ``None`` if absent.

        Uses the xmlchemy-generated ``cell_lst`` rather than a raw
        ``findall`` so the namespace-qualified lookup hits.
        """
        for cell in self._element.cell_lst:
            if cell.get("N") == name:
                return cell  # type: ignore[return-value]
        return None


class TextShape(Shape):
    """Shape that carries in-shape text.

    Every 0.1.0 autoshape is a ``TextShape`` — the ``.text_frame`` /
    ``.text`` convenience surface is inherited via this class rather
    than defined on every concrete subclass.
    """

    @property
    def has_text_frame(self) -> bool:
        """True — every 0.1.0 shape has a text frame on demand."""
        return True

    @property
    def text_frame(self) -> TextFrame:
        """:class:`TextFrame` wrapping the ``<Text>`` child of this shape."""
        text_el = self._element.get_or_add_text()
        return TextFrame(text_el)

    @property
    def text(self) -> str:
        """Shortcut: ``shape.text`` <=> ``shape.text_frame.text``."""
        return self.text_frame.text

    @text.setter
    def text(self, value: str) -> None:
        self.text_frame.text = value


__all__ = ["Shape", "TextShape"]
