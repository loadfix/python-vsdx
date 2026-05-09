"""Visio master parts.

Two part classes live here, mirroring the page-part split:

- :class:`MastersPart` — the index at ``/visio/masters/masters.xml``
  whose root ``<Masters>`` element carries a ``<Master>`` entry per
  master (with ``@ID`` / ``@NameU`` / ``@BaseID`` / ``@UniqueID`` plus
  a ``<Rel r:id="…">`` pointer to the master-contents part and an
  optional ``<Icon>`` child).
- :class:`MasterPart` — one per master, at
  ``/visio/masters/master%d.xml``. Root element is ``<MasterContents>``
  carrying a ``<Shapes>`` tree identical in shape to the one inside a
  :class:`~vsdx.parts.page.PagePart`.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc.packuri import PackURI

from vsdx.constants import (
    CT_VSDX_MASTER,
    CT_VSDX_MASTERS,
    NS_R,
    RT_VISIO_MASTER,
)
from vsdx.oxml import parse_xml, qn
from vsdx.parts._templates import DEFAULT_MASTER_XML, DEFAULT_MASTERS_XML
from vsdx.parts._verbatim import VerbatimXmlPart

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class MastersPart(VerbatimXmlPart):
    """The ``/visio/masters/masters.xml`` index part.

    Singleton within a package. Content-type
    ``application/vnd.ms-visio.masters+xml``.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> MastersPart:
        """Return a new, empty masters-index part."""
        element = parse_xml(DEFAULT_MASTERS_XML)
        part = cls(
            PackURI("/visio/masters/masters.xml"),
            CT_VSDX_MASTERS,
            package,
            element,
        )
        part.__dict__["_master_parts_list"] = []
        return part

    @property
    def _master_parts(self) -> list[MasterPart]:
        """Return the ordered list of :class:`MasterPart` children.

        Lazily rebuilt from the ``RT_VISIO_MASTER`` rels on first
        access for parts loaded from disk (see
        :attr:`vsdx.parts.page.PagesPart._page_parts` for the
        equivalent pattern on the pages side).
        """
        if "_master_parts_list" not in self.__dict__:
            lst: list[MasterPart] = []
            for rel in self.rels.values():
                if rel.is_external:
                    continue
                target = rel.target_part
                if isinstance(target, MasterPart):
                    lst.append(target)
            self.__dict__["_master_parts_list"] = lst
        return self.__dict__["_master_parts_list"]

    def add_master_part(self, name_u: str) -> MasterPart:
        """Mint a new :class:`MasterPart`, wire it in, and return it.

        Mirrors :meth:`vsdx.parts.page.PagesPart.add_page_part` —
        three coordinated writes: fresh part, ``RT_VISIO_MASTER``
        relationship, ``<Master>`` index entry with a ``<Rel>`` child
        pointing at the new part. The ``@ID`` / ``@NameU`` / ``@Name``
        attributes on the new ``<Master>`` all take *name_u*; the
        distinction between Name and NameU is irrelevant at 0.1.0
        because we don't support localised master names yet.

        The PaguePart's :attr:`~MasterPart.master_element` back-reference
        points at the new ``<Master>`` entry so the proxy layer's
        :class:`~vsdx.master.Master` wraps the index entry (the element
        carrying identifier attributes) rather than the contents element
        (``<MasterContents>``, which only holds the shape-tree).

        .. versionadded:: 0.1.0
        """
        master_part = MasterPart.new(self.package)
        rId = self.relate_to(master_part, RT_VISIO_MASTER)
        next_id = len(self._master_parts) + 1
        master_el = self.element.makeelement(
            qn("vsdx:Master"),
            nsmap={"r": NS_R},
        )
        master_el.set("ID", str(next_id))
        master_el.set("Name", name_u)
        master_el.set("NameU", name_u)
        rel_el = self.element.makeelement(
            qn("vsdx:Rel"),
            nsmap={"r": NS_R},
        )
        rel_el.set(f"{{{NS_R}}}id", rId)
        master_el.append(rel_el)
        self.element.append(master_el)
        master_part.master_element = master_el
        self._master_parts.append(master_part)
        return master_part


class MasterPart(VerbatimXmlPart):
    """A ``/visio/masters/master%d.xml`` per-master part.

    Content-type ``application/vnd.ms-visio.master+xml``.
    """

    _PARTNAME_TMPL = "/visio/masters/master%d.xml"

    @classmethod
    def new(cls, package: OpcPackage) -> MasterPart:
        """Return a new, empty master-contents part with a package-
        unique partname.
        """
        partname = package.next_partname(cls._PARTNAME_TMPL)
        element = parse_xml(DEFAULT_MASTER_XML)
        return cls(partname, CT_VSDX_MASTER, package, element)

    @property
    def master_element(self):
        """The ``<Master>`` index entry that points at this part.

        Mirror of :attr:`vsdx.parts.page.PagePart.page_element` —
        populated by :meth:`MastersPart.add_master_part` at
        authoring time, ``None`` for parts constructed in isolation.

        .. versionadded:: 0.1.0
        """
        return self.__dict__.get("_master_element")

    @master_element.setter
    def master_element(self, value) -> None:
        self.__dict__["_master_element"] = value
