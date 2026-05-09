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
