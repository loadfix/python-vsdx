"""Unit tests for CT_Shape — the core recursive shape element."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.cell import CT_Cell
from vsdx.oxml.section import CT_Section
from vsdx.oxml.shape import CT_ForeignData, CT_Shape, CT_Text


class Describe_CT_Shape:
    def it_round_trips_an_identifier_and_type(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="1" Type="Shape" Master="7"/>'
            % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        assert shape.id_ == 1
        assert shape.type_ == "Shape"
        assert shape.master == 7

    def it_round_trips_stylesheet_references(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="2" LineStyle="0" FillStyle="2" TextStyle="3"/>'
            % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        assert shape.line_style == 0
        assert shape.fill_style == 2
        assert shape.text_style == 3

    def it_round_trips_singleton_cells(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="1">'
            '<vsdx:Cell N="PinX" V="2"/>'
            '<vsdx:Cell N="PinY" V="3"/>'
            '<vsdx:Cell N="Width" V="1"/>'
            '<vsdx:Cell N="Height" V="1"/>'
            "</vsdx:Shape>" % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        cells = shape.cell_lst
        assert len(cells) == 4
        assert all(isinstance(c, CT_Cell) for c in cells)
        names = [c.name_ for c in cells]
        assert names == ["PinX", "PinY", "Width", "Height"]

    def it_round_trips_mixed_cells_and_sections(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="1" Type="Shape">'
            '<vsdx:Cell N="PinX" V="2"/>'
            '<vsdx:Section N="Geometry" IX="0">'
            '<vsdx:Row IX="1" T="LineTo">'
            '<vsdx:Cell N="X" V="0"/>'
            "</vsdx:Row>"
            "</vsdx:Section>"
            "</vsdx:Shape>" % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        assert len(shape.cell_lst) == 1
        sections = shape.section_lst
        assert len(sections) == 1
        assert isinstance(sections[0], CT_Section)
        assert sections[0].name_ == "Geometry"

    def it_round_trips_a_Text_child(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="1">'
            "<vsdx:Text>Hello world</vsdx:Text>"
            "</vsdx:Shape>" % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        assert isinstance(shape.text, CT_Text)
        assert shape.text.text == "Hello world"

    def it_round_trips_a_ForeignData_child(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="1" Type="Foreign">'
            '<vsdx:ForeignData ForeignType="Bitmap" CompressionType="PNG">Zm9v</vsdx:ForeignData>'
            "</vsdx:Shape>" % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        assert isinstance(shape.foreignData, CT_ForeignData)
        assert shape.foreignData.foreign_type == "Bitmap"
        assert shape.foreignData.compression_type == "PNG"

    def it_supports_nested_group_shapes(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="10" Type="Group">'
            "<vsdx:Shapes>"
            '<vsdx:Shape ID="11" Type="Shape"/>'
            '<vsdx:Shape ID="12" Type="Shape"/>'
            "</vsdx:Shapes>"
            "</vsdx:Shape>" % nsdecls("vsdx")
        ).encode()
        group = parse_xml(xml)
        assert isinstance(group, CT_Shape)
        assert group.type_ == "Group"
        assert group.shapes is not None
        inner = group.shapes.shape_lst
        assert [s.id_ for s in inner] == [11, 12]

    def it_round_trips_a_Del_inheritance_sentinel(self) -> None:
        xml = (
            '<vsdx:Shape %s ID="5" Del="1"/>' % nsdecls("vsdx")
        ).encode()
        shape = parse_xml(xml)
        assert isinstance(shape, CT_Shape)
        assert shape.del_ == "1"
