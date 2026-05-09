"""``DataGraphic`` + ``DataGraphics`` proxies — Visio data graphics.

A *data graphic* is a named rendering rule Visio applies on top of a
shape's custom-property (ShapeData) values. The graphic's items bind
one ShapeData field to one graphic element (text callout, icon set,
colour-by-value, data bar) so Visio desktop renders e.g. a red traffic
light when the ``Priority`` field equals ``"High"``.

Schema (per MS Learn *DataGraphic* / *DataGraphicItem* pages):

- **Container** — ``<Section N="DataGraphic">`` child of
  ``<VisioDocument>`` (document-root level; one section per graphic).
  The section's ``@IX`` attribute is the document-scoped graphic id.
- **Items** — each ``<Row IX="n" T="kind">`` inside the section binds
  a ShapeData column (``<Cell N="Column">``) to a graphic kind
  (``T="TextCallout"`` / ``T="IconSet"`` / ``T="ColorByValue"`` /
  ``T="DataBar"``).
- **Shape linkage** — a shape opts into a data graphic by setting
  ``<Cell N="DataGraphic" V="<id>">`` on itself; the value is the
  DataGraphic section's ``@IX``.

Scope (0.2.0 — R8-2):

- **Read** — parse + expose the full definition tree.
- **Preserve** — every section / row / cell round-trips byte-faithful
  because the backing oxml classes are the same
  :class:`~vsdx.oxml.section.CT_Section` / :class:`CT_Row` / ``CT_Cell``
  we've always used; the proxy layer is a read-through view.
- **Shape-side mutate** — ``shape.data_graphic = graphic`` / ``= None``
  writes/clears the ``DataGraphic`` cell on the shape. Authoring new
  DataGraphic definitions (``document.add_data_graphic(...)``) is
  **deferred to 0.3.0**.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, List, Optional

from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.oxml._stubs import CT_Row, CT_Section  # TODO(vsdx/track-1)
    from vsdx.shapes.base import Shape

__all__ = ["DataGraphic", "DataGraphicItem", "DataGraphics"]


_DATAGRAPHIC_SECTION_NAME = "DataGraphic"
_SHAPE_DATAGRAPHIC_CELL = "DataGraphic"


# ---------------------------------------------------------------------------
# Cell-level helpers — reuse the row-cell lookup pattern from vsdx.layers.
# Duplicated here (rather than imported) because the layers module treats
# them as private and their signatures match 1:1.
# ---------------------------------------------------------------------------


def _row_cell(row, name: str):
    """Return the ``<Cell N=name>`` child on *row*, or ``None``."""
    for cell in row.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _row_cell_v(row, name: str) -> Optional[str]:
    cell = _row_cell(row, name)
    if cell is None:
        return None
    return cell.get("V")


# ---------------------------------------------------------------------------
# DataGraphicItem — one binding (shape-data column -> graphic kind).
# ---------------------------------------------------------------------------


class DataGraphicItem:
    """A single ``<Row>`` inside a ``<Section N="DataGraphic">``.

    Binds a ShapeData column to one graphic element. The ``@T``
    attribute on the row discriminates the kind:

    - ``TextCallout`` — renders a text balloon pointing at the shape.
    - ``IconSet`` — renders one of N icons based on value bands.
    - ``ColorByValue`` — repaints the shape based on value bands.
    - ``DataBar`` — renders a horizontal bar sized by value.

    The row also carries per-kind cells (``<Cell N="Column">`` for the
    bound ShapeData column, ``<Cell N="DefaultStyle">`` for default
    appearance, plus kind-specific cells). 0.2.0 exposes the
    discriminator + column + a :attr:`cells` dict for full
    round-trip; typed per-kind views are a 0.3.0 concern.

    .. versionadded:: 0.2.0
    """

    def __init__(self, row: "CT_Row", graphic: "DataGraphic") -> None:
        self._row = row
        self._graphic = graphic

    # -- identity -------------------------------------------------------

    @property
    def index(self) -> int:
        """The item's ``@IX`` within the graphic (zero-based)."""
        ix = self._row.get("IX")
        return int(ix) if ix is not None else 0

    @property
    def kind(self) -> Optional[str]:
        """The item's graphic kind (``@T`` attribute).

        One of ``TextCallout`` / ``IconSet`` / ``ColorByValue`` /
        ``DataBar``, or ``None`` for rows Visio has written without a
        discriminator (rare; preserved verbatim on round-trip).
        """
        return self._row.get("T")

    # -- bindings -------------------------------------------------------

    @property
    def column(self) -> Optional[str]:
        """The ShapeData column this item binds to.

        Read from ``<Cell N="Column" V="…">``. The value is a
        column-reference formula like ``"Prop.Priority"`` that names
        the ``<Row N="Priority">`` inside a shape's
        ``<Section N="Property">``.
        """
        return _row_cell_v(self._row, "Column")

    @property
    def default_style(self) -> Optional[str]:
        """The item's ``DefaultStyle`` cell value, or ``None``."""
        return _row_cell_v(self._row, "DefaultStyle")

    @property
    def callout_type(self) -> Optional[str]:
        """The item's ``CalloutType`` cell (for ``TextCallout`` items)."""
        return _row_cell_v(self._row, "CalloutType")

    @property
    def cells(self) -> dict:
        """Every named ``<Cell>`` on the row, keyed by ``@N``.

        Convenience for callers who need to read per-kind cells this
        proxy hasn't specialised (``LowValue``, ``HighValue``,
        ``IconSet``, etc.). Values are the raw ``@V`` attributes;
        formulas (``@F``) are not surfaced here — use
        :attr:`element` for full access.
        """
        out = {}
        for cell in self._row.cell_lst:
            name = cell.get("N")
            if name is None:
                continue
            out[name] = cell.get("V")
        return out

    # -- escape hatch ---------------------------------------------------

    @property
    def element(self) -> "CT_Row":
        """The underlying ``<Row>`` element.

        Exposed for callers that need to inspect formulas / unit hints
        / uncommon cells the proxy doesn't surface.
        """
        return self._row


