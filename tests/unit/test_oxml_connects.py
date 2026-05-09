"""Unit tests for CT_Connects and CT_Connect."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.connects import CT_Connect, CT_Connects


class Describe_CT_Connect:
    def it_round_trips_a_begin_endpoint_glue(self) -> None:
        xml = (
            '<vsdx:Connect %s FromSheet="5" FromCell="BeginX" FromPart="9"'
            ' ToSheet="3" ToCell="PinX"/>' % nsdecls("vsdx")
        ).encode()
        conn = parse_xml(xml)
        assert isinstance(conn, CT_Connect)
        assert conn.from_sheet == 5
        assert conn.from_cell == "BeginX"
        assert conn.from_part == 9
        assert conn.to_sheet == 3
        assert conn.to_cell == "PinX"

    def it_round_trips_an_end_endpoint_glue(self) -> None:
        xml = (
            '<vsdx:Connect %s FromSheet="5" FromCell="EndX" FromPart="12"'
            ' ToSheet="4" ToCell="PinX"/>' % nsdecls("vsdx")
        ).encode()
        conn = parse_xml(xml)
        assert isinstance(conn, CT_Connect)
        assert conn.from_cell == "EndX"
        assert conn.from_part == 12


class Describe_CT_Connects:
    def it_is_empty_for_a_page_with_no_connectors(self) -> None:
        xml = ("<vsdx:Connects %s/>" % nsdecls("vsdx")).encode()
        connects = parse_xml(xml)
        assert isinstance(connects, CT_Connects)
        assert connects.connect_lst == []

    def it_round_trips_a_dynamic_connector_pair(self) -> None:
        xml = (
            "<vsdx:Connects %s>"
            '<vsdx:Connect FromSheet="5" FromCell="BeginX" FromPart="9"'
            ' ToSheet="3" ToCell="PinX"/>'
            '<vsdx:Connect FromSheet="5" FromCell="EndX" FromPart="12"'
            ' ToSheet="4" ToCell="PinX"/>'
            "</vsdx:Connects>" % nsdecls("vsdx")
        ).encode()
        connects = parse_xml(xml)
        assert isinstance(connects, CT_Connects)
        lst = connects.connect_lst
        assert len(lst) == 2
        assert lst[0].from_cell == "BeginX"
        assert lst[1].from_cell == "EndX"
