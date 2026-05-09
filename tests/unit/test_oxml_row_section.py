"""Unit tests for CT_Row and CT_Section."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.cell import CT_Cell
from vsdx.oxml.row import CT_Row
from vsdx.oxml.section import CT_Section


class Describe_CT_Row:
    def it_round_trips_an_indexed_row(self) -> None:
        xml = (
            '<vsdx:Row %s IX="3"><vsdx:Cell N="X" V="0"/></vsdx:Row>'
            % nsdecls("vsdx")
        ).encode()
        row = parse_xml(xml)
        assert isinstance(row, CT_Row)
        assert row.ix == 3
        assert row.t is None
        assert row.name_ is None

    def it_round_trips_a_geometry_typed_row(self) -> None:
        xml = (
            '<vsdx:Row %s IX="1" T="LineTo">'
            '<vsdx:Cell N="X" V="0" F="Width*0"/>'
            '<vsdx:Cell N="Y" V="0" F="Height*0"/>'
            "</vsdx:Row>" % nsdecls("vsdx")
        ).encode()
        row = parse_xml(xml)
        assert isinstance(row, CT_Row)
        assert row.ix == 1
        assert row.t == "LineTo"
        cells = row.cell_lst
        assert len(cells) == 2
        assert all(isinstance(c, CT_Cell) for c in cells)
        assert cells[0].name_ == "X"
        assert cells[1].name_ == "Y"

    def it_round_trips_a_named_row(self) -> None:
        xml = (
            '<vsdx:Row %s N="User.MyVar"><vsdx:Cell N="Value" V="42"/></vsdx:Row>'
            % nsdecls("vsdx")
        ).encode()
        row = parse_xml(xml)
        assert isinstance(row, CT_Row)
        assert row.name_ == "User.MyVar"
        assert row.ix is None


class Describe_CT_Section:
    def it_round_trips_a_Geometry_section(self) -> None:
        xml = (
            '<vsdx:Section %s N="Geometry" IX="0">'
            '<vsdx:Row IX="1" T="MoveTo">'
            '<vsdx:Cell N="X" V="0"/><vsdx:Cell N="Y" V="0"/>'
            "</vsdx:Row>"
            '<vsdx:Row IX="2" T="LineTo">'
            '<vsdx:Cell N="X" V="1"/><vsdx:Cell N="Y" V="1"/>'
            "</vsdx:Row>"
            "</vsdx:Section>" % nsdecls("vsdx")
        ).encode()
        sect = parse_xml(xml)
        assert isinstance(sect, CT_Section)
        assert sect.name_ == "Geometry"
        assert sect.ix == 0
        rows = sect.row_lst
        assert len(rows) == 2
        assert rows[0].t == "MoveTo"
        assert rows[1].t == "LineTo"

    def it_round_trips_a_Character_section_with_indexed_rows(self) -> None:
        xml = (
            '<vsdx:Section %s N="Character">'
            '<vsdx:Row IX="0"><vsdx:Cell N="Font" V="0"/></vsdx:Row>'
            "</vsdx:Section>" % nsdecls("vsdx")
        ).encode()
        sect = parse_xml(xml)
        assert isinstance(sect, CT_Section)
        assert sect.name_ == "Character"
        assert sect.ix is None
        assert len(sect.row_lst) == 1
