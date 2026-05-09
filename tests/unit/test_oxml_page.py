"""Unit tests for CT_Page, CT_PageSheet, CT_PageContents, CT_Rel."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.cell import CT_Cell
from vsdx.oxml.page import (
    CT_Page,
    CT_PageContents,
    CT_PageSheet,
    CT_Rel,
)


class Describe_CT_Rel:
    def it_round_trips_an_r_id(self) -> None:
        xml = (
            '<vsdx:Rel %s %s r:id="rId7"/>'
            % (nsdecls("vsdx"), nsdecls("r"))
        ).encode()
        rel = parse_xml(xml)
        assert isinstance(rel, CT_Rel)
        assert rel.rId == "rId7"


class Describe_CT_PageSheet:
    def it_round_trips_singleton_cells(self) -> None:
        xml = (
            "<vsdx:PageSheet %s>"
            '<vsdx:Cell N="PageWidth" V="8.5" U="IN"/>'
            '<vsdx:Cell N="PageHeight" V="11" U="IN"/>'
            "</vsdx:PageSheet>" % nsdecls("vsdx")
        ).encode()
        ps = parse_xml(xml)
        assert isinstance(ps, CT_PageSheet)
        cells = ps.cell_lst
        assert len(cells) == 2
        assert all(isinstance(c, CT_Cell) for c in cells)


class Describe_CT_Page:
    def it_round_trips_a_page_entry(self) -> None:
        xml = (
            '<vsdx:Page %s %s ID="0" NameU="Page-1" Name="Page-1"'
            ' ViewScale="-1" ViewCenterX="4.25" ViewCenterY="5.5">'
            '<vsdx:PageSheet><vsdx:Cell N="PageWidth" V="8.5"/></vsdx:PageSheet>'
            '<vsdx:Rel r:id="rId1"/>'
            "</vsdx:Page>"
            % (nsdecls("vsdx"), nsdecls("r"))
        ).encode()
        page = parse_xml(xml)
        assert isinstance(page, CT_Page)
        assert page.id_ == 0
        assert page.name_u == "Page-1"
        assert page.name == "Page-1"
        assert page.view_scale == "-1"
        assert page.view_center_x == "4.25"
        assert isinstance(page.pageSheet, CT_PageSheet)
        assert isinstance(page.rel, CT_Rel)
        assert page.rel.rId == "rId1"


class Describe_CT_PageContents:
    def it_round_trips_Shapes_and_Connects(self) -> None:
        xml = (
            "<vsdx:PageContents %s>"
            "<vsdx:Shapes>"
            '<vsdx:Shape ID="1" Type="Shape"/>'
            "</vsdx:Shapes>"
            "<vsdx:Connects>"
            '<vsdx:Connect FromSheet="1" FromCell="BeginX"'
            ' ToSheet="2"/>'
            "</vsdx:Connects>"
            "</vsdx:PageContents>" % nsdecls("vsdx")
        ).encode()
        pc = parse_xml(xml)
        assert isinstance(pc, CT_PageContents)
        assert pc.shapes is not None
        assert pc.connects is not None
        assert len(pc.shapes.shape_lst) == 1
        assert len(pc.connects.connect_lst) == 1