# ---------------------------------------------------------------------------
# DataGraphic — one ``<Section N="DataGraphic">`` on ``<VisioDocument>``.
# ---------------------------------------------------------------------------


class DataGraphic:
    """A single data graphic definition.

    Wraps one ``<Section N="DataGraphic" IX="N">`` at the document
    root. Iterate :attr:`items` to walk the per-field bindings.

    Construct indirectly via :attr:`VisioDocument.data_graphics` —
    callers do not instantiate this class directly.

    .. versionadded:: 0.2.0
    """

    def __init__(
        self, section: "CT_Section", collection: "DataGraphics"
    ) -> None:
        self._section = section
        self._collection = collection

    # -- identity -------------------------------------------------------

    @property
    def id(self) -> int:
        """The graphic's document-scoped id (``@IX``)."""
        ix = self._section.get("IX")
        return int(ix) if ix is not None else 0

    @property
    def name(self) -> Optional[str]:
        """The graphic's display name (``@NameU`` attribute).

        Visio stores the user-facing name on the ``Section`` element
        itself (``@NameU`` for the universal / locale-invariant name,
        ``@Name`` for the display name). Returns ``@Name`` with
        ``@NameU`` as fallback, matching Visio desktop's resolution
        order.
        """
        return self._section.get("Name") or self._section.get("NameU")

    @property
    def name_universal(self) -> Optional[str]:
        """The locale-invariant ``@NameU`` attribute, if present."""
        return self._section.get("NameU")

    # -- behaviour flags ------------------------------------------------

    @property
    def default_position(self) -> Optional[str]:
        """``@DefaultPosition`` — where callouts sit relative to the shape.

        Values are Visio-internal integers (e.g. ``"0"`` = "Below the
        shape"). Preserved as a string for fidelity.
        """
        return self._section.get("DefaultPosition")

    @property
    def default_style(self) -> Optional[str]:
        """``@DefaultStyle`` — default theme / line / fill style id."""
        return self._section.get("DefaultStyle")

    @property
    def hide_shape_data_fields(self) -> Optional[str]:
        """``@HideShapeDataFields`` — suppress the ShapeData window? (flag)."""
        return self._section.get("HideShapeDataFields")

    # -- items ----------------------------------------------------------

    @property
    def items(self) -> List[DataGraphicItem]:
        """The graphic's :class:`DataGraphicItem` rows, in ``@IX`` order.

        One entry per ShapeData-field binding.
        """
        rows = sorted(
            self._section.row_lst,
            key=lambda r: int(r.get("IX") or 0),
        )
        return [DataGraphicItem(r, self) for r in rows]

    def __iter__(self) -> Iterator[DataGraphicItem]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self._section.row_lst)

    def __getitem__(self, idx: int) -> DataGraphicItem:
        return self.items[idx]

    # -- escape hatch ---------------------------------------------------

    @property
    def element(self) -> "CT_Section":
        """The underlying ``<Section>`` element."""
        return self._section


