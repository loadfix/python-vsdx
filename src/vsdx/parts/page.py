"""Visio page parts.

Two part classes live here:

- :class:`PagesPart` — the index at ``/visio/pages/pages.xml`` whose
  root ``<Pages>`` element carries a ``<Page>`` entry per page (with
  ``@ID`` / ``@NameU`` / a ``<Rel r:id="…">`` pointer to the page-
  contents part).
- :class:`PagePart` — one per drawing page, at
  ``/visio/pages/page%d.xml``. Root element is ``<PageContents>``
  holding the `<Shapes>` tree plus `<Connects>`.

The relationship graph: ``VisioDocumentPart`` → ``RT_VISIO_PAGES`` →
``PagesPart`` → ``RT_VISIO_PAGE`` → ``PagePart`` (one per).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc import XmlPart, parse_xml
from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VSDX_PAGE, CT_VSDX_PAGES
from vsdx.parts._templates import DEFAULT_PAGE_XML, DEFAULT_PAGES_XML

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class PagesPart(XmlPart):
    """The ``/visio/pages/pages.xml`` index part.

    Singleton within a package. Content-type
    ``application/vnd.ms-visio.pages+xml``.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> PagesPart:
        """Return a new, empty pages-index part."""
        element = parse_xml(DEFAULT_PAGES_XML)
        return cls(
            PackURI("/visio/pages/pages.xml"),
            CT_VSDX_PAGES,
            package,
            element,
        )


class PagePart(XmlPart):
    """A ``/visio/pages/page%d.xml`` per-page part.

    Content-type ``application/vnd.ms-visio.page+xml``. Partname is
    minted by the enclosing :class:`~vsdx.package.VisioPackage` via
    :meth:`~ooxml_opc.package.OpcPackage.next_partname` so sequential
    numbering holds across package-lifetime page additions / removals.
    """

    _PARTNAME_TMPL = "/visio/pages/page%d.xml"

    @classmethod
    def new(cls, package: OpcPackage) -> PagePart:
        """Return a new, empty page-contents part.

        The partname is minted via the package's partname allocator so
        parallel ``new()`` calls don't collide. The caller is
        responsible for adding a matching ``<Page>`` entry (with a
        ``<Rel r:id="…">`` to this part) on the :class:`PagesPart`.
        """
        partname = package.next_partname(cls._PARTNAME_TMPL)
        element = parse_xml(DEFAULT_PAGE_XML)
        return cls(partname, CT_VSDX_PAGE, package, element)
