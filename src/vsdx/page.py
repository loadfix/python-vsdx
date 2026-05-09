"""``Page`` + ``Pages`` proxies for python-vsdx.

``Pages`` is the collection surface on :class:`~vsdx.document.VisioDocument`
— it wraps the ``PagesPart`` (which owns ``/visio/pages/pages.xml``) and
exposes ``add_page`` / ``__iter__`` / ``__getitem__`` / ``__len__``.

``Page`` wraps a single ``<Page>`` entry in that index plus its
corresponding ``PagePart`` (``/visio/pages/page{N}.xml``). The
interesting methods on ``Page`` are ``shapes`` (the :class:`~vsdx.shapes.ShapeTree`
proxy) and ``next_shape_id`` (used by the shape tree to allocate unique
IDs within this page).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional

from vsdx.shapes.shapetree import ShapeTree
from vsdx.shared import ParentedElementProxy, PartElementProxy
from vsdx.theme import Theme
from vsdx.util import Inches, Length, lazyproperty

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.ink import InkStroke
    from vsdx.layers import Layers
    from vsdx.oxml._stubs import CT_Cell, CT_Page, CT_PageSheet  # TODO(vsdx/track-1)
    from vsdx.parts._stubs import PagePart, PagesPart  # TODO(vsdx/track-2)
    from vsdx.print_setup import PrintSetup


class Page(PartElementProxy):
    """A single page in a Visio document.

    Exposes the shape-tree and page metadata (name, width, height).
    Each :class:`Page` owns a :class:`~vsdx.parts._stubs.PagePart`.
    """

    def __init__(self, page_part: "PagePart", parent: "Pages") -> None:
        super().__init__(page_part.page_element, page_part)
        self._page_part = page_part
        self._parent = parent

    # -- metadata -------------------------------------------------------

    @property
    def name(self) -> Optional[str]:
        return self._element.name  # type: ignore[attr-defined]

    @name.setter
    def name(self, value: str) -> None:
        self._element.name = value  # type: ignore[attr-defined]

    @property
    def width(self) -> Length:
        """Page width, in inches."""
        v = self._element.get("PageWidth")
        return Inches(float(v)) if v else Inches(8.5)

    @width.setter
    def width(self, value: float) -> None:
        self._element.set("PageWidth", _fmt(float(value)))

    @property
    def height(self) -> Length:
        """Page height, in inches."""
        v = self._element.get("PageHeight")
        return Inches(float(v)) if v else Inches(11.0)

    @height.setter
    def height(self, value: float) -> None:
        self._element.set("PageHeight", _fmt(float(value)))

    # -- page scale / drawing scale (PageSheet singleton cells) --------

    def _sheet_cell_v(self, name: str) -> Optional[str]:
        """Return the ``@V`` on ``<PageSheet><Cell N=name>``, or ``None``.

        Shared helper for scale / snap / visibility singleton cells —
        all of which live as direct ``<Cell>`` children on the page's
        ``<PageSheet>``. Returns ``None`` when the sheet is absent or
        carries no cell with that ``@N``.
        """
        sheet = self._element.pageSheet
        if sheet is None:
            return None
        for cell in sheet.cell_lst:
            if cell.get("N") == name:
                return cell.get("V")
        return None

    def _set_sheet_cell_v(
        self, name: str, value: Optional[str], unit: Optional[str] = None
    ) -> None:
        """Create-or-update ``<PageSheet><Cell N=name V=value [U=unit]>``.

        Passing ``None`` clears the cell entirely so Visio falls back
        to the schema default on next open (matches the byte-identity
        expectation of callers authoring against otherwise-default
        pages — the cell is materialised only when explicitly set).
        """
        if value is None:
            sheet = self._element.pageSheet
            if sheet is None:
                return
            for cell in list(sheet.cell_lst):
                if cell.get("N") == name:
                    sheet.remove(cell)
                    return
            return
        sheet = self._element.get_or_add_pageSheet()
        target = None
        for cell in sheet.cell_lst:
            if cell.get("N") == name:
                target = cell
                break
        if target is None:
            target = sheet._add_cell()
            target.set("N", name)
        target.set("V", value)
        if unit is not None:
            target.set("U", unit)

    @property
    def page_scale(self) -> Optional[float]:
        """The page (real-world) scale (``<PageSheet><Cell N="PageScale">``).

        Visio's two-cell drawing-scale model splits the user's "1 inch
        = 10 feet" setting into :attr:`page_scale` (the drawing-unit
        multiplier Visio uses for page-space coordinates) and
        :attr:`drawing_scale` (the real-world-unit measure). The ratio
        ``drawing_scale / page_scale`` yields the displayed scale.

        Returns ``None`` when the cell is absent (Visio defaults the
        ratio to 1:1 — "no drawing scale"). Assigning ``None`` removes
        the cell; numeric assignment materialises the PageSheet on
        demand.

        .. versionadded:: 0.3.0
        """
        raw = self._sheet_cell_v("PageScale")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @page_scale.setter
    def page_scale(self, value: Optional[float]) -> None:
        if value is None:
            self._set_sheet_cell_v("PageScale", None)
            return
        self._set_sheet_cell_v("PageScale", _fmt(float(value)), unit="IN")

    @property
    def drawing_scale(self) -> Optional[float]:
        """The drawing (real-world) scale value (``<Cell N="DrawingScale">``).

        See :attr:`page_scale` for the split-cell drawing-scale model.
        Returns ``None`` when the cell is absent.

        .. versionadded:: 0.3.0
        """
        raw = self._sheet_cell_v("DrawingScale")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @drawing_scale.setter
    def drawing_scale(self, value: Optional[float]) -> None:
        if value is None:
            self._set_sheet_cell_v("DrawingScale", None)
            return
        self._set_sheet_cell_v("DrawingScale", _fmt(float(value)), unit="IN")

    @property
    def drawing_size_type(self) -> Optional[int]:
        """Drawing-size-type code (``<Cell N="DrawingSizeType">``).

        Visio's ``visDrawSizeStandard`` enum — ``0`` = same-as-printer,
        ``1`` = fit-to-drawing-contents, ``2`` = standard-paper,
        ``3`` = custom-size, ``4`` = custom-scaled, etc. Returns
        ``None`` when the cell is absent.

        .. versionadded:: 0.3.0
        """
        raw = self._sheet_cell_v("DrawingSizeType")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            try:
                return int(float(raw))
            except ValueError:
                return None

    @drawing_size_type.setter
    def drawing_size_type(self, value: Optional[int]) -> None:
        if value is None:
            self._set_sheet_cell_v("DrawingSizeType", None)
            return
        self._set_sheet_cell_v("DrawingSizeType", str(int(value)))

    @property
    def drawing_scale_type(self) -> Optional[int]:
        """Drawing-scale-type code (``<Cell N="DrawingScaleType">``).

        Visio's ``visDrawScaleType`` enum — ``0`` = no-scale,
        ``1`` = architectural, ``2`` = civil-engineering, ``3`` =
        custom, ``4`` = metric, ``5`` = mechanical-engineering, ``6``
        = generic (dimensionless). Returns ``None`` when the cell is
        absent.

        .. versionadded:: 0.3.0
        """
        raw = self._sheet_cell_v("DrawingScaleType")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            try:
                return int(float(raw))
            except ValueError:
                return None

    @drawing_scale_type.setter
    def drawing_scale_type(self, value: Optional[int]) -> None:
        if value is None:
            self._set_sheet_cell_v("DrawingScaleType", None)
            return
        self._set_sheet_cell_v("DrawingScaleType", str(int(value)))

    @property
    def inhibit_snap(self) -> bool:
        """Whether the page suppresses snap (``<Cell N="InhibitSnap">``).

        ``True`` corresponds to ``@V="1"``. Absent cells read as
        ``False``. The setter materialises the cell on first use.

        .. versionadded:: 0.3.0
        """
        raw = self._sheet_cell_v("InhibitSnap")
        if raw is None:
            return False
        return raw.strip().lower() in ("1", "true", "yes", "-1")

    @inhibit_snap.setter
    def inhibit_snap(self, value: bool) -> None:
        self._set_sheet_cell_v("InhibitSnap", "1" if bool(value) else "0")

    @property
    def ui_visibility(self) -> Optional[int]:
        """UI-visibility flag (``<Cell N="UIVisibility">``).

        ``0`` = visible (default), ``1`` = hidden-in-UI (used for
        auxiliary pages Visio keeps in the file but hides from the
        page-tab strip). Returns ``None`` when the cell is absent.

        .. versionadded:: 0.3.0
        """
        raw = self._sheet_cell_v("UIVisibility")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            try:
                return int(float(raw))
            except ValueError:
                return None

    @ui_visibility.setter
    def ui_visibility(self, value: Optional[int]) -> None:
        if value is None:
            self._set_sheet_cell_v("UIVisibility", None)
            return
        self._set_sheet_cell_v("UIVisibility", str(int(value)))

    # -- print setup ----------------------------------------------------

    @lazyproperty
    def print_setup(self) -> "PrintSetup":
        """:class:`~vsdx.print_setup.PrintSetup` proxy for this page.

        Exposes the page-scope print cells (orientation, paper size,
        margins, centering, tile scale) as typed properties. The
        proxy is always returned — it walks the underlying
        ``<PageSheet>`` on every access, so missing cells read as
        ``None`` and writes materialise cells on demand.

        .. versionadded:: 0.3.0
        """
        # Local import dodges the page <-> print_setup cycle; the
        # module imports :class:`Page` for type-checking only.
        from vsdx.print_setup import PrintSetup

        return PrintSetup(self)

    # -- shape tree -----------------------------------------------------

    @lazyproperty
    def shapes(self) -> ShapeTree:
        """:class:`ShapeTree` over this page's ``<PageContents>``."""
        return ShapeTree(self._page_part.element, self)

    def next_shape_id(self) -> int:
        """Allocate a fresh ``@ID`` for a new shape on this page."""
        return self._page_part.allocate_shape_id()

    # -- layers ---------------------------------------------------------

    @lazyproperty
    def layers(self) -> "Layers":
        """:class:`~vsdx.layers.Layers` collection over this page's
        ``<Section N="Layer">``.

        Iteration yields zero :class:`~vsdx.layers.Layer` proxies when
        the page has no layer section yet — adding the first layer
        materialises the section on demand.

        .. versionadded:: 0.2.0
        """
        # Local import dodges the page <-> layers cycle; layers imports
        # vsdx.shapes.base which imports vsdx.text which imports …
        from vsdx.layers import Layers

        return Layers(self)

    # -- background-page semantics --------------------------------------

    @property
    def is_background(self) -> bool:
        """``True`` if this page is a background page (``@Background="1"``).

        Background pages are never displayed in Visio desktop's page-tab
        strip — they are only rendered when a foreground page references
        them via :attr:`background_page`. See 0.2.0 scoping doc §5.1.

        .. versionadded:: 0.2.0
        """
        val = self._element.get("Background")
        return val == "1"

    @is_background.setter
    def is_background(self, value: bool) -> None:
        if value:
            self._element.set("Background", "1")
        else:
            self._element.attrib.pop("Background", None)

    @property
    def background_page(self) -> Optional["Page"]:
        """The background page referenced by this page, or ``None``.

        Resolves the ``@BackPage`` attribute (which carries the target's
        ``@NameU``) to the live :class:`Page` instance in the parent
        :class:`Pages` collection. Returns ``None`` if the attribute is
        absent or points at a missing / non-background page.

        .. versionadded:: 0.2.0
        """
        name = self._element.get("BackPage")
        if not name:
            return None
        for page in self._parent:
            if page._element.get("NameU") == name and page.is_background:
                return page
        return None

    @background_page.setter
    def background_page(self, value: Optional["Page"]) -> None:
        """Assign a background page to this page.

        Passes ``None`` to clear the reference. The target must be a
        background page (``is_background=True``) and must not be this
        page itself (self-reference is refused).

        :raises ValueError: when the target is not a background page,
            or when assigning a page as its own background.
        """
        if value is None:
            self._element.attrib.pop("BackPage", None)
            return
        if value is self:
            raise ValueError(
                "cannot assign a page as its own background"
            )
        if not value.is_background:
            raise ValueError(
                "target page %r is not a background page "
                "(set is_background=True first)" % value.name
            )
        target_name = value._element.get("NameU") or value.name
        if not target_name:
            raise ValueError(
                "background page has no NameU; assign a name first"
            )
        self._element.set("BackPage", target_name)

    # -- theme override -------------------------------------------------

    @property
    def theme(self) -> Optional[Theme]:
        """The theme effective on this page.

        When the page carries a direct ``RT.THEME`` relationship to a
        :class:`~vsdx.parts.theme.ThemePart` (a "per-page theme
        override" — Visio's mechanism for pages that diverge from the
        document-wide theme), this returns a :class:`Theme` proxy
        wrapping *that* part. Otherwise it falls back to the
        document-wide :attr:`~vsdx.document.VisioDocument.theme`,
        returning ``None`` only when the package has no theme at all.

        Assigning a :class:`Theme` establishes (or replaces) the
        per-page override rel. Assigning ``None`` removes the override
        rel so the page inherits the document theme again.

        .. versionadded:: 0.3.0
        """
        from ooxml_opc import RELATIONSHIP_TYPE as RT

        from vsdx.parts.theme import ThemePart

        for rel in self._page_part.rels.values():
            if rel.is_external or rel.reltype != RT.THEME:
                continue
            target = rel.target_part
            if isinstance(target, ThemePart):
                return Theme(target)
        doc = self._parent._parent  # Pages → VisioDocument
        return doc.theme

    @theme.setter
    def theme(self, value: Optional[Theme]) -> None:
        from ooxml_opc import RELATIONSHIP_TYPE as RT

        from vsdx.parts.theme import ThemePart

        # Drop any existing override rel first.
        for rId, rel in list(self._page_part.rels.items()):
            if rel.is_external or rel.reltype != RT.THEME:
                continue
            target = rel.target_part
            if isinstance(target, ThemePart):
                del self._page_part.rels[rId]
        if value is None:
            return
        if not isinstance(value, Theme):
            raise TypeError(
                "Page.theme setter expects a Theme or None, got %r" % type(value).__name__
            )
        self._page_part.relate_to(value.part, RT.THEME)

    # -- ink annotations ------------------------------------------------

    @property
    def ink_strokes(self) -> "list[InkStroke]":
        """Flat list of |InkStroke| for every ``<inkml:trace>`` on this page.

        Walks the page part's relationships for every
        :data:`ooxml_ink.RELATIONSHIP_TYPE_INK` edge, resolves each to
        its :class:`~vsdx.parts.ink.InkPart`, and enumerates the part's
        traces in document order. Traces are flattened across parts —
        the returned list does not expose which part a stroke
        originated in.

        Returns ``[]`` when the page has no ink parts or when every
        resolvable part has zero traces. Degrades to ``[]`` if the
        shared ``ooxml_ink`` package is not importable.

        .. versionadded:: 0.3.0
        """
        try:
            from ooxml_ink import RELATIONSHIP_TYPE_INK
            from ooxml_ink.oxml.inkml import CT_Ink
            from ooxml_ink.part import InkPart as _SharedInkPart

            from vsdx.ink import InkStroke
        except ImportError:
            return []

        strokes: list[InkStroke] = []
        for rel in self._page_part.rels.values():
            if rel.is_external or rel.reltype != RELATIONSHIP_TYPE_INK:
                continue
            ink_part = rel.target_part
            if not isinstance(ink_part, _SharedInkPart):
                continue
            try:
                ink_elm = ink_part.ink
            except Exception:  # noqa: BLE001  -- malformed ink survivable
                continue
            if not isinstance(ink_elm, CT_Ink):
                continue
            for trace in ink_elm.all_traces:
                strokes.append(InkStroke(trace, ink_elm))
        return strokes

    def add_ink_stroke(
        self,
        points: "list[tuple[float, float]] | list[tuple[float, float, float]]",
        pressure: "list[float] | None" = None,
        color: "str | None" = None,
        width: "float | None" = None,
    ) -> "InkStroke":
        """Append a new ink stroke to this page and return its |InkStroke| proxy.

        *points* is a non-empty list of ``(x, y)`` pairs — or 3-tuples
        ``(x, y, pressure)`` if you prefer to carry per-point pressure
        alongside the coordinates; in that case leave the *pressure*
        kwarg at its default.

        *pressure* is an optional per-point pressure list; supplying
        this instead of 3-tuples yields the same result with a cleaner
        coordinate list.

        *color* is a hex-RGB string (``"#RRGGBB"`` or ``"RRGGBB"``) and
        *width* is a nib width in pixels; either may be omitted.

        Creates — or reuses — a single ``/visio/ink/ink{n}.xml`` part
        for this page and establishes an
        :data:`~ooxml_ink.RELATIONSHIP_TYPE_INK` relationship on the
        page part. Subsequent calls to :meth:`add_ink_stroke` reuse the
        existing ink part so strokes authored in one session share a
        single InkML file — matching how Office groups strokes drawn
        during a single "pen-down to pen-up" sequence.

        Raises :class:`ValueError` when *points* is empty or when
        *pressure* is supplied with a mismatched length. Raises
        :class:`ImportError` when ``ooxml_ink`` is not installed.

        .. versionadded:: 0.3.0
        """
        if not points:
            raise ValueError("ink stroke must carry at least one point")

        from ooxml_ink import CONTENT_TYPE_INK, RELATIONSHIP_TYPE_INK

        from vsdx.ink import InkStroke
        from vsdx.parts.ink import InkPart as _VsdxInkPart
        from vsdx.parts.ink import append_trace

        # -- normalise 3-tuple (x, y, pressure) shorthand into an explicit
        # -- pressure list. Tolerates mixed shapes as long as consistent.
        if pressure is None and points and len(points[0]) >= 3:
            pressure = [float(p[2]) for p in points]
            points = [(float(p[0]), float(p[1])) for p in points]

        # -- locate the page's existing authored ink part; otherwise mint a
        # -- fresh one and wire it into the page-part rels. Only
        # -- :class:`vsdx.parts.ink.InkPart` is eligible for reuse — a bare
        # -- shared ``ooxml_ink.InkPart`` loaded from disk is treated
        # -- verbatim.
        ink_part: "_VsdxInkPart | None" = None
        for rel in self._page_part.rels.values():
            if rel.is_external or rel.reltype != RELATIONSHIP_TYPE_INK:
                continue
            candidate = rel.target_part
            if (
                isinstance(candidate, _VsdxInkPart)
                and candidate.content_type == CONTENT_TYPE_INK
            ):
                ink_part = candidate
                break

        if ink_part is None:
            ink_part = _VsdxInkPart.new(self._page_part.package)
            self._page_part.relate_to(ink_part, RELATIONSHIP_TYPE_INK)

        trace = append_trace(
            ink_part,
            [(float(p[0]), float(p[1])) for p in points],
            pressure=pressure,
            color=color,
            width=width,
        )
        return InkStroke(trace, ink_part.ink)

    # -- navigation -----------------------------------------------------

    @property
    def part(self):  # type: ignore[override]
        return self._page_part


