"""Unit tests for CT_Master, CT_MasterContents, CT_Icon, CT_Masters."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.master import (
    CT_Icon,
    CT_Master,
    CT_MasterContents,
)
from vsdx.oxml.masters import CT_Masters


class Describe_CT_Master:
    def it_round_trips_a_master_entry(self) -> None:
        xml = (
            '<vsdx:Master %s %s ID="0" NameU="Rectangle" Name="Rectangle"'
            ' BaseID="{91A5A9A0-1234-5678-ABCD-1234567890AB}"'
            ' UniqueID="{DEADBEEF-0000-0000-0000-000000000001}"'
            ' Hidden="0" MatchByName="1">'
            '<vsdx:PageSheet><vsdx:Cell N="PinX" V="0"/></vsdx:PageSheet>'
            '<vsdx:Rel r:id="rId1"/>'
            "</vsdx:Master>"
            % (nsdecls("vsdx"), nsdecls("r"))
        ).encode()
        master = parse_xml(xml)
        assert isinstance(master, CT_Master)
        assert master.id_ == 0
        assert master.name_u == "Rectangle"
        assert master.base_id == "{91A5A9A0-1234-5678-ABCD-1234567890AB}"
        assert master.hidden == "0"
        assert master.match_by_name == "1"
        assert master.pageSheet is not None
        assert master.rel is not None

    def it_accepts_an_icon_child(self) -> None:
        xml = (
            '<vsdx:Master %s ID="1" NameU="Ellipse">'
            "<vsdx:Icon>AAECAwQF</vsdx:Icon>"
            "</vsdx:Master>" % nsdecls("vsdx")
        ).encode()
        master = parse_xml(xml)
        assert isinstance(master, CT_Master)
        assert isinstance(master.icon, CT_Icon)
        assert master.icon.text == "AAECAwQF"


class Describe_CT_MasterContents:
    def it_round_trips_a_master_shape_tree(self) -> None:
        xml = (
            "<vsdx:MasterContents %s>"
            "<vsdx:Shapes>"
            '<vsdx:Shape ID="1" Type="Shape">'
            '<vsdx:Cell N="Width" V="1"/>'
            "</vsdx:Shape>"
            "</vsdx:Shapes>"
            "</vsdx:MasterContents>" % nsdecls("vsdx")
        ).encode()
        mc = parse_xml(xml)
        assert isinstance(mc, CT_MasterContents)
        assert mc.shapes is not None
        assert len(mc.shapes.shape_lst) == 1


class Describe_CT_Masters:
    def it_round_trips_an_empty_master_index(self) -> None:
        xml = ("<vsdx:Masters %s/>" % nsdecls("vsdx")).encode()
        masters = parse_xml(xml)
        assert isinstance(masters, CT_Masters)
        assert masters.master_lst == []

    def it_round_trips_multiple_masters(self) -> None:
        xml = (
            "<vsdx:Masters %s>"
            '<vsdx:Master ID="0" NameU="Rectangle"/>'
            '<vsdx:Master ID="1" NameU="Ellipse"/>'
            '<vsdx:Master ID="2" NameU="Triangle"/>'
            "</vsdx:Masters>" % nsdecls("vsdx")
        ).encode()
        masters = parse_xml(xml)
        assert isinstance(masters, CT_Masters)
        lst = masters.master_lst
        assert [m.name_u for m in lst] == ["Rectangle", "Ellipse", "Triangle"]
