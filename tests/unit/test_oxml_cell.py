"""Unit tests for CT_Cell — the universal name/value element."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.cell import CT_Cell


class Describe_CT_Cell:
    def it_round_trips_a_PinX_singleton_cell(self) -> None:
        xml = (
            '<vsdx:Cell %s N="PinX" V="2" U="IN"/>' % nsdecls("vsdx")
        ).encode()
        cell = parse_xml(xml)
        assert isinstance(cell, CT_Cell)
        assert cell.name_ == "PinX"
        assert cell.v == "2"
        assert cell.u == "IN"

    def it_round_trips_a_cell_with_a_formula(self) -> None:
        xml = (
            '<vsdx:Cell %s N="X" V="0" F="Width*0"/>' % nsdecls("vsdx")
        ).encode()
        cell = parse_xml(xml)
        assert isinstance(cell, CT_Cell)
        assert cell.name_ == "X"
        assert cell.v == "0"
        assert cell.f == "Width*0"

    def it_accepts_an_error_attribute(self) -> None:
        xml = (
            '<vsdx:Cell %s N="LineWeight" V="0.01" F="Foo" E="#NAME?"/>'
            % nsdecls("vsdx")
        ).encode()
        cell = parse_xml(xml)
        assert isinstance(cell, CT_Cell)
        assert cell.e == "#NAME?"

    def it_returns_None_for_attributes_not_present(self) -> None:
        xml = ('<vsdx:Cell %s N="Width"/>' % nsdecls("vsdx")).encode()
        cell = parse_xml(xml)
        assert isinstance(cell, CT_Cell)
        assert cell.v is None
        assert cell.f is None
        assert cell.u is None
        assert cell.e is None

    def it_accepts_a_themed_color_sentinel_as_V(self) -> None:
        xml = (
            '<vsdx:Cell %s N="FillForegnd" V="Themed" F="THEMEGUARD(THEME(\'AccentColor1\'))"/>'
            % nsdecls("vsdx")
        ).encode()
        cell = parse_xml(xml)
        assert isinstance(cell, CT_Cell)
        # V is opaque at oxml layer — we don't try to parse "Themed"
        # as a float.
        assert cell.v == "Themed"

    def and_it_allows_the_N_attribute_to_be_omitted(self) -> None:
        # Tabular cells inside a Row may omit @N when position implies
        # identity — XSD marks it optional. Match the XSD.
        xml = ('<vsdx:Cell %s V="0.5"/>' % nsdecls("vsdx")).encode()
        cell = parse_xml(xml)
        assert isinstance(cell, CT_Cell)
        assert cell.name_ is None
        assert cell.v == "0.5"
