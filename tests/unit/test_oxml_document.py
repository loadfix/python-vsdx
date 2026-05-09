"""Unit tests for CT_VisioDocument and its DocumentSettings children."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.document import (
    CT_DocumentSettings,
    CT_DocumentSheet,
    CT_StyleSheet,
    CT_StyleSheets,
    CT_VisioDocument,
)


class Describe_CT_VisioDocument:
    def it_round_trips_root_attributes(self) -> None:
        xml = (
            "<vsdx:VisioDocument %s"
            ' key="b63c4a6e" metric="0" start="190"'
            ' DocLangID="1033" buildnum="12345" version="16.0"/>'
            % nsdecls("vsdx")
        ).encode()
        doc = parse_xml(xml)
        assert isinstance(doc, CT_VisioDocument)
        assert doc.key == "b63c4a6e"
        assert doc.metric == "0"
        assert doc.doc_lang_id == "1033"
        assert doc.buildnum == "12345"
        assert doc.version == "16.0"

    def it_round_trips_document_children(self) -> None:
        xml = (
            "<vsdx:VisioDocument %s>"
            "<vsdx:DocumentProperties/>"
            '<vsdx:DocumentSettings TopPage="0" DefaultTextStyle="3"/>'
            "<vsdx:Colors/>"
            "<vsdx:FaceNames/>"
            "<vsdx:StyleSheets>"
            '<vsdx:StyleSheet ID="0" NameU="No Style"/>'
            "</vsdx:StyleSheets>"
            "<vsdx:DocumentSheet/>"
            "<vsdx:EventList/>"
            "</vsdx:VisioDocument>" % nsdecls("vsdx")
        ).encode()
        doc = parse_xml(xml)
        assert isinstance(doc, CT_VisioDocument)
        assert doc.documentProperties is not None
        assert isinstance(doc.documentSettings, CT_DocumentSettings)
        assert doc.documentSettings.top_page == 0
        assert doc.documentSettings.default_text_style == 3
        assert isinstance(doc.styleSheets, CT_StyleSheets)
        assert isinstance(doc.documentSheet, CT_DocumentSheet)
        assert doc.eventList is not None


class Describe_CT_StyleSheets:
    def it_round_trips_multiple_stylesheets(self) -> None:
        xml = (
            "<vsdx:StyleSheets %s>"
            '<vsdx:StyleSheet ID="0" NameU="No Style"/>'
            '<vsdx:StyleSheet ID="1" NameU="Text Only" LineStyle="0"/>'
            '<vsdx:StyleSheet ID="2" NameU="Callout" FillStyle="1"/>'
            "</vsdx:StyleSheets>" % nsdecls("vsdx")
        ).encode()
        sheets = parse_xml(xml)
        assert isinstance(sheets, CT_StyleSheets)
        lst = sheets.styleSheet_lst
        assert [s.id_ for s in lst] == [0, 1, 2]
        assert all(isinstance(s, CT_StyleSheet) for s in lst)
        assert lst[1].line_style == 0
        assert lst[2].fill_style == 1


class Describe_CT_DocumentSheet:
    def it_round_trips_cells_and_sections(self) -> None:
        xml = (
            "<vsdx:DocumentSheet %s>"
            '<vsdx:Cell N="DocLangID" V="1033"/>'
            '<vsdx:Section N="User"/>'
            "</vsdx:DocumentSheet>" % nsdecls("vsdx")
        ).encode()
        ds = parse_xml(xml)
        assert isinstance(ds, CT_DocumentSheet)
        assert len(ds.cell_lst) == 1
        assert len(ds.section_lst) == 1
