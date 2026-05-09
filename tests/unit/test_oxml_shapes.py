"""Unit tests for CT_Shapes — the recursive container."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.shape import CT_Shape
from vsdx.oxml.shapes import CT_Shapes


class Describe_CT_Shapes:
    def it_is_empty_for_a_page_with_no_shapes(self) -> None:
        xml = ("<vsdx:Shapes %s/>" % nsdecls("vsdx")).encode()
        shapes = parse_xml(xml)
        assert isinstance(shapes, CT_Shapes)
        assert shapes.shape_lst == []

    def it_round_trips_a_collection_of_shapes(self) -> None:
        xml = (
            "<vsdx:Shapes %s>"
            '<vsdx:Shape ID="1" Type="Shape"/>'
            '<vsdx:Shape ID="2" Type="Shape"/>'
            '<vsdx:Shape ID="3" Type="Shape"/>'
            "</vsdx:Shapes>" % nsdecls("vsdx")
        ).encode()
        shapes = parse_xml(xml)
        assert isinstance(shapes, CT_Shapes)
        kids = shapes.shape_lst
        assert len(kids) == 3
        assert all(isinstance(s, CT_Shape) for s in kids)
        assert [s.id_ for s in kids] == [1, 2, 3]

    def it_is_recursive_via_nested_group_shapes(self) -> None:
        xml = (
            "<vsdx:Shapes %s>"
            '<vsdx:Shape ID="10" Type="Group">'
            "<vsdx:Shapes>"
            '<vsdx:Shape ID="11" Type="Shape"/>'
            "</vsdx:Shapes>"
            "</vsdx:Shape>"
            "</vsdx:Shapes>" % nsdecls("vsdx")
        ).encode()
        shapes = parse_xml(xml)
        assert isinstance(shapes, CT_Shapes)
        group = shapes.shape_lst[0]
        assert group.type_ == "Group"
        assert group.shapes is not None
        assert [s.id_ for s in group.shapes.shape_lst] == [11]
