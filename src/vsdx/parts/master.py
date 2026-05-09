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

from ooxml_opc import XmlPart, parse_xml
from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VSDX_MASTER, CT_VSDX_MASTERS
from vsdx.parts._templates import DEFAULT_MASTER_XML, DEFAULT_MASTERS_XML

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class MastersPart(XmlPart):
    """The ``/visio/masters/masters.xml`` index part.

    Singleton within a package. Content-type
    ``application/vnd.ms-visio.masters+xml``.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> MastersPart:
        """Return a new, empty masters-index part."""
        element = parse_xml(DEFAULT_MASTERS_XML)
        return cls(
            PackURI("/visio/masters/masters.xml"),
            CT_VSDX_MASTERS,
            package,
            element,
        )


class MasterPart(XmlPart):
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
