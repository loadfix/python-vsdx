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
"""``<Shape>`` — the core (recursive) shape element.

A Visio shape contains any subset of:

- Singleton ``<Cell>`` children — ShapeSheet cells at the shape scope
  (``PinX`` / ``PinY`` / ``Width`` / ``Height`` / ``Angle`` / …).
- ``<Section>`` children — tabular cell collections (Geometry, Char,
  Para, Scratch, User, Property, …). Multiple sections of the same
  kind can coexist (e.g. compound Geometry paths).
- ``<Text>`` — in-shape text, with cp/pp/tp formatting runs and
  inline fields.
- ``<Data1>`` / ``<Data2>`` / ``<Data3>`` — legacy shape data blobs
  (free-text properties from Visio 5 era, still preserved).
- ``<ForeignData>`` — embedded foreign content (EMF/WMF/image data
  for foreign shapes).
- ``<Shapes>`` — nested shapes (group shapes).

Attributes carried on ``<Shape>``:

- ``@ID`` — page-scoped shape ID.
- ``@Type`` — one of ``Shape`` / ``Group`` / ``Foreign`` / ``Guide`` /
  ``Page`` (:class:`ST_ShapeType`).
- ``@Master`` — master-ID reference (when the shape is an instance of
  a master from ``/visio/masters/masters.xml``).
- ``@MasterShape`` — reference to a shape within the master (for
  instances of a sub-shape inside a group master).
- ``@NameU`` — universal (locale-invariant) shape name.
- ``@Name`` — localised shape name (display name).
- ``@UniqueID`` — optional curly-braced GUID for tracking.
- ``@LineStyle`` / ``@FillStyle`` / ``@TextStyle`` — named
  stylesheet references (integers pointing at
  ``/visio/document.xml StyleSheets``).

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

__all__ = ["CT_ForeignData", "CT_Shape", "CT_Text"]


class CT_Text(BaseOxmlElement):
    """``<Text>`` — in-shape text with inline formatting runs.

    The mixed content model is preserved verbatim at the oxml layer —
    the proxy layer (track 3) tokenises cp/pp/tp markers into a typed
    run stream.

    .. versionadded:: 0.1.0
    """

    # ``Text`` in Visio uses mixed content: text nodes interleaved
    # with ``<cp>`` / ``<pp>`` / ``<tp>`` / ``<fld>`` run markers.
    # We don't enumerate specific children here because the lxml
    # element's ``.text`` / children iteration already round-trips
    # mixed content faithfully. Future track-3 work will add typed
    # accessors on top.


class CT_ForeignData(BaseOxmlElement):
    """``<ForeignData>`` — embedded foreign content (EMF/WMF/bitmap).

    Carries the binary payload as base64-encoded text in the XML.
    ``@ForeignType`` names the payload kind (``Bitmap`` / ``Metafile``
    / ``EnhMetaFile`` / ``Object`` / ``EMF`` / …).

    .. versionadded:: 0.1.0
    """

    foreign_type = OptionalAttribute("ForeignType", XsdString)
    compression_type = OptionalAttribute("CompressionType", XsdString)
    compression_level = OptionalAttribute("CompressionLevel", XsdString)
    object_height = OptionalAttribute("ObjectHeight", XsdString)
    object_width = OptionalAttribute("ObjectWidth", XsdString)
    mapping_mode = OptionalAttribute("MappingMode", XsdString)
    extent_x = OptionalAttribute("ExtentX", XsdString)
    extent_y = OptionalAttribute("ExtentY", XsdString)
    show_as_icon = OptionalAttribute("ShowAsIcon", XsdString)


class CT_Shape(BaseOxmlElement):
    """The core Visio shape element — recursive via nested ``<Shapes>``.

    .. versionadded:: 0.1.0
    """

    # -- identifier attributes --
    id_ = OptionalAttribute("ID", XsdUnsignedInt)
    type_ = OptionalAttribute("Type", XsdString)
    master = OptionalAttribute("Master", XsdUnsignedInt)
    master_shape = OptionalAttribute("MasterShape", XsdUnsignedInt)
    name_u = OptionalAttribute("NameU", XsdString)
    name = OptionalAttribute("Name", XsdString)
    unique_id = OptionalAttribute("UniqueID", XsdString)
    # -- stylesheet references (stylesheet IDs into document.xml) --
    line_style = OptionalAttribute("LineStyle", XsdUnsignedInt)
    fill_style = OptionalAttribute("FillStyle", XsdUnsignedInt)
    text_style = OptionalAttribute("TextStyle", XsdUnsignedInt)
    # -- inheritance-delete marker (rare, but we preserve round-trip) --
    del_ = OptionalAttribute("Del", XsdString)

    # -- child elements --
    # Singleton cells ride directly on Shape (PinX, PinY, …). The
    # descriptor auto-generates a ``cell_lst`` getter on this class.
    cell = ZeroOrMore("vsdx:Cell")
    # Sections group tabular cells (Geometry, Char, Para, Scratch, …).
    # Auto-generates ``section_lst`` getter.
    section = ZeroOrMore("vsdx:Section")
    # Optional Text element.
    text = ZeroOrOne("vsdx:Text")
    # Optional ForeignData (for Type="Foreign" shapes). Auto-generates
    # a ``foreignData`` property.
    foreignData = ZeroOrOne("vsdx:ForeignData")
    # Optional legacy Data1/2/3 blobs (free-text properties).
    # Modelled generically — their content is a raw string payload.
    # (ZeroOrOne on each slot for round-trip fidelity; most shapes
    # don't carry them.)
    # Nested Shapes for group shapes (recursive).
    shapes = ZeroOrOne("vsdx:Shapes")
