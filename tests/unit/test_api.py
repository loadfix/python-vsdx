"""Behavioural tests for the top-level ``Visio`` factory and happy path.

Name style matches the python-pptx convention: ``Describe*`` classes,
``it_*`` / ``they_*`` methods. The happy-path scenario from the brief
lives in :class:`DescribeVisio::it_can_author_a_connected_diagram`.
"""

from __future__ import annotations

import io

import pytest

from vsdx import (
    Connector,
    Ellipse,
    Rectangle,
    Triangle,
    VS_SHAPE_TYPE,
    Visio,
    VisioDocument,
)
from vsdx.util import Inches


class DescribeVisio:
    def it_returns_a_VisioDocument_on_the_no_arg_path(self):
        doc = Visio()
        assert isinstance(doc, VisioDocument)

    def it_starts_with_no_pages(self):
        doc = Visio()
        assert len(doc.pages) == 0

    def it_starts_with_no_masters(self):
        doc = Visio()
        assert len(doc.masters) == 0

    def it_exposes_theme_none_on_a_bare_package(self):
        # -- VisioPackage.new() deliberately does not seed a theme part;
        # -- that responsibility lives in track 4 (templates). The
        # -- adoption task surfaces None in the interim rather than
        # -- inventing a synthetic theme.
        doc = Visio()

        assert doc.theme is None

    def it_exposes_the_theme_proxy_when_a_theme_part_is_related(self):
        from ooxml_opc import RELATIONSHIP_TYPE as RT

        from vsdx import Theme
        from vsdx.parts.theme import ThemePart

        _STUB = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
            b' name="Office Theme">'
            b"<a:themeElements>"
            b'<a:clrScheme name="Office">'
            b'<a:accent1><a:srgbClr val="4F81BD"/></a:accent1>'
            b"</a:clrScheme>"
            b"</a:themeElements></a:theme>"
        )
        doc = Visio()
        theme_part = ThemePart.new(doc.package, _STUB)
        doc.package.document_part.relate_to(theme_part, RT.THEME)

        theme = doc.theme

        assert isinstance(theme, Theme)
        assert theme.name == "Office Theme"
        assert theme.color("accent1") == "4F81BD"

    def it_can_author_a_connected_diagram(self):
        """End-to-end happy path from the brief — 4-shape connected diagram."""
        doc = Visio()
        page = doc.pages.add_page(name="Page-1")
        assert page.name == "Page-1"

        rect = page.shapes.add_shape(
            "Rectangle", at=(Inches(1), Inches(1)), size=(Inches(2), Inches(1))
        )
        rect.text = "Start"
        assert isinstance(rect, Rectangle)
        assert rect.text == "Start"

        ellipse = page.shapes.add_shape(
            "Ellipse", at=(Inches(4), Inches(1)), size=(Inches(2), Inches(1))
        )
        ellipse.text = "End"
        assert isinstance(ellipse, Ellipse)

        conn = page.shapes.add_connector(rect, ellipse)
        assert isinstance(conn, Connector)
        # endpoints glued to anchor-shape pins
        assert conn.begin_x == float(rect.pin_x)
        assert conn.end_x == float(ellipse.pin_x)

        # round-trip through save() — stub package writes a marker blob
        buf = io.BytesIO()
        doc.save(buf)
        assert buf.getvalue()  # non-empty

    def it_can_save_to_a_path(self, tmp_path):
        doc = Visio()
        doc.pages.add_page()
        out = tmp_path / "out.vsdx"
        doc.save(str(out))
        assert out.exists()
        assert out.read_bytes()


class DescribeVisioPages:
    def it_assigns_default_names(self):
        doc = Visio()
        p1 = doc.pages.add_page()
        p2 = doc.pages.add_page()
        assert p1.name == "Page-1"
        assert p2.name == "Page-2"

    def it_accepts_explicit_names(self):
        doc = Visio()
        p = doc.pages.add_page(name="Flow")
        assert p.name == "Flow"

    def it_allows_iteration_indexing_and_len(self):
        doc = Visio()
        p1 = doc.pages.add_page()
        p2 = doc.pages.add_page()
        p3 = doc.pages.add_page()
        assert len(doc.pages) == 3
        assert doc.pages[0] is p1
        assert list(doc.pages) == [p1, p2, p3]

    def it_records_page_dimensions(self):
        doc = Visio()
        p = doc.pages.add_page(width=11.0, height=8.5)
        assert float(p.width) == 11.0
        assert float(p.height) == 8.5

    def it_can_change_the_page_name(self):
        doc = Visio()
        p = doc.pages.add_page()
        p.name = "Renamed"
        assert p.name == "Renamed"
