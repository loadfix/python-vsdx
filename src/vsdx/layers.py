"""``Layer`` + ``Layers`` proxies — page-scoped drawing layers.

Visio layers are a **named section** on the page's ``<PageSheet>``
(``<Section N="Layer">``). Each ``<Row IX="N">`` inside the section
defines one layer and carries cells for name / colour / visibility /
print / lock / etc. Shapes join a layer by carrying a
``<Cell N="LayerMember" V="0,2">`` naming the indices they belong to.

Design notes (from the 0.2.0 scoping doc §4.1):

- *Zero new ``CT_*`` classes* — layers reuse the existing
  ``CT_Section`` / ``CT_Row`` / ``CT_Cell`` trio. The discriminator is
  value-level (``section.name_ == "Layer"``), not class-level.
- The 0.2.0 ``Layer`` proxy is the authoring surface; the oxml layer
  stays lower-level.
- Layer-index monotonicity is enforced on :meth:`Layers.add` — the
  next-available index is assigned at insert time. Delete semantics
  follow Visio desktop: every ``LayerMember`` cell on the page is
  rewritten to drop the deleted index and renumber the tail (see
  scoping-doc §9.1 and open-question #3).

.. versionadded:: 0.2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, List, Optional

from vsdx.oxml import qn
from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Row, CT_Section  # TODO(vsdx/track-1)
    from vsdx.page import Page

__all__ = ["Layer", "Layers", "ShapeLayers"]


_LAYER_SECTION_NAME = "Layer"


# ---------------------------------------------------------------------------
# Cell-level helpers — named cells inside a <Row>
# ---------------------------------------------------------------------------


def _row_cell(row, name: str):
    """Return the ``<Cell N=name>`` child on *row*, or ``None``."""
    for cell in row.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _get_or_add_row_cell(row, name: str):
    """Return the ``<Cell N=name>`` on *row*, creating one if absent.

    Visio's per-row ``<Cell>`` model mirrors the per-shape model —
    cells are distinguished by ``@N`` rather than element kind.
    """
    cell = _row_cell(row, name)
    if cell is not None:
        return cell
    # ``_add_cell`` is the xmlchemy-generated helper on CT_Row.
    cell = row._add_cell()
    cell.set("N", name)
    return cell


def _cell_v_as_bool(cell) -> bool:
    """``<Cell V="1">`` → ``True``; ``V="0"`` / absent → ``False``."""
    if cell is None:
        return False
    v = cell.get("V")
    return v == "1" or v == "true" or v == "True"


def _bool_to_v(value: bool) -> str:
    return "1" if value else "0"


# ---------------------------------------------------------------------------
# Layer proxy — wraps a single <Row IX="N"> inside <Section N="Layer">
# ---------------------------------------------------------------------------


class Layer:
    """One layer on a :class:`~vsdx.page.Page`.

    Construct indirectly via :class:`Layers.add` / iteration —
    callers do not instantiate this class directly.

    .. versionadded:: 0.2.0
    """

    def __init__(self, row: "CT_Row", layers: "Layers") -> None:
        self._row = row
        self._layers = layers

    # -- identity -------------------------------------------------------

    @property
    def index(self) -> int:
        """The layer's ``@IX`` index (zero-based)."""
        ix = self._row.get("IX")
        return int(ix) if ix is not None else 0

    # -- named-cell accessors -------------------------------------------

    @property
    def name(self) -> str:
        """The layer's display name (``<Cell N="Name" V="…">``)."""
        cell = _row_cell(self._row, "Name")
        return (cell.get("V") if cell is not None else "") or ""

    @name.setter
    def name(self, value: str) -> None:
        cell = _get_or_add_row_cell(self._row, "Name")
        cell.set("V", str(value))
        # Visio writes NameUniv alongside Name — keep them in sync by
        # default. Callers who need locale-divergent universal names
        # can override via :attr:`name_univ`.
        nu = _row_cell(self._row, "NameUniv")
        if nu is None or nu.get("V") == "" or nu.get("V") is None:
            nu_cell = _get_or_add_row_cell(self._row, "NameUniv")
            nu_cell.set("V", str(value))

    @property
    def name_univ(self) -> str:
        """Universal (locale-invariant) layer name."""
        cell = _row_cell(self._row, "NameUniv")
        return (cell.get("V") if cell is not None else "") or ""

    @name_univ.setter
    def name_univ(self, value: str) -> None:
        cell = _get_or_add_row_cell(self._row, "NameUniv")
        cell.set("V", str(value))

    @property
    def visible(self) -> bool:
        """Whether the layer is visible (``<Cell N="Visible" V="1">``)."""
        return _cell_v_as_bool(_row_cell(self._row, "Visible"))

    @visible.setter
    def visible(self, value: bool) -> None:
        cell = _get_or_add_row_cell(self._row, "Visible")
        cell.set("V", _bool_to_v(bool(value)))

    @property
    def print(self) -> bool:
        """Whether the layer prints (``<Cell N="Print" V="1">``)."""
        return _cell_v_as_bool(_row_cell(self._row, "Print"))

    @print.setter
    def print(self, value: bool) -> None:
        cell = _get_or_add_row_cell(self._row, "Print")
        cell.set("V", _bool_to_v(bool(value)))

    @property
    def print_(self) -> bool:
        """Trailing-underscore alias for :attr:`print`.

        ``print`` shadows the built-in; ``print_`` is provided as the
        PEP-8-friendly spelling for callers who prefer to avoid the
        keyword-shaped attribute name (matches python-pptx / python-docx
        convention for ``print`` / ``class`` / etc.).

        .. versionadded:: 0.3.0
        """
        return self.print

    @print_.setter
    def print_(self, value: bool) -> None:
        self.print = value

    @property
    def active(self) -> bool:
        return _cell_v_as_bool(_row_cell(self._row, "Active"))

    @active.setter
    def active(self, value: bool) -> None:
        cell = _get_or_add_row_cell(self._row, "Active")
        cell.set("V", _bool_to_v(bool(value)))

    @property
    def locked(self) -> bool:
        """Whether the layer is locked from edits (``<Cell N="Lock" V="1">``)."""
        return _cell_v_as_bool(_row_cell(self._row, "Lock"))

    @locked.setter
    def locked(self, value: bool) -> None:
        cell = _get_or_add_row_cell(self._row, "Lock")
        cell.set("V", _bool_to_v(bool(value)))

    @property
    def lock(self) -> bool:
        """Alias for :attr:`locked` matching the Visio cell-name spelling.

        The underlying ``<Cell N="Lock" V="…">`` is named ``Lock``
        singular; :attr:`locked` is the grammatical property name we
        prefer, and :attr:`lock` is the literal cell-name spelling for
        callers mapping directly off ECMA-376.

        .. versionadded:: 0.3.0
        """
        return self.locked

    @lock.setter
    def lock(self, value: bool) -> None:
        self.locked = value

    @property
    def snap(self) -> bool:
        return _cell_v_as_bool(_row_cell(self._row, "Snap"))

    @snap.setter
    def snap(self, value: bool) -> None:
        cell = _get_or_add_row_cell(self._row, "Snap")
        cell.set("V", _bool_to_v(bool(value)))

    @property
    def glue(self) -> bool:
        return _cell_v_as_bool(_row_cell(self._row, "Glue"))

    @glue.setter
    def glue(self, value: bool) -> None:
        cell = _get_or_add_row_cell(self._row, "Glue")
        cell.set("V", _bool_to_v(bool(value)))

    @property
    def color(self) -> str:
        """The layer colour cell value (typically ``"Themed"`` or an RGB index)."""
        cell = _row_cell(self._row, "Color")
        return (cell.get("V") if cell is not None else "") or ""

    @color.setter
    def color(self, value: str) -> None:
        cell = _get_or_add_row_cell(self._row, "Color")
        cell.set("V", str(value))

    # -- fluent setters -------------------------------------------------

    def set_visible(self, value: bool) -> "Layer":
        """Set :attr:`visible` and return self for chaining.

        Convenience mutator matching the python-docx / python-pptx
        ``set_…`` idiom, intended for the common case of toggling a
        single cell without breaking the fluent call chain::

            page.layers.add("Guides").set_visible(False).set_printable(False)

        .. versionadded:: 0.3.0
        """
        self.visible = bool(value)
        return self

    def set_printable(self, value: bool) -> "Layer":
        """Set :attr:`print` and return self for chaining.

        See :meth:`set_visible` for the design rationale. The method is
        spelt ``set_printable`` rather than ``set_print`` because
        ``print`` is the Python built-in; the property keeps the Visio
        cell-name spelling but the fluent form uses the adjective.

        .. versionadded:: 0.3.0
        """
        self.print = bool(value)
        return self


