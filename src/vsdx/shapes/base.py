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

import logging
from typing import TYPE_CHECKING, Any, List, Optional

from vsdx.enum.cells import ST_Unit
from vsdx.shared import ParentedElementProxy
from vsdx.text import TextFrame
from vsdx.util import Inches, Length

if TYPE_CHECKING:
    from vsdx.connection_points import ConnectionPoints
    from vsdx.geometry import Geometries, Geometry
    from vsdx.hyperlinks import HyperlinkCollection
    from vsdx.master import Master
    from vsdx.oxml._stubs import CT_Cell, CT_Shape  # TODO(vsdx/track-1)
    from vsdx.shape_data import ShapeData
    from vsdx.shapes.shapetree import ShapeTree


_log = logging.getLogger(__name__)


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
    #
    # Getters walk the master-chain via :meth:`effective_prop` so an
    # instance shape that omits (say) ``<Cell N="Width">`` inherits the
    # value from its master's first shape (or a chained ancestor). See
    # :meth:`master_chain` for the walk order. Setters write the cell
    # directly on the instance — instance-level overrides always win
    # the resolver race against any master value.

    @property
    def pin_x(self) -> Length:
        """Pin X — horizontal location of the shape's pin, in inches.

        Falls back to the master-chain value when the instance has no
        ``<Cell N="PinX">`` of its own. Returns ``Inches(0.0)`` when
        unresolved.
        """
        return Inches(self._effective_cell_float("PinX") or 0.0)

    @pin_x.setter
    def pin_x(self, value: Any) -> None:
        _set_cell_float(self._element, "PinX", float(value), ST_Unit.INCHES.value)

    @property
    def pin_y(self) -> Length:
        return Inches(self._effective_cell_float("PinY") or 0.0)

    @pin_y.setter
    def pin_y(self, value: Any) -> None:
        _set_cell_float(self._element, "PinY", float(value), ST_Unit.INCHES.value)

    @property
    def width(self) -> Length:
        return Inches(self._effective_cell_float("Width") or 0.0)

    @width.setter
    def width(self, value: Any) -> None:
        _set_cell_float(self._element, "Width", float(value), ST_Unit.INCHES.value)

    @property
    def height(self) -> Length:
        return Inches(self._effective_cell_float("Height") or 0.0)

    @height.setter
    def height(self, value: Any) -> None:
        _set_cell_float(self._element, "Height", float(value), ST_Unit.INCHES.value)

    @property
    def angle(self) -> float:
        """Rotation angle in radians (Visio's native unit for Angle).

        Falls back to the master-chain value when the instance has no
        ``<Cell N="Angle">`` of its own.
        """
        return self._effective_cell_float("Angle") or 0.0

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
    def layers(self) -> "Any":
        """Layer-membership view on this shape.

        Returns a :class:`~vsdx.layers.ShapeLayers` proxy that supports
        both the read-only list idiom (``len(shape.layers)``,
        ``layer in shape.layers``, ``for L in shape.layers``) and the
        ergonomic ``shape.layers.add(layer)`` / ``shape.layers.remove(layer)``
        mutators introduced in 0.3.0. Iterating yields
        :class:`~vsdx.layers.Layer` proxies in the
        ``<Cell N="LayerMember" V="…">`` declaration order; an empty
        membership reads as ``len(...) == 0`` and ``bool(...)`` ``False``.

        .. versionadded:: 0.2.0
        .. versionchanged:: 0.3.0
            Returns :class:`~vsdx.layers.ShapeLayers` instead of a bare
            ``list``. Backwards-compatible — every read-only pattern that
            worked on the list still works on the proxy.
        """
        from vsdx.layers import ShapeLayers

        return ShapeLayers(self)

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

    def add_to_layer(self, layer) -> None:
        """Add this shape to *layer* (idempotent).

        Appends *layer.index* to the shape's ``<Cell N="LayerMember">``
        value if it is not already present. Existing memberships are
        preserved in their original declaration order — the new index
        is appended to the tail, matching Visio desktop's append-on-add
        behaviour.

        .. versionadded:: 0.3.0
        """
        from vsdx.layers import (
            _set_shape_layer_indices,
            _shape_layer_indices,
        )

        current = _shape_layer_indices(self._element)
        target = layer.index
        if target in current:
            return
        _set_shape_layer_indices(self._element, current + [target])

    def remove_from_layer(self, layer) -> None:
        """Remove this shape from *layer* (idempotent).

        Drops *layer.index* from the shape's ``<Cell N="LayerMember">``
        value if present; leaves the remaining indices (and their
        order) untouched. When the removal empties the list the cell
        itself is cleaned up so a shape with no layers has no
        ``LayerMember`` cell (matches
        :func:`vsdx.layers._rewrite_shape_membership`).

        .. versionadded:: 0.3.0
        """
        from vsdx.layers import (
            _set_shape_layer_indices,
            _shape_layer_indices,
        )

        current = _shape_layer_indices(self._element)
        target = layer.index
        if target not in current:
            return
        remaining = [ix for ix in current if ix != target]
        if remaining:
            _set_shape_layer_indices(self._element, remaining)
            return
        # Clear the cell entirely when the shape loses all memberships.
        shape_el = self._element
        for cell in list(shape_el.cell_lst):
            if cell.get("N") == "LayerMember":
                shape_el.remove(cell)

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

    # -- data-recordset bindings ----------------------------------------

    @property
    def data_bindings(self):
        """The shape's :class:`~vsdx.data_recordsets.DataBinding` proxies.

        List-like over every ``<DataBinding Recordset="n" Row="m"/>``
        child of this shape. Each binding resolves to a row in one of
        the document's :attr:`~vsdx.document.VisioDocument.data_
        recordsets`, exposing the linked ``DataRecordset`` / ``DataRow``
        and a read-only column-name → value dict.

        Read-only in 0.2.0 — returns an empty list when the shape has
        no bindings (the common case) or when the owning document
        cannot be resolved (unit-test oxml fixtures).

        .. versionadded:: 0.2.0
        """
        from vsdx.data_recordsets import _shape_data_bindings

        document = self._owning_document()
        if document is None:
            return []
        return _shape_data_bindings(self, document)

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

    # -- connector attachments -----------------------------------------

    def _owning_page_contents(self):
        """Walk up the proxy tree to the owning ``<PageContents>``.

        Returns ``None`` when the shape was constructed outside a
        :class:`ShapeTree` — unit-test oxml-only fixtures fall in this
        bucket and silently yield empty connector lists.
        """
        from vsdx.shapes.shapetree import ShapeTree

        tree = self._parent
        while tree is not None and not isinstance(tree, ShapeTree):
            tree = getattr(tree, "_parent", None)
        if tree is None:
            return tree, None
        return tree, tree._element

    def _connector_proxies_for(self, from_cell: str):
        """Return the :class:`Connector` proxies gluing *this* shape on *from_cell*.

        *from_cell* is ``"EndX"`` (for :attr:`connections_in` — the
        target-side glue) or ``"BeginX"`` (for :attr:`connections_out` —
        the source-side glue).  Walks the owning page's ``<Connects>``
        element; every matching entry resolves to the connector shape
        with the same ``@FromSheet`` ID.
        """
        from vsdx.shapes.connector import Connector

        tree, page_contents = self._owning_page_contents()
        if tree is None or page_contents is None:
            return []
        connects = getattr(page_contents, "connects", None)
        if connects is None:
            return []
        my_id = str(self.shape_id)
        connector_ids: list[int] = []
        seen: set[int] = set()
        for entry in connects.connect_lst:
            if entry.get("FromCell") != from_cell:
                continue
            if entry.get("ToSheet") != my_id:
                continue
            from_sheet = entry.get("FromSheet")
            if from_sheet is None:
                continue
            try:
                fsid = int(from_sheet)
            except ValueError:
                continue
            if fsid in seen:
                continue
            seen.add(fsid)
            connector_ids.append(fsid)
        connectors: list[Connector] = []
        for fsid in connector_ids:
            for el in page_contents.shapes_element.shape_lst:
                if int(el.shape_id or 0) == fsid:
                    connectors.append(Connector(el, tree))
                    break
        return connectors

    @property
    def connections_in(self):
        """:class:`Connector` instances whose *target* endpoint glues to this shape.

        Walks the owning page's ``<Connects>`` for entries with
        ``@FromCell="EndX"`` and ``@ToSheet`` matching this shape's ID,
        resolving each to the connector shape at ``@FromSheet``.
        Returns ``[]`` when this shape is unparented or when no such
        glue exists.

        .. versionadded:: 0.3.0
        """
        return self._connector_proxies_for("EndX")

    @property
    def connections_out(self):
        """:class:`Connector` instances whose *source* endpoint glues to this shape.

        Mirror of :attr:`connections_in` against ``@FromCell="BeginX"``
        glue entries.

        .. versionadded:: 0.3.0
        """
        return self._connector_proxies_for("BeginX")

    # -- connection points ---------------------------------------------

    @property
    def connection_points(self) -> "ConnectionPoints":
        """The shape's :class:`~vsdx.connection_points.ConnectionPoints` proxy.

        List-like over the shape's ``<Section N="Connection">`` rows —
        ``shape.connection_points[0]`` returns the first point,
        ``shape.connection_points.add(x, y)`` appends a new one.
        Shapes without any Connection section expose an empty
        sequence; the section is materialised on first ``add`` call.

        .. versionadded:: 0.3.0
        """
        from vsdx.connection_points import ConnectionPoints

        return ConnectionPoints(self)

    # -- master-chain inheritance --------------------------------------

    @property
    def master(self) -> Optional["Master"]:
        """The :class:`~vsdx.master.Master` this shape instances, or ``None``.

        Resolves the shape's raw ``@Master`` attribute (NameU string or
        numeric ID) against the owning document's ``doc.masters``
        collection. Returns ``None`` for shapes that are not master
        instances, or when the shape was constructed without a proxy
        parent chain (unit-test oxml fixtures).

        .. versionadded:: 0.3.0
        """
        ref = self._element.get("Master")
        if ref is None or ref == "":
            return None
        document = self._owning_document()
        if document is None:
            return None
        return document.masters.resolve(ref)

    @property
    def master_chain(self) -> List["Master"]:
        """Master inheritance chain, most-specific first.

        Walks ``self.master`` then each master's ``parent_master_ref``
        (``<Master Master="...">``) until the pointer is absent or a
        cycle is detected. A cycle (a master referring back to one
        already visited) is broken early with a ``logging.WARNING`` —
        the chain is truncated at the first already-seen master.

        Returns an empty list for shapes with no master, or when the
        owning document cannot be resolved.

        .. versionadded:: 0.3.0
        """
        chain: List["Master"] = []
        seen_ids: set[int] = set()
        current = self.master
        while current is not None:
            key = id(current._element)
            if key in seen_ids:
                _log.warning(
                    "master-chain cycle detected at '%s'; truncating walk",
                    getattr(current, "name_u", None) or "?",
                )
                break
            seen_ids.add(key)
            chain.append(current)
            next_ref = current.parent_master_ref
            if next_ref is None or next_ref == "":
                break
            masters = current._parent  # Masters collection
            next_master = masters.resolve(next_ref) if masters is not None else None
            if next_master is None:
                break
            current = next_master
        return chain

    def effective_prop(self, name: str) -> Optional[Any]:
        """Resolve a named cell, walking up the master chain.

        Order:

        1. The instance shape's own ``<Cell N=name>`` (if present and
           carrying a non-empty ``V`` / or just any value — absent is
           the only "not defined" signal).
        2. Each master in :attr:`master_chain`, in order.

        Returns the cell proxy (carrying ``V``, ``U``, ``F``) for the
        first match, or ``None`` if no master defines the cell either.
        The proxy is returned rather than the raw value so callers can
        discriminate between a numeric value, a formula-only cell, and
        a theme reference.

        .. versionadded:: 0.3.0
        """
        own = self._get_cell(name)
        if own is not None:
            return own
        for master in self.master_chain:
            cell = master.get_cell(name)
            if cell is not None:
                return cell
        return None

    def _effective_cell_float(self, name: str) -> Optional[float]:
        """Return the float value of the effective ``<Cell N=name>``.

        Private helper shared by the geometry accessors. Applies the
        same empty-V / non-numeric guard as :func:`_cell_float` so
        formula-only master cells (no ``V``) don't crash the caller.
        """
        cell = self.effective_prop(name)
        if cell is None:
            return None
        v = cell.get("V")
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @property
    def effective_text(self) -> str:
        """In-shape text, falling back to the master chain.

        Returns the instance's ``<Text>`` content when non-empty;
        otherwise walks :attr:`master_chain` and returns the first
        non-empty master-level text. Returns the empty string when no
        text is found anywhere in the chain.

        .. versionadded:: 0.3.0
        """
        text_el = getattr(self._element, "text", None)
        if text_el is not None:
            own = text_el.text
            if own:
                return own
        for master in self.master_chain:
            mtext = master.text
            if mtext:
                return mtext
        return ""

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
