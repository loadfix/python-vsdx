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

from typing import TYPE_CHECKING, Iterable, Iterator, Optional

from vsdx.shapes.shapetree import ShapeTree
from vsdx.shared import ParentedElementProxy, PartElementProxy
from vsdx.theme import Theme
from vsdx.util import Inches, Length, lazyproperty

if TYPE_CHECKING:
    from vsdx.connection_points import ConnectionPoint
    from vsdx.container import Container
    from vsdx.document import VisioDocument
    from vsdx.ink import InkStroke
    from vsdx.layers import Layers
    from vsdx.oxml._stubs import CT_Cell, CT_Page, CT_PageSheet  # TODO(vsdx/track-1)
    from vsdx.parts._stubs import PagePart, PagesPart  # TODO(vsdx/track-2)
    from vsdx.print_setup import PrintSetup
    from vsdx.shapes.base import Shape
    from vsdx.shapes.connector import Connector


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

    # -- ShapeSheet formula recomputation -------------------------------

    def recompute(self) -> int:
        """Re-evaluate every cell with a formula on every shape on this page.

        Iterates the page's :class:`ShapeTree` and calls
        :meth:`vsdx.shapes.base.Shape.recompute` on each shape; nested
        group-shape children are walked recursively. Returns the total
        number of cells whose ``@V`` actually changed across the page.

        .. versionadded:: 0.3.0
        """

        return _recompute_shape_tree(self.shapes)

    # -- high-level connector authoring --------------------------------

    def connect(
        self,
        source_shape: "Shape",
        target_shape: "Shape",
        source_point: "Optional[ConnectionPoint]" = None,
        target_point: "Optional[ConnectionPoint]" = None,
        connector_master: str = "Dynamic connector",
    ) -> "Connector":
        """Drop a connector shape linking *source_shape* to *target_shape*.

        High-level authoring surface on top of
        :meth:`ShapeTree.add_connector`.  The instantiated connector is
        an instance of *connector_master* (default: the built-in
        ``"Dynamic connector"`` master).  Glue is written into the
        page's ``<Connects>`` element as two ``<Connect>`` entries
        (``BeginX`` → source, ``EndX`` → target).

        *source_point* / *target_point* control which anchor on each
        shape the glue references:

        - :class:`None` (default) — nearest-edge auto-pick. If the
          shape has connection points, the one closest to the opposite
          shape's centre-pin is chosen; otherwise the endpoint glues to
          the centre-pin (``ToCell="PinX"``).
        - A specific :class:`ConnectionPoint` — written verbatim as
          ``ToCell="Connections.X<index>"``.

        The connector's ``BeginX`` / ``BeginY`` / ``EndX`` / ``EndY``
        cells are materialised to match the chosen endpoints' world
        coordinates, so the emitted file renders without a Visio
        reroute pass.

        .. versionadded:: 0.3.0
        """
        from vsdx.shapes.connector import (
            Connector,
            _connection_point_world_xy,
        )

        shape_el = self.shapes._element.shapes_element.add_shape(
            master_name_u=connector_master
        )
        shape_el.shape_id = self.next_shape_id()
        conn = Connector(shape_el, self.shapes)

        # Auto-pick nearest-edge points when not specified.
        if source_point is None:
            source_point = _nearest_connection_point(source_shape, target_shape)
        if target_point is None:
            target_point = _nearest_connection_point(target_shape, source_shape)

        # Write begin / end cells from the (possibly resolved) endpoints.
        if source_point is not None:
            bx, by = _connection_point_world_xy(source_shape, source_point)
        else:
            bx, by = float(source_shape.pin_x), float(source_shape.pin_y)
        if target_point is not None:
            ex, ey = _connection_point_world_xy(target_shape, target_point)
        else:
            ex, ey = float(target_shape.pin_x), float(target_shape.pin_y)
        conn.begin_x = bx
        conn.begin_y = by
        conn.end_x = ex
        conn.end_y = ey

        # Write the two <Connect> glue entries.  When glued to a
        # specific connection point we use the ``Connections.X<n>``
        # cell-reference form; centre-pin glue uses the simpler
        # ``ToCell="PinX"`` form.
        connects = self.shapes._element.connects_element
        source_to_cell = (
            "Connections.X%d" % source_point.index
            if source_point is not None
            else "PinX"
        )
        target_to_cell = (
            "Connections.X%d" % target_point.index
            if target_point is not None
            else "PinX"
        )
        connects.add_connect(
            from_sheet=str(conn.shape_id),
            to_sheet=str(source_shape.shape_id),
            from_cell="BeginX",
            to_cell=source_to_cell,
        )
        connects.add_connect(
            from_sheet=str(conn.shape_id),
            to_sheet=str(target_shape.shape_id),
            from_cell="EndX",
            to_cell=target_to_cell,
        )
        return conn

    # -- container shapes ----------------------------------------------

    def add_container(
        self,
        title: Optional[str] = None,
        title_position: str = "top-left",
        style: str = "rounded",
        border_color=None,
        fill_color=None,
        label_style: str = "plain",
        at: "tuple[float, float]" = (1.0, 1.0),
        size: "tuple[float, float]" = (4.0, 3.0),
        auto_resize: bool = False,
    ) -> "Container":
        """Add a container shape to this page and return its proxy.

        A container is a labelled rounded rectangle that encloses
        other shapes — heavily used for AWS-VPC-style architecture
        diagrams where logical zones (VPC, subnet, security group)
        wrap a cluster of resources. The returned :class:`Container`
        accepts subsequent shapes either via the ``container=`` kwarg
        on :meth:`ShapeTree.add_shape` (top-level shapes that should
        live inside the container) or via :meth:`Container.add_container`
        (nested containers).

        :param title: optional label rendered at *title_position*.
        :param title_position: one of ``"top-left"``, ``"top"``,
            ``"top-right"``, ``"bottom"``, ``"banner"``.
        :param style: ``"rounded"`` or ``"sharp"`` outline.
        :param border_color: hex string, ``(r, g, b)`` tuple, or a
            theme-scheme slot name like ``"accent1"``. Theme slots
            resolve against the document's theme at author time.
        :param fill_color: same accepted forms as *border_color*.
        :param label_style: ``"plain"`` / ``"banner"`` / ``"tab"``.
        :param at: page-scoped centre-pin in inches.
        :param size: ``(width, height)`` in inches.
        :param auto_resize: when ``True``, the container expands to
            fit its members at save time. See
            :meth:`Container.fit_to_members` for the standalone hook.

        .. versionadded:: 0.3.0
        """
        from vsdx.container import _author_container_into_tree

        return _author_container_into_tree(
            tree=self.shapes,
            page=self,
            title=title,
            title_position=title_position,
            style=style,
            border_color=border_color,
            fill_color=fill_color,
            label_style=label_style,
            at=at,
            size=size,
            auto_resize=auto_resize,
        )

    @property
    def containers(self) -> "list[Container]":
        """Top-level :class:`Container` shapes on this page, in document order.

        Walks the page's :class:`ShapeTree` and yields one
        :class:`Container` proxy per shape whose marker cell is set —
        i.e. shapes authored by :meth:`add_container` and shapes
        reloaded from a ``.vsdx`` that carries the same metadata.
        Nested containers (those inside another container) are *not*
        included; iterate the parent's :attr:`Container.member_shapes`
        to find them.

        .. versionadded:: 0.3.0
        """
        from vsdx.container import Container

        out: list[Container] = []
        for shape in self.shapes:
            if isinstance(shape, Container):
                out.append(shape)
        return out

    def _apply_container_auto_resize(self) -> None:
        """Walk every container on the page and run :meth:`fit_to_members`
        on those whose :attr:`auto_resize` is ``True``.

        Called from :meth:`vsdx.document.VisioDocument.save` so the
        on-disk container always wraps its current membership without
        the caller having to track size manually.

        Containers are processed innermost-first so a parent that also
        carries ``auto_resize=True`` sees the resized children when it
        runs its own fit pass. Children of a non-auto-resize parent
        still resize themselves.
        """
        from vsdx.container import Container

        # Collect containers depth-first so deepest run first.
        ordered: list[Container] = []

        def _walk(c: "Container") -> None:
            for member in c.member_shapes:
                if isinstance(member, Container):
                    _walk(member)
            ordered.append(c)

        for c in self.containers:
            _walk(c)
        for c in ordered:
            if c.auto_resize:
                c.fit_to_members()

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

    def add_layer(
        self,
        name: str,
        visible: bool = True,
        print_: bool = True,
        color: str = "Themed",
    ):
        """Append a new layer to this page and return its proxy.

        Thin convenience wrapper over ``page.layers.add(...)`` — provided
        so the common case ("add one named layer to a page") reads
        linearly on the :class:`Page` surface instead of dipping through
        the :class:`~vsdx.layers.Layers` collection. The *print_* kwarg
        avoids shadowing the built-in ``print``.

        .. versionadded:: 0.3.0
        """
        # NB: Layers.add spells the printability kwarg as ``print=`` to
        # match the Visio cell-name. We expose the PEP-8-friendly
        # ``print_`` here and translate.
        return self.layers.add(
            name, visible=visible, print=print_, color=color
        )

    def layer(self, name: str):
        """Return the layer on this page named *name*, or ``None``.

        Equivalent to ``page.layers.get(name)`` — the short spelling is
        convenient when passing a layer to ``Shape.add_to_layer(...)``.

        .. versionadded:: 0.3.0
        """
        return self.layers.get(name)

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

    @property
    def background(self) -> Optional["Page"]:
        """Short spelling for :attr:`background_page`.

        Reads / writes the same ``@BackPage`` attribute. The grammatical
        ``page.background = back`` reads naturally next to
        ``page.is_background = True`` so it's the spelling we
        recommend in 0.3.0+.

        Assigning ``None`` clears the reference; assigning a non-
        background :class:`Page` raises :class:`ValueError`.

        .. versionadded:: 0.3.0
        """
        return self.background_page

    @background.setter
    def background(self, value: Optional["Page"]) -> None:
        self.background_page = value

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

    def set_effect_variant(self, index: int) -> None:
        """Apply one of the theme's three effect variants to every shape.

        :param index: ``0`` / ``1`` / ``2`` — a 0-based index into
            :attr:`Theme.effect_variants` (subtle / moderate / intense).

        For every :class:`~vsdx.shapes.base.Shape` on this page, writes
        (or updates) a ``<Cell N="QuickStyleEffectMatrix" V="<n>">``
        where ``<n>`` is the 1-based preset number corresponding to
        *index* — the value Visio stores to look up the selected
        effect style in the theme's ``a:effectStyleLst``.

        Shapes with no effective theme still accept the write; the
        Visio renderer falls back to its default effect chain when the
        referenced preset is out of range in the theme. Group-shape
        children are *not* traversed — only the top-level shapes on the
        page receive the update. Callers that want deep application can
        walk the shape tree manually.

        Raises:

        - :class:`TypeError` if *index* is not an ``int``;
        - :class:`ValueError` if *index* is outside ``0 <= index < 3``.

        .. versionadded:: 0.4.0
        """
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError(
                "effect variant index must be an int, got %r"
                % type(index).__name__
            )
        if index < 0 or index >= 3:
            raise ValueError(
                "effect variant index out of range: %d (expected 0, 1, or 2)"
                % index
            )
        preset = index + 1
        for shape in self.shapes:
            cell = shape._element.get_or_add_cell("QuickStyleEffectMatrix")
            cell.set("V", str(preset))

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

    # -- diagram lint ---------------------------------------------------

    def lint(
        self,
        rules: "Optional[Iterable[str]]" = None,
    ) -> "list":
        """Inspect this page for diagram-quality issues.

        Returns a list of :class:`vsdx.lint.Finding` instances — one per
        rule violation found. *rules* is an optional iterable of rule-id
        strings restricting which checks run; the default runs every
        rule in :data:`vsdx.lint.DEFAULT_RULES`.

        Rule catalogue (severity in brackets):

        - ``shape-overlap`` (error) — two shapes overlap by more than
          5 % of the smaller's area.
        - ``disconnected-node`` (warning) — a non-connector shape with
          neither incoming nor outgoing connectors.
        - ``unlabeled-connector`` (warning) — connector with empty text.
        - ``connector-crossings`` (info) — five or more line crossings
          on the page.
        - ``inconsistent-shape-size`` (warning) — within one master /
          shape-type, area varies by more than 2x.
        - ``off-grid`` (info) — pin coordinates not aligned to the page's
          grid spacing (only fires when ``XGridSpacing`` /
          ``YGridSpacing`` is set).
        - ``text-overflow`` (warning) — shape text estimated to exceed
          the shape's height at the default 10-pt font.
        - ``label-readability`` (info) — label point size below 8 pt.

        Findings are returned in rule-declaration order, then in
        document order within each rule. Unknown rule-ids in *rules* are
        silently ignored — forward-compatible with rule names from a
        future package version.

        .. versionadded:: 0.3.0
        """
        from vsdx.lint import lint as _lint

        return _lint(self, rules=rules)

    # -- SVG export -----------------------------------------------------

    def to_svg(self, path: Optional[str] = None) -> str:
        """Render this page as a minimal standalone SVG document.

        When *path* is ``None`` (default) the SVG is returned as a
        string. Passing *path* writes the document to that location
        (UTF-8, overwriting any existing file) and also returns the
        same string.

        Only the primitive shape kinds ship today — rectangles,
        ellipses, plain text, and straight-line connectors. Anything
        else renders as a zero-size placeholder ``<rect>`` with an
        ``<!-- unsupported shape -->`` comment so the export
        continues end-to-end. See :mod:`vsdx.svg` for the full
        conventions, coordinate translation (Visio bottom-left-in →
        SVG top-left-px at 96 DPI), and the security note on text
        escaping.

        .. versionadded:: 0.2.0
        """
        # Deferred import — svg.page_to_svg reaches back into shape
        # subclasses, which ultimately import from :class:`Page`.
        from vsdx.svg import page_to_svg, write_page_svg

        if path is None:
            return page_to_svg(self)
        return write_page_svg(self, path)

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
        background: bool = False,
    ) -> Page:
        """Add a new page and return its :class:`Page` proxy.

        :param name: optional ``@NameU`` for the page; defaults to
            ``"Page-N"`` (or ``"VBackground-N"`` when *background* is
            ``True`` and *name* is ``None``).
        :param width: page width in inches (default ``8.5``).
        :param height: page height in inches (default ``11.0``).
        :param background: when ``True``, the page is created with
            ``@Background="1"`` so it can be referenced by foreground
            pages via :attr:`Page.background`. See 0.2.0 scoping doc
            §5.1. ``[Added in 0.3.0]``.

        .. versionchanged:: 0.3.0
            Added the *background* keyword argument so background-page
            authoring matches the foreground spelling and avoids the
            two-call ``add_page(...)`` + ``page.is_background = True``
            dance for the common case.
        """
        if background and name is None:
            # Match :meth:`add_background_page`'s auto-naming rule so
            # ``add_page(background=True)`` and ``add_background_page()``
            # converge on the same default identity for callers that
            # mix the two spellings.
            base = "VBackground"
            existing = {p._element.get("NameU") for p in self._page_cache}
            idx = 1
            while f"{base}-{idx}" in existing:
                idx += 1
            name = f"{base}-{idx}"
        else:
            name = name or f"Page-{len(self._page_cache) + 1}"
        page_part = self._pages_part.add_page_part(name)
        page_part.page_element.set("PageWidth", _fmt(width))
        page_part.page_element.set("PageHeight", _fmt(height))
        page = Page(page_part, self)
        if background:
            page.is_background = True
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
        :attr:`Page.background` (or :attr:`Page.background_page`) on a
        foreground page to wire the reference. See 0.2.0 scoping doc
        §5.4.

        Equivalent to :meth:`add_page` ``(background=True)`` introduced
        in 0.3.0; both call sites converge on the same auto-naming
        rule (``VBackground-1`` / ``-2`` / …).

        .. versionadded:: 0.2.0
        """
        return self.add_page(
            name=name, width=width, height=height, background=True
        )

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


def _nearest_connection_point(
    shape: "Shape", other: "Shape"
) -> "Optional[ConnectionPoint]":
    """Return the connection point on *shape* closest to *other*'s centre-pin.

    Returns ``None`` when *shape* has no connection points (the caller
    then falls back to centre-pin glue).  Distance is scored in page
    coordinates using the simple ``LocPinX/Y = size/2`` assumption —
    see :func:`vsdx.shapes.connector._connection_point_world_xy`.
    """
    from vsdx.shapes.connector import _connection_point_world_xy

    points = list(shape.connection_points)
    if not points:
        return None
    other_x = float(other.pin_x)
    other_y = float(other.pin_y)
    best: "Optional[ConnectionPoint]" = None
    best_d2 = float("inf")
    for point in points:
        wx, wy = _connection_point_world_xy(shape, point)
        dx = wx - other_x
        dy = wy - other_y
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2 = d2
            best = point
    return best


def _recompute_shape_tree(shape_tree) -> int:
    """Walk *shape_tree* recursively, summing ``recompute`` change counts.

    Module-level helper because :class:`Page` and :class:`VisioDocument`
    both delegate the work to a shape iterator. Nested group-shape
    children carry their own ``<Cell>`` grids and are reachable via
    :attr:`Shape.shapes` on the group; we descend into those too.
    """

    total = 0
    for shape in shape_tree:
        total += shape.recompute()
        # Group shapes carry nested children — descend so their cells
        # are recomputed too. ``getattr`` keeps this safe for the
        # (most common) leaf-shape case where ``shapes`` is absent.
        nested_el = getattr(shape._element, "shapes", None)
        if nested_el is None:
            continue
        # Build a lightweight iterator over the nested shape tree by
        # constructing transient :class:`Shape` proxies. We deliberately
        # don't use the ``GroupShape.children`` API to avoid an import
        # cycle; the proxy is only needed for its ``recompute()`` and
        # ``_element`` attributes, which the base class supplies.
        from vsdx.shapes.base import Shape as _Shape

        for nested_el2 in nested_el.shape_lst:
            nested_shape = _Shape(nested_el2, shape_tree)
            total += nested_shape.recompute()
    return total


__all__ = ["Page", "Pages"]