# ---------------------------------------------------------------------------
# Layers collection — wraps <Section N="Layer"> on a page's <PageSheet>
# ---------------------------------------------------------------------------


class Layers(ParentedElementProxy):
    """Layer collection on a :class:`~vsdx.page.Page`.

    Iteration yields :class:`Layer` proxies in ``@IX`` order. Add new
    layers via :meth:`add`; delete with :meth:`remove`.

    .. versionadded:: 0.2.0
    """

    def __init__(self, page: "Page") -> None:
        # The Layer section lives on the page-index entry's <PageSheet>,
        # not on <PageContents>. The ``Page`` proxy's ``_element`` is
        # already the <Page> index entry (see vsdx.page.Page.__init__),
        # so we don't need the page-part's PageContents here.
        super().__init__(page._element, page)
        self._page = page

    # -- container ------------------------------------------------------

    def __iter__(self) -> Iterator[Layer]:
        section = self._section()
        if section is None:
            return iter([])
        rows = sorted(
            section.row_lst,
            key=lambda r: int(r.get("IX") or 0),
        )
        return iter(Layer(r, self) for r in rows)

    def __len__(self) -> int:
        section = self._section()
        if section is None:
            return 0
        return len(section.row_lst)

    def __getitem__(self, idx: int) -> Layer:
        return list(iter(self))[idx]

    # -- lookup ---------------------------------------------------------

    def get(self, name: str) -> Optional[Layer]:
        """Return the layer with display name *name* or ``None``."""
        for layer in self:
            if layer.name == name:
                return layer
        return None

    # -- authoring ------------------------------------------------------

    def add(
        self,
        name: str,
        *,
        visible: bool = True,
        print: bool = True,
        color: str = "Themed",
    ) -> Layer:
        """Add a new layer and return its :class:`Layer` proxy.

        Assigns a fresh ``@IX`` (the next unused integer index). The
        caller supplies the display name; universal name defaults to
        match unless overridden afterwards via :attr:`Layer.name_univ`.

        .. versionadded:: 0.2.0
        """
        section = self._get_or_add_section()
        # Find the next available IX — monotonic, never gaps-aware
        # (scoping doc §2.5 invariant #2).
        used = set()
        for row in section.row_lst:
            ix = row.get("IX")
            if ix is not None:
                try:
                    used.add(int(ix))
                except ValueError:
                    pass
        next_ix = 0
        while next_ix in used:
            next_ix += 1
        # xmlchemy-generated add_row on CT_Section.
        row = section._add_row()
        row.set("IX", str(next_ix))
        layer = Layer(row, self)
        layer.name = name
        layer.visible = visible
        layer.print = print
        layer.color = color
        return layer

    def remove(self, layer: Layer) -> None:
        """Remove *layer* and renumber every shape's ``LayerMember`` cell.

        Renumbering matches Visio desktop behaviour: indices greater
        than the deleted layer's index are decremented; the deleted
        layer's own index is dropped from every shape. See scoping-doc
        open-question #3 (recommendation (a)).
        """
        section = self._section()
        if section is None:
            return
        target_ix = layer.index
        # Remove the row element itself.
        section.remove(layer._row)
        # Renumber layers with IX > target_ix.
        for other in section.row_lst:
            ix = int(other.get("IX") or 0)
            if ix > target_ix:
                other.set("IX", str(ix - 1))
        # Rewrite every LayerMember cell on every shape of the page.
        self._rewrite_layer_member_cells(target_ix)

    # -- shape-membership ----------------------------------------------

    def shapes_on(self, layer: Layer):
        """Yield every shape on this page that is a member of *layer*.

        Shapes declare membership via their ``<Cell N="LayerMember" V="…">``
        — a comma-separated integer list (``"0"``, ``"0,2"``, …).
        """
        from vsdx.shapes.base import Shape  # local import dodges a cycle

        target_ix = layer.index
        for shape in self._page.shapes:
            if not isinstance(shape, Shape):
                continue
            membership = _shape_layer_indices(shape._element)
            if target_ix in membership:
                yield shape

    # -- internal -------------------------------------------------------

    def _section(self):
        """Return the ``<Section N="Layer">`` child on the <PageSheet>.

        Returns ``None`` if the page carries no layer section (which is
        normal — Visio's default Page-1 has no layers until the user
        creates one).
        """
        page_sheet = self._page._element.pageSheet
        if page_sheet is None:
            return None
        for section in page_sheet.section_lst:
            if section.get("N") == _LAYER_SECTION_NAME:
                return section
        return None

    def _get_or_add_section(self) -> "CT_Section":
        section = self._section()
        if section is not None:
            return section
        page_sheet = self._page._element.get_or_add_pageSheet()
        new_section = page_sheet._add_section()
        new_section.set("N", _LAYER_SECTION_NAME)
        return new_section

    def _rewrite_layer_member_cells(self, removed_ix: int) -> None:
        from vsdx.shapes.base import Shape

        for shape in self._page.shapes:
            if not isinstance(shape, Shape):
                continue
            _rewrite_shape_membership(shape._element, removed_ix)