class Pages(ParentedElementProxy):
    """Collection of pages on a :class:`~vsdx.document.VisioDocument`."""

    def __init__(self, pages_part: "PagesPart", parent: "VisioDocument") -> None:
        super().__init__(pages_part.element, parent)
        self._pages_part = pages_part
        self._page_cache: list[Page] = []
        self._rebuild_cache()

    # -- container ------------------------------------------------------

    def __iter__(self) -> Iterator[Page]:
        return iter(self._page_cache)

    def __len__(self) -> int:
        return len(self._page_cache)

    def __getitem__(self, idx: int) -> Page:
        return self._page_cache[idx]

    # -- authoring ------------------------------------------------------

    def add_page(
        self,
        name: Optional[str] = None,
        width: float = 8.5,
        height: float = 11.0,
    ) -> Page:
        """Add a new page and return its :class:`Page` proxy."""
        name = name or f"Page-{len(self._page_cache) + 1}"
        page_part = self._pages_part.add_page_part(name)
        page_part.page_element.set("PageWidth", _fmt(width))
        page_part.page_element.set("PageHeight", _fmt(height))
        page = Page(page_part, self)
        self._page_cache.append(page)
        return page

    def add_background_page(
        self,
        name: Optional[str] = None,
        width: float = 8.5,
        height: float = 11.0,
    ) -> Page:
        """Add a new background page and return its :class:`Page` proxy.

        The page is created with ``@Background="1"`` — use
        :attr:`Page.background_page` on a foreground page to wire the
        reference. See 0.2.0 scoping doc §5.4.

        .. versionadded:: 0.2.0
        """
        # Default the name to a non-conflicting background-page name.
        if name is None:
            base = "VBackground"
            existing = {p._element.get("NameU") for p in self._page_cache}
            idx = 1
            while f"{base}-{idx}" in existing:
                idx += 1
            name = f"{base}-{idx}"
        page = self.add_page(name=name, width=width, height=height)
        page.is_background = True
        return page

    # -- filter views ---------------------------------------------------

    @property
    def foreground(self) -> "list[Page]":
        """All non-background pages, in source order.

        .. versionadded:: 0.2.0
        """
        return [p for p in self._page_cache if not p.is_background]

    @property
    def backgrounds(self) -> "list[Page]":
        """All background pages, in source order.

        .. versionadded:: 0.2.0
        """
        return [p for p in self._page_cache if p.is_background]

    # -- dangling-reference cleanup -------------------------------------

    def remove(self, page: Page) -> None:
        """Remove *page* from the document, clearing dangling references.

        Matches the scoping-doc open-question #2 recommendation (b) —
        when a background page is removed, every foreground page that
        referenced it has its ``@BackPage`` attribute cleared. No
        exception is raised on dangling-cleanup.

        .. versionadded:: 0.2.0
        """
        if page not in self._page_cache:
            raise ValueError("page is not in this collection")
        name_u = page._element.get("NameU")
        # Clear dangling BackPage references on every surviving page.
        if page.is_background and name_u:
            for other in self._page_cache:
                if other is page:
                    continue
                if other._element.get("BackPage") == name_u:
                    other._element.attrib.pop("BackPage", None)
        # Detach the <Page> index entry from pages.xml.
        idx_el = page._element
        parent_el = idx_el.getparent()
        if parent_el is not None:
            parent_el.remove(idx_el)
        # Drop the cache entry. (Full package-rels cleanup for the part
        # is a follow-up; the 0.2.0 semantic focus is on dangling
        # name-references rather than part-level rel pruning.)
        self._page_cache.remove(page)

    # -- internal -------------------------------------------------------

    def _rebuild_cache(self) -> None:
        self._page_cache = [
            Page(p, self) for p in getattr(self._pages_part, "_page_parts", [])
        ]


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return ("%f" % value).rstrip("0").rstrip(".")


__all__ = ["Page", "Pages"]
