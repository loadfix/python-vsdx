"""Visio namespace URIs, content-type, and relationship-type constants.

Visio is **not** ECMA-standardised — the authoritative schema lives on
Microsoft Learn under the
``http://schemas.microsoft.com/office/visio/2011/1/core`` namespace,
not in the ECMA-376 corpus. See the `vsdx scoping doc
<audits/2026-05-09-vsdx-scoping.md>`_ for the full analysis.

Content-type and relationship-type strings are not yet registered in
`loadfix/python-ooxml-opc`; when they are, this module will switch to
re-exporting them. Until then we own the canonical values here.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

__all__ = [
    # -- Namespaces --
    "NS_VSDX_CORE",
    "NS_R",
    "NS_XML",
    # -- Content types --
    "CT_VSDX_DRAWING_MAIN",
    "CT_VSDX_DRAWING",
    "CT_VSDX_MACRO_DRAWING_MAIN",
    "CT_VSDX_TEMPLATE_MAIN",
    "CT_VSDX_STENCIL_MAIN",
    "CT_VSDX_PAGE",
    "CT_VSDX_PAGES",
    "CT_VSDX_MASTER",
    "CT_VSDX_MASTERS",
    "CT_VSDX_WINDOWS",
    "CT_VSDX_EXTENSIONS",
    "CT_VSDX_SOLUTIONS",
    "CT_VSDX_DATACONNECTIONS",
    "CT_VSDX_DATARECORDSETS",
    "CT_VSDX_VALIDATION",
    # -- Relationship types --
    "RT_VISIO_DOCUMENT",
    "RT_VISIO_PAGES",
    "RT_VISIO_PAGE",
    "RT_VISIO_MASTERS",
    "RT_VISIO_MASTER",
    "RT_VISIO_WINDOWS",
    "RT_VISIO_EXTENSIONS",
]


# -- namespace URIs ---------------------------------------------------------

#: Visio core namespace (no prefix in serialised XML — Visio emits
#: ``xmlns="http://schemas.microsoft.com/office/visio/2011/1/core"`` as
#: the default namespace on ``<VisioDocument>``, ``<Pages>``,
#: ``<PageContents>``, ``<MasterContents>``, ``<Masters>``,
#: ``<Windows>``). Internally this package uses the ``vsdx:`` prefix
#: for qn() resolution and nsdecls() serialisation in tests; lxml
#: normalises to the default namespace on real-world writes.
NS_VSDX_CORE = "http://schemas.microsoft.com/office/visio/2011/1/core"

#: OPC relationships namespace (prefix ``r:``). Used for ``r:id``
#: attributes on Visio's ``<Rel>`` elements inside ``<Page>`` /
#: ``<Master>``.
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

#: The XML namespace (prefix ``xml:``). Used for ``xml:space="preserve"``
#: on Visio ``<Text>`` elements.
NS_XML = "http://www.w3.org/XML/1998/namespace"


# -- content-type constants -------------------------------------------------
# Cross-verified against dave-howard/vsdx and MS Learn's schema map.
# These are the strings that will eventually land in
# `python-ooxml-opc.CONTENT_TYPE`; declared locally for 0.1.0.

CT_VSDX_DRAWING_MAIN = "application/vnd.ms-visio.drawing.main+xml"
CT_VSDX_DRAWING = "application/vnd.ms-visio.drawing+xml"
CT_VSDX_MACRO_DRAWING_MAIN = (
    "application/vnd.ms-visio.drawing.macroEnabled.main+xml"
)
CT_VSDX_TEMPLATE_MAIN = "application/vnd.ms-visio.template.main+xml"
CT_VSDX_STENCIL_MAIN = "application/vnd.ms-visio.stencil.main+xml"
CT_VSDX_PAGE = "application/vnd.ms-visio.page+xml"
CT_VSDX_PAGES = "application/vnd.ms-visio.pages+xml"
CT_VSDX_MASTER = "application/vnd.ms-visio.master+xml"
CT_VSDX_MASTERS = "application/vnd.ms-visio.masters+xml"
CT_VSDX_WINDOWS = "application/vnd.ms-visio.windows+xml"
CT_VSDX_EXTENSIONS = "application/vnd.ms-visio.extensions+xml"
CT_VSDX_SOLUTIONS = "application/vnd.ms-visio.solutions+xml"
CT_VSDX_DATACONNECTIONS = "application/vnd.ms-visio.dataConnections+xml"
CT_VSDX_DATARECORDSETS = "application/vnd.ms-visio.dataRecordSets+xml"
CT_VSDX_VALIDATION = "application/vnd.ms-visio.validation+xml"


# -- relationship-type constants --------------------------------------------
# Note the ``visio/2010/relationships/`` path — Microsoft picked the
# year of the relationship-type spec-freeze, not the schema-evolution
# year (``visio/2011/1/core``).

RT_VISIO_DOCUMENT = (
    "http://schemas.microsoft.com/visio/2010/relationships/document"
)
RT_VISIO_PAGES = "http://schemas.microsoft.com/visio/2010/relationships/pages"
RT_VISIO_PAGE = "http://schemas.microsoft.com/visio/2010/relationships/page"
RT_VISIO_MASTERS = (
    "http://schemas.microsoft.com/visio/2010/relationships/masters"
)
RT_VISIO_MASTER = (
    "http://schemas.microsoft.com/visio/2010/relationships/master"
)
RT_VISIO_WINDOWS = (
    "http://schemas.microsoft.com/visio/2010/relationships/windows"
)
RT_VISIO_EXTENSIONS = (
    "http://schemas.microsoft.com/visio/2010/relationships/extensions"
)