# ---------------------------------------------------------------------------
# Low-level membership helpers — operate on a <Shape> element directly
# ---------------------------------------------------------------------------


def _shape_layer_indices(shape_el) -> List[int]:
    """Return the layer indices declared by *shape_el*'s LayerMember cell."""
    for cell in shape_el.cell_lst:
        if cell.get("N") == "LayerMember":
            v = cell.get("V") or ""
            if not v:
                return []
            try:
                return [int(part) for part in v.split(",") if part != ""]
            except ValueError:
                return []
    return []


def _set_shape_layer_indices(shape_el, indices: List[int]) -> None:
    """Write a ``<Cell N="LayerMember" V="...">`` on *shape_el*.

    The caller is responsible for the semantics of *indices* (order,
    dedup); we serialise verbatim to preserve round-trip fidelity.
    """
    cell = None
    for c in shape_el.cell_lst:
        if c.get("N") == "LayerMember":
            cell = c
            break
    if cell is None:
        cell = shape_el._add_cell()
        cell.set("N", "LayerMember")
    cell.set("V", ",".join(str(i) for i in indices))


def _rewrite_shape_membership(shape_el, removed_ix: int) -> None:
    """Drop *removed_ix* from a shape's LayerMember list, decrement tail."""
    current = _shape_layer_indices(shape_el)
    if not current:
        return
    new = []
    for ix in current:
        if ix == removed_ix:
            continue
        if ix > removed_ix:
            new.append(ix - 1)
        else:
            new.append(ix)
    if new:
        _set_shape_layer_indices(shape_el, new)
    else:
        # Clear the cell entirely when a shape loses all memberships.
        for cell in list(shape_el.cell_lst):
            if cell.get("N") == "LayerMember":
                shape_el.remove(cell)


