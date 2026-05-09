"""Visio data-recordset part — ``/visio/datarecordsets/datarecordset%d.xml``.

One part per recordset. Content-type
``application/vnd.ms-visio.dataRecordSets+xml`` — registered on the
shared :class:`~ooxml_opc.PartFactory` table by :func:`vsdx.package.
register_visio_parts`.

Subclasses :class:`~vsdx.parts._verbatim.VerbatimXmlPart` so an
unmodified round-trip preserves the on-disk bytes byte-for-byte —
important because the payload encodes credentials in the ADO
connection string and any serialiser-induced whitespace / quoting
drift would invalidate Visio desktop's data-source refresh.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vsdx.constants import CT_VSDX_DATARECORDSETS
from vsdx.parts._verbatim import VerbatimXmlPart

if TYPE_CHECKING:
    pass


__all__ = ["DataRecordsetsPart"]


class DataRecordsetsPart(VerbatimXmlPart):
    """One ``/visio/datarecordsets/datarecordset%d.xml`` part.

    Content-type is the shared Visio recordset content-type constant
    :data:`~vsdx.constants.CT_VSDX_DATARECORDSETS`. The part carries a
    root ``<DataRecordset>`` element in the Visio core namespace;
    structure is walked lazily by :class:`vsdx.data_recordsets.
    DataRecordset` — this class only owns the blob and its partname.

    Partname template: ``/visio/datarecordsets/datarecordset%d.xml``
    with ``%d`` minted via :meth:`~ooxml_opc.package.OpcPackage.
    next_partname` at authoring time. For 0.2.0 we only *load* existing
    recordsets; ``new()`` is intentionally absent until R11-ish
    authoring lands.
    """

    _PARTNAME_TMPL = "/visio/datarecordsets/datarecordset%d.xml"

    # All the behaviour we need is inherited from VerbatimXmlPart:
    # load (blob capture + fingerprint), blob (mutation-aware return),
    # part_type_for registration (via vsdx.package.register_visio_parts).
    #
    # The content_type constant is referenced here purely to make the
    # wiring contract explicit for future maintainers; the package map
    # is the active registration point.
    CONTENT_TYPE = CT_VSDX_DATARECORDSETS
