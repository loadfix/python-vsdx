"""Unit tests for the minimal page → SVG renderer (R17-4).

Each test authors a fresh page via the public :func:`vsdx.Visio`
surface, calls :meth:`Page.to_svg`, re-parses the result with lxml,
and asserts on element counts or specific attribute values. The
parse-back is deliberate — it doubles as a well-formedness check for
every scenario we ship.
"""

from __future__ import annotations

import os

import pytest
from lxml import etree

import vsdx
from vsdx import Visio


SVG_NS = "http://www.w3.org/2000/svg"


def _parse(svg: str) -> etree._Element:
    """Parse the SVG string the renderer emits and return the root element."""
    return etree.fromstring(svg.encode("utf-8"))


def _find_all(root: etree._Element, tag: str) -> list[etree._Element]:
    return root.findall(".//{%s}%s" % (SVG_NS, tag))


class DescribePageToSvg:
    def it_renders_a_three_shape_page_with_expected_element_counts(self):
        doc = Visio()
        page = doc.pages.add_page(name="Three")
        page.shapes.add_shape("Rectangle", at=(1.0, 1.0), size=(2.0, 1.0), text="A")
        page.shapes.add_shape("Ellipse", at=(5.0, 1.0), size=(2.0, 1.0), text="B")
        rect = page.shapes[0]
        ell = page.shapes[1]
        page.shapes.add_connector(rect, ell)

        svg = page.to_svg()
        root = _parse(svg)

        assert root.tag == "{%s}svg" % SVG_NS
        assert len(_find_all(root, "rect")) == 1
        assert len(_find_all(root, "ellipse")) == 1
        assert len(_find_all(root, "line")) == 1
        # Two text shapes authored, one <text> per shape.
        assert len(_find_all(root, "text")) == 2

    def it_returns_an_svg_1_1_document_with_page_sized_viewbox(self):
        doc = Visio()
        page = doc.pages.add_page(name="Size", width=10.0, height=5.0)

        svg = page.to_svg()
        root = _parse(svg)

        # 96 px / inch at the default SVG DPI.
        assert root.get("viewBox") == "0 0 960 480"
        assert root.get("width") == "960"
        assert root.get("height") == "480"
        assert root.get("version") == "1.1"

    def it_places_rectangle_at_top_left_corner_in_svg_coords(self):
        doc = Visio()
        page = doc.pages.add_page(name="Rect", width=8.5, height=11.0)
        page.shapes.add_shape("Rectangle", at=(1.0, 10.0), size=(2.0, 1.0))

        svg = page.to_svg()
        rect_els = _find_all(_parse(svg), "rect")
        assert len(rect_els) == 1
        rect = rect_els[0]
        # left = pin_x - w/2 = 0 in; top_in_svg = page_h - (pin_y + h/2)
        # = 11 - 10.5 = 0.5 in = 48 px
        assert rect.get("x") == "0"
        assert rect.get("y") == "48"
        assert rect.get("width") == "192"
        assert rect.get("height") == "96"

    def it_defaults_fill_to_white_and_stroke_to_black(self):
        doc = Visio()
        page = doc.pages.add_page(name="Colours")
        page.shapes.add_shape("Rectangle", at=(1.0, 1.0), size=(1.0, 1.0))

        svg = page.to_svg()
        rect = _find_all(_parse(svg), "rect")[0]
        assert rect.get("fill") == "#FFFFFF"
        assert rect.get("stroke") == "#000000"

    def it_honours_authored_fill_and_line_colours(self):
        doc = Visio()
        page = doc.pages.add_page(name="RGB")
        r = page.shapes.add_shape("Rectangle", at=(1.0, 1.0), size=(1.0, 1.0))
        r.fill_foregnd = "FF8800"
        r.line_color = "#112233"

        svg = page.to_svg()
        rect = _find_all(_parse(svg), "rect")[0]
        assert rect.get("fill") == "#FF8800"
        assert rect.get("stroke") == "#112233"

    def it_escapes_shape_text_to_prevent_markup_injection(self):
        doc = Visio()
        page = doc.pages.add_page(name="Escape")
        page.shapes.add_shape(
            "Rectangle",
            at=(1.0, 1.0),
            size=(1.0, 1.0),
            text="<script>alert(1)</script> & \"quoted\"",
        )

        svg = page.to_svg()
        # Authored payload must not round-trip as live markup.
        assert "<script>" not in svg
        # lxml should parse the text node and report the raw content.
        texts = _find_all(_parse(svg), "text")
        assert len(texts) == 1
        assert "<script>" in (texts[0].text or "")
        assert "&" in (texts[0].text or "")

    def it_emits_a_placeholder_rect_and_comment_for_unsupported_shapes(self):
        doc = Visio()
        page = doc.pages.add_page(name="Unsupp")
        page.shapes.add_shape("Triangle", at=(3.0, 3.0), size=(1.0, 1.0))

        svg = page.to_svg()
        # Render continued past the unsupported shape.
        assert "unsupported shape: master=Triangle" in svg
        root = _parse(svg)
        rects = _find_all(root, "rect")
        assert len(rects) == 1
        # Placeholder is zero-size so gallery consumers can skip it.
        assert rects[0].get("width") == "0"
        assert rects[0].get("height") == "0"

    def it_writes_to_a_path_when_one_is_supplied(self, tmp_path):
        doc = Visio()
        page = doc.pages.add_page(name="Write")
        page.shapes.add_shape("Rectangle", at=(1.0, 1.0), size=(1.0, 1.0))

        out = tmp_path / "page.svg"
        returned = page.to_svg(str(out))

        assert out.exists()
        on_disk = out.read_text(encoding="utf-8")
        assert on_disk == returned
        assert "<svg" in on_disk

    def it_renders_a_connector_line_between_two_shapes(self):
        doc = Visio()
        page = doc.pages.add_page(name="Conn", width=10.0, height=5.0)
        a = page.shapes.add_shape("Rectangle", at=(1.0, 4.0), size=(1.0, 1.0))
        b = page.shapes.add_shape("Rectangle", at=(9.0, 4.0), size=(1.0, 1.0))
        page.shapes.add_connector(a, b)

        svg = page.to_svg()
        lines = _find_all(_parse(svg), "line")
        assert len(lines) == 1
        line = lines[0]
        # Visio pins land at (1, 4) / (9, 4); page h=5; SVG-y = (5-4)*96 = 96.
        assert line.get("x1") == "96"
        assert line.get("x2") == "864"
        assert line.get("y1") == "96"
        assert line.get("y2") == "96"


class DescribeDocumentToSvgAll:
    def it_writes_one_svg_per_page(self, tmp_path):
        doc = Visio()
        doc.pages.add_page(name="Alpha")
        doc.pages.add_page(name="Beta")

        written = doc.to_svg_all(str(tmp_path))

        assert len(written) == 2
        for path in written:
            assert os.path.exists(path)
            assert path.endswith(".svg")
            assert os.path.getsize(path) > 0

    def it_creates_the_directory_when_it_does_not_exist(self, tmp_path):
        doc = Visio()
        doc.pages.add_page(name="Only")

        target = tmp_path / "out" / "svgs"
        written = doc.to_svg_all(str(target))

        assert target.is_dir()
        assert len(written) == 1

    def it_sanitises_page_names_in_filenames(self, tmp_path):
        doc = Visio()
        doc.pages.add_page(name="weird / name: *?")

        written = doc.to_svg_all(str(tmp_path))
        base = os.path.basename(written[0])

        for bad in "/:*?":
            assert bad not in base
        # Index prefix preserved even when the name is aggressively cleaned.
        assert base.startswith("page-1-")