# -- used by vsdx.shapes.base.Shape.layers --
def _shape_layers_proxy(shape, page):
    """Return a list of :class:`Layer` objects for *shape*'s memberships.

    Called from :attr:`vsdx.shapes.base.Shape.layers` so the proxy
    layer can resolve ``LayerMember`` cell values to live Layer
    proxies without duplicating the parsing logic.
    """
    indices = _shape_layer_indices(shape._element)
    page_layers = page.layers
    lookup = {layer.index: layer for layer in page_layers}
    return [lookup[ix] for ix in indices if ix in lookup]


# ---------------------------------------------------------------------------
# ShapeLayers — per-shape layer-membership proxy
# ---------------------------------------------------------------------------


class ShapeLayers:
    """Layer-membership view on a single :class:`~vsdx.shapes.base.Shape`.

    Iterates the shape's ``<Cell N="LayerMember">`` indices, resolved
    against the owning page's :class:`Layers` collection. Supports the
    ergonomic membership idiom::

        shape.layers.add(layer)
        shape.layers.remove(layer)
        assert layer in shape.layers
        for L in shape.layers: ...
        len(shape.layers)

    Behaves like a list of :class:`Layer` proxies for read-only iteration
    so existing call-sites that did ``for L in shape.layers`` /
    ``len(shape.layers)`` / ``layer in shape.layers`` keep working
    unchanged. The :meth:`add` / :meth:`remove` mutators delegate to
    :meth:`Shape.add_to_layer` / :meth:`Shape.remove_from_layer` to
    preserve the canonical ordering invariant (scoping-doc §2.5
    invariant #3).

    Construct indirectly via :attr:`Shape.layers` — callers do not
    instantiate this class directly.

    .. versionadded:: 0.3.0
    """

    def __init__(self, shape) -> None:
        self._shape = shape

    # -- container ------------------------------------------------------

    def _resolved(self) -> List[Layer]:
        """Resolve this shape's LayerMember indices to live Layer proxies."""
        from vsdx.page import Page  # local import dodges a cycle
        from vsdx.shapes.shapetree import ShapeTree

        parent = self._shape._parent
        if isinstance(parent, ShapeTree):
            page = parent._parent
        elif isinstance(parent, Page):
            page = parent
        else:
            climbing = parent
            while climbing is not None and not isinstance(climbing, Page):
                climbing = getattr(climbing, "_parent", None)
            page = climbing
        if page is None:
            return []
        return _shape_layers_proxy(self._shape, page)

    def __iter__(self) -> Iterator[Layer]:
        return iter(self._resolved())

    def __len__(self) -> int:
        return len(self._resolved())

    def __getitem__(self, idx: int) -> Layer:
        return self._resolved()[idx]

    def __contains__(self, layer: object) -> bool:
        if not isinstance(layer, Layer):
            return False
        target_ix = layer.index
        return target_ix in _shape_layer_indices(self._shape._element)

    def __bool__(self) -> bool:
        return len(self) > 0

    def __eq__(self, other: object) -> bool:
        # Equate with a plain list of Layer proxies for back-compat with
        # ``shape.layers == [...]`` style assertions.
        if isinstance(other, list):
            return self._resolved() == other
        if isinstance(other, ShapeLayers):
            return self._shape is other._shape
        return NotImplemented

    def __repr__(self) -> str:
        return "<ShapeLayers %r>" % [layer.name for layer in self._resolved()]

    # -- authoring ------------------------------------------------------

    def add(self, layer: Layer) -> Layer:
        """Add *layer* to this shape's membership (idempotent).

        Mirrors :meth:`Shape.add_to_layer` and returns *layer* so
        chained calls like ``shape.layers.add(L).visible`` read
        naturally.

        .. versionadded:: 0.3.0
        """
        self._shape.add_to_layer(layer)
        return layer

    def remove(self, layer: Layer) -> None:
        """Remove *layer* from this shape's membership (idempotent).

        Mirrors :meth:`Shape.remove_from_layer`.

        .. versionadded:: 0.3.0
        """
        self._shape.remove_from_layer(layer)


# -- unused-import guard --
_ = qn