# ---------------------------------------------------------------------------
# DataGraphics collection — all ``<Section N="DataGraphic">`` on a document.
# ---------------------------------------------------------------------------


class DataGraphics(ParentedElementProxy):
    """Document-scoped data-graphic collection.

    Iterate the collection to walk every ``<Section N="DataGraphic">``
    child of ``<VisioDocument>`` in document order. Lookup by id via
    :meth:`get` or by name via :meth:`get_by_name`.

    Authoring new graphics (``document.add_data_graphic(...)``) is
    **deferred to 0.3.0**; the 0.2.0 surface is read + preserve +
    shape-side association only.

    .. versionadded:: 0.2.0
    """

    def __init__(self, document: "VisioDocument") -> None:
        super().__init__(document._element, document)
        self._document = document

    # -- container ------------------------------------------------------

    def _sections(self) -> List["CT_Section"]:
        """Return every ``<Section N="DataGraphic">`` child of the document.

        Order of iteration is document order.
        """
        return [
            s
            for s in self._document._element.section_lst
            if s.get("N") == _DATAGRAPHIC_SECTION_NAME
        ]

    def __iter__(self) -> Iterator[DataGraphic]:
        return iter(DataGraphic(s, self) for s in self._sections())

    def __len__(self) -> int:
        return len(self._sections())

    def __getitem__(self, idx: int) -> DataGraphic:
        return list(self)[idx]

    # -- lookup ---------------------------------------------------------

    def get(self, graphic_id: int) -> Optional[DataGraphic]:
        """Return the DataGraphic with ``@IX == graphic_id`` or ``None``."""
        for graphic in self:
            if graphic.id == graphic_id:
                return graphic
        return None

    def get_by_name(self, name: str) -> Optional[DataGraphic]:
        """Return the DataGraphic whose display name matches *name*.

        Compares against ``@Name`` first, then ``@NameU``. Returns
        ``None`` if nothing matches.
        """
        for graphic in self:
            if graphic.name == name or graphic.name_universal == name:
                return graphic
        return None


# ---------------------------------------------------------------------------
# Shape-side accessors — called from vsdx.shapes.base.Shape via helpers.
# ---------------------------------------------------------------------------


def _shape_data_graphic_id(shape_el) -> Optional[int]:
    """Return the DataGraphic id declared on *shape_el* or ``None``.

    Reads ``<Cell N="DataGraphic" V="…">``. Returns ``None`` if the
    cell is absent, empty, or non-integer.
    """
    for cell in shape_el.cell_lst:
        if cell.get("N") == _SHAPE_DATAGRAPHIC_CELL:
            v = cell.get("V")
            if v is None or v == "":
                return None
            try:
                return int(v)
            except ValueError:
                return None
    return None


def _set_shape_data_graphic_id(shape_el, graphic_id: Optional[int]) -> None:
    """Write or remove the shape's ``<Cell N="DataGraphic">`` cell.

    ``graphic_id=None`` removes the cell entirely (the shape reverts
    to "no data graphic"). An integer value overwrites any existing
    cell in-place.
    """
    existing = None
    for cell in shape_el.cell_lst:
        if cell.get("N") == _SHAPE_DATAGRAPHIC_CELL:
            existing = cell
            break
    if graphic_id is None:
        if existing is not None:
            shape_el.remove(existing)
        return
    cell = existing if existing is not None else shape_el._add_cell()
    cell.set("N", _SHAPE_DATAGRAPHIC_CELL)
    cell.set("V", str(int(graphic_id)))


def _resolve_shape_data_graphic(
    shape: "Shape", document: "VisioDocument"
) -> Optional[DataGraphic]:
    """Return the :class:`DataGraphic` linked to *shape*, or ``None``.

    Called from :attr:`vsdx.shapes.base.Shape.data_graphic` — keeps
    the resolution logic next to the cell layout rather than spread
    across the shape module.
    """
    gid = _shape_data_graphic_id(shape._element)
    if gid is None:
        return None
    return document.data_graphics.get(gid)
