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

from typing import TYPE_CHECKING, Optional

from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VSDX_PAGE, CT_VSDX_PAGES, NS_R, RT_VISIO_PAGE
from vsdx.oxml import parse_xml, qn
from vsdx.parts._templates import DEFAULT_PAGE_XML, DEFAULT_PAGES_XML
from vsdx.parts._verbatim import VerbatimXmlPart

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class PagesPart(VerbatimXmlPart):
    """The ``/visio/pages/pages.xml`` index part.

    Singleton within a package. Content-type
    ``application/vnd.ms-visio.pages+xml``.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> PagesPart:
        """Return a new, empty pages-index part."""
        element = parse_xml(DEFAULT_PAGES_XML)
        part = cls(
            PackURI("/visio/pages/pages.xml"),
            CT_VSDX_PAGES,
            package,
            element,
        )
        # Seed the back-reference list; :attr:`_page_parts` reads it.
        part.__dict__["_page_parts_list"] = []
        return part

    @property
    def _page_parts(self) -> list[PagePart]:
        """Return the ordered list of :class:`PagePart` children.

        Back-reference list populated by :meth:`add_page_part`. For
        parts loaded from disk that never went through :meth:`new`
        the list is lazily initialised by scanning the ``RT_VISIO_PAGE``
        rels on first access.
        """
        if "_page_parts_list" not in self.__dict__:
            lst: list[PagePart] = []
            for rel in self.rels.values():
                if rel.is_external:
                    continue
                target = rel.target_part
                if isinstance(target, PagePart):
                    lst.append(target)
            self.__dict__["_page_parts_list"] = lst
        return self.__dict__["_page_parts_list"]

    def add_page_part(self, name: str) -> PagePart:
        """Mint a new :class:`PagePart`, wire it into the package graph, and return it.

        The Visio page-addition choreography is three coordinated writes:

        1. a fresh :class:`PagePart` at ``/visio/pages/page%d.xml``
           (partname from the package's numeric allocator);
        2. a ``RT_VISIO_PAGE`` relationship from this :class:`PagesPart`
           to the new :class:`PagePart` — the ``rId`` is the value that
           lands in the ``<Rel r:id=…>`` on the page-index entry;
        3. a ``<Page @ID @Name @NameU>`` entry under the
           :class:`PagesPart` root, with a ``<Rel>`` child carrying the
           ``rId`` from step 2 — this is what pins the index entry to
           the part on load.

        Ownership of that choreography lives on :class:`PagesPart`
        because the parts layer is the OPC abstraction that knows the
        relationship / partname machinery; pushing it up into the
        proxy would leak ``rId`` / ``PackURI`` concerns into the
        authoring-surface API.

        After return, the PagePart's :attr:`~PagePart.page_element`
        back-reference points at the new ``<Page>`` entry so the
        proxy layer can set ``PageWidth`` / ``PageHeight`` without
        re-traversing the index.

        .. versionadded:: 0.1.0
        """
        page_part = PagePart.new(self.package)
        rId = self.relate_to(page_part, RT_VISIO_PAGE)
        # Assign a fresh ID (1-based, monotonic within the package).
        next_id = len(self._page_parts) + 1
        page_el = self.element.makeelement(
            qn("vsdx:Page"),
            nsmap={"r": NS_R},
        )
        page_el.set("ID", str(next_id))
        page_el.set("Name", name)
        page_el.set("NameU", name)
        rel_el = self.element.makeelement(
            qn("vsdx:Rel"),
            nsmap={"r": NS_R},
        )
        rel_el.set(f"{{{NS_R}}}id", rId)
        page_el.append(rel_el)
        self.element.append(page_el)
        page_part.page_element = page_el
        self._page_parts.append(page_part)
        return page_part


class PagePart(VerbatimXmlPart):
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
        part = cls(partname, CT_VSDX_PAGE, package, element)
        part._shape_id_counter = 0  # type: ignore[attr-defined]
        return part

    @property
    def page_element(self):
        """The ``<Page>`` index entry that points at this part.

        Set by :meth:`PagesPart.add_page_part` when a part is freshly
        minted; ``None`` for parts that have not yet been indexed (e.g.
        a PagePart constructed in isolation for a test).

        The back-reference lets the proxy layer's :class:`~vsdx.page.Page`
        wrap the page *index* element (where ``PageWidth``/``PageHeight``
        live in the authoring shortcut) rather than the contents element
        (``<PageContents>``, which holds shapes instead of page
        metadata).

        .. versionadded:: 0.1.0
        """
        return self.__dict__.get("_page_element")

    @page_element.setter
    def page_element(self, value) -> None:
        self.__dict__["_page_element"] = value

    def allocate_shape_id(self) -> int:
        """Return the next fresh shape ID for this page, starting at 1.

        Visio's shape IDs are page-scoped (``<Shape ID="…">`` values are
        unique within a single ``<PageContents>`` but not across pages).
        Keeping the counter on the part means the proxy can request a
        new ID without having to scan the ``<Shapes>`` tree on each
        call — an important optimisation for large pages.

        .. versionadded:: 0.1.0
        """
        current = self.__dict__.get("_shape_id_counter", 0)
        next_id = current + 1
        self.__dict__["_shape_id_counter"] = next_id
        return next_id
