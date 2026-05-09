# pyright: reportImportCycles=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUntypedBaseClass=false
# pyright: reportMissingTypeStubs=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportMissingImports=false
# pyright: reportPrivateUsage=false
"""``<VisioDocument>`` — root of ``/visio/document.xml``.

Per MS Learn's schema map, ``<VisioDocument>`` contains (in order):

- ``<DocumentProperties>`` — metadata (*note*: the real metadata
  lives in ``/docProps/*.xml``; this element holds Visio-specific
  extras like ``PreviewPicture``).
- ``<DocumentSettings>`` — document-wide behaviour flags.
- ``<Colors>`` — color palette entries.
- ``<FaceNames>`` — font face name table.
- ``<StyleSheets>`` — default line/fill/text style sheets.
- ``<DocumentSheet>`` — document-level ShapeSheet (units, scale,
  etc.).
- ``<EventList>`` — Visio event handlers.
- ``<HeaderFooter>`` — print headers/footers.

Visio's StyleSheets sub-tree is **required for the document to open
cleanly** — the conformance constraint in CLAUDE.md §3 forbids
omitting it on write.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    XsdString,
    XsdUnsignedInt,
    ZeroOrMore,
    ZeroOrOne,
)

__all__ = [
    "CT_Colors",
    "CT_DocumentProperties",
    "CT_DocumentSettings",
    "CT_DocumentSheet",
    "CT_EventList",
    "CT_FaceNames",
    "CT_StyleSheet",
    "CT_StyleSheets",
    "CT_VisioDocument",
]


class CT_DocumentProperties(BaseOxmlElement):
    """``<DocumentProperties>`` — Visio-specific document metadata.

    Real core-metadata properties (title, author, subject, …) live in
    ``/docProps/core.xml`` and are handled by
    ``python-ooxml-docprops``. This element holds only Visio-extras
    like ``<PreviewPicture>`` and ``<TimeCreated>``.

    .. versionadded:: 0.1.0
    """


class CT_DocumentSettings(BaseOxmlElement):
    """``<DocumentSettings>`` — document-wide behaviour flags.

    Attributes like ``@TopPage`` (default page to open on), colour
    defaults, display flags. The element also holds singleton cells
    (``GlueSettings``, ``SnapSettings``, ``DynamicGridEnabled`` …) in
    the same Cell/@N/@V pattern.

    .. versionadded:: 0.1.0
    """

    top_page = OptionalAttribute("TopPage", XsdUnsignedInt)
    default_text_style = OptionalAttribute("DefaultTextStyle", XsdUnsignedInt)
    default_line_style = OptionalAttribute("DefaultLineStyle", XsdUnsignedInt)
    default_fill_style = OptionalAttribute("DefaultFillStyle", XsdUnsignedInt)
    default_guide_style = OptionalAttribute("DefaultGuideStyle", XsdUnsignedInt)

    cell = ZeroOrMore("vsdx:Cell")


class CT_Colors(BaseOxmlElement):
    """``<Colors>`` — document colour palette.

    .. versionadded:: 0.1.0
    """

    # Auto-generates ``colorEntry_lst`` getter.
    colorEntry = ZeroOrMore("vsdx:ColorEntry")


class CT_FaceNames(BaseOxmlElement):
    """``<FaceNames>`` — font face-name table.

    .. versionadded:: 0.1.0
    """

    # Auto-generates ``face_lst`` getter.
    face = ZeroOrMore("vsdx:Face")


class CT_StyleSheet(BaseOxmlElement):
    """A named stylesheet inside ``<StyleSheets>``.

    Identifying attributes:

    - ``@ID`` — stylesheet ID (referenced by ``Shape/@LineStyle``
      etc.).
    - ``@NameU`` / ``@Name`` — stylesheet name.
    - ``@LineStyle`` / ``@FillStyle`` / ``@TextStyle`` — IDs of
      parent stylesheets (stylesheets inherit from each other like
      shapes inherit from masters).

    Carries its own singleton cells + sections (same Cell/Row/Section
    vocabulary as shapes).

    .. versionadded:: 0.1.0
    """

    id_ = OptionalAttribute("ID", XsdUnsignedInt)
    name = OptionalAttribute("Name", XsdString)
    name_u = OptionalAttribute("NameU", XsdString)
    is_custom_name = OptionalAttribute("IsCustomName", XsdString)
    is_custom_name_u = OptionalAttribute("IsCustomNameU", XsdString)
    line_style = OptionalAttribute("LineStyle", XsdUnsignedInt)
    fill_style = OptionalAttribute("FillStyle", XsdUnsignedInt)
    text_style = OptionalAttribute("TextStyle", XsdUnsignedInt)
    unique_id = OptionalAttribute("UniqueID", XsdString)

    cell = ZeroOrMore("vsdx:Cell")
    section = ZeroOrMore("vsdx:Section")


class CT_StyleSheets(BaseOxmlElement):
    """``<StyleSheets>`` — required root-level stylesheet collection.

    A conformant ``/visio/document.xml`` **must** include at least
    the three default stylesheets (LineStyle, FillStyle, TextStyle)
    that Visio desktop picks up as fallbacks. Omitting the
    collection causes "the file is corrupt" errors on open — see
    ``CLAUDE.md`` §"Three conformance constraints".

    .. versionadded:: 0.1.0
    """

    # Auto-generates ``styleSheet_lst`` getter.
    styleSheet = ZeroOrMore("vsdx:StyleSheet")


class CT_DocumentSheet(BaseOxmlElement):
    """The document's own ShapeSheet (defaults for units, scale, …).

    Same Cell/Section mechanics as :class:`CT_PageSheet`.

    .. versionadded:: 0.1.0
    """

    line_style = OptionalAttribute("LineStyle", XsdUnsignedInt)
    fill_style = OptionalAttribute("FillStyle", XsdUnsignedInt)
    text_style = OptionalAttribute("TextStyle", XsdUnsignedInt)
    unique_id = OptionalAttribute("UniqueID", XsdString)

    cell = ZeroOrMore("vsdx:Cell")
    section = ZeroOrMore("vsdx:Section")


class CT_EventList(BaseOxmlElement):
    """``<EventList>`` — Visio event handlers (legacy macro hooks).

    Not meaningful in ``.vsdx`` (macro content is excluded); the
    element is preserved round-trip only.

    .. versionadded:: 0.1.0
    """


class CT_VisioDocument(BaseOxmlElement):
    """Root of ``/visio/document.xml``.

    Attributes (per MS Learn ``VisioDocument_Type``):

    - ``@xml:space`` — typically omitted or ``default``.
    - ``@key`` / ``@metric`` / ``@start`` — document-flag attributes
      Visio emits on certain document versions; stored opaquely.
    - ``@DocLangID`` — BCP-47 or LCID for the document language.
    - ``@buildnum`` — Visio build number (for provenance).
    - ``@version`` — schema version, typically ``16.0``.

    .. versionadded:: 0.1.0
    """

    key = OptionalAttribute("key", XsdString)
    metric = OptionalAttribute("metric", XsdString)
    start = OptionalAttribute("start", XsdString)
    doc_lang_id = OptionalAttribute("DocLangID", XsdString)
    buildnum = OptionalAttribute("buildnum", XsdString)
    version = OptionalAttribute("version", XsdString)

    documentProperties = ZeroOrOne("vsdx:DocumentProperties")
    documentSettings = ZeroOrOne("vsdx:DocumentSettings")
    colors = ZeroOrOne("vsdx:Colors")
    faceNames = ZeroOrOne("vsdx:FaceNames")
    styleSheets = ZeroOrOne("vsdx:StyleSheets")
    documentSheet = ZeroOrOne("vsdx:DocumentSheet")
    eventList = ZeroOrOne("vsdx:EventList")
    # ``<Section>`` children at document root — primarily ``N="DataGraphic"``
    # (one section per data-graphic definition, per MS Learn's DataGraphic
    # reference). Auto-generates a ``section_lst`` getter on this class.
    # Added 0.2.0 dev — R8-2.
    section = ZeroOrMore("vsdx:Section")
