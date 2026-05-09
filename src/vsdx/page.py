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
from vsdx.util import Inches, Length, lazyproperty

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.layers import Layers
    from vsdx.oxml._stubs import CT_Page  # TODO(vsdx/track-1)
    from vsdx.parts._stubs import PagePart, PagesPart  # TODO(vsdx/track-2)


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
