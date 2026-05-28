# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""Unit tests for the SVG → Visio importer (issue #51).

Each test authors a fresh page via the public :func:`vsdx.Visio`
surface, calls :meth:`Page.add_svg` / :meth:`Page.add_svg_string`
on a hand-rolled SVG snippet, and asserts on the resulting shape
graph (counts, types, colours, bounding-box-ish sanity).

The tests deliberately avoid round-tripping to a saved ``.vsdx``
on disk — the in-memory shape inspection is a tighter contract
that doesn't depend on the OPC packaging layer.
"""

from __future__ import annotations

import io

import pytest

from vsdx import Ellipse, GroupShape, Rectangle, Visio
from vsdx.from_svg import (
    PX_PER_INCH,
    _parse_color,
    _parse_length,
    _parse_points,
    _parse_translate,
    _path_to_segments,
)


# ---------------------------------------------------------------------------
# Length / color / transform / points / path helper tests
# ---------------------------------------------------------------------------


class DescribeLengthParser:
    def it_handles_px_at_72_dpi(self):
        assert _parse_length("72px") == pytest.approx(1.0)

    def it_handles_inches(self):
        assert _parse_length("2in") == pytest.approx(2.0)

    def it_handles_millimetres(self):
        assert _parse_length("25.4mm") == pytest.approx(1.0)

    def it_handles_centimetres(self):
        assert _parse_length("2.54cm") == pytest.approx(1.0)

    def it_handles_points(self):
        assert _parse_length("72pt") == pytest.approx(1.0)

    def it_treats_bare_numbers_as_pixels(self):
        # A bare numeric string with no unit is the SVG default (px).
        assert _parse_length("36") == pytest.approx(0.5)

    def it_falls_back_to_default_for_unknown_unit(self):
        assert _parse_length("100em", default_inches=42.0) == 42.0
        assert _parse_length(None, default_inches=7.5) == 7.5
        assert _parse_length("nonsense", default_inches=3.0) == 3.0


class DescribeColorParser:
    def it_resolves_named_colors(self):
        assert _parse_color("red") == "#FF0000"
        assert _parse_color("BLUE") == "#0000FF"
        assert _parse_color("Yellow") == "#FFFF00"

    def it_passes_through_hex6(self):
        assert _parse_color("#abcdef") == "#ABCDEF"

    def it_expands_hex3(self):
        assert _parse_color("#abc") == "#AABBCC"

    def it_resolves_rgb_function(self):
        assert _parse_color("rgb(255, 0, 128)") == "#FF0080"

    def it_returns_none_for_paint_none(self):
        assert _parse_color("none") is None
        assert _parse_color("transparent") is None

    def it_returns_none_for_unknown(self):
        assert _parse_color(None) is None
        assert _parse_color("") is None
        assert _parse_color("not-a-color") is None


class DescribeTranslateParser:
    def it_parses_two_arg_form(self):
        assert _parse_translate("translate(10, 20)") == (10.0, 20.0)

    def it_parses_one_arg_form_with_zero_y(self):
        assert _parse_translate("translate(10)") == (10.0, 0.0)

    def it_handles_whitespace_separator(self):
        assert _parse_translate("translate( 5  10 )") == (5.0, 10.0)

    def it_returns_zero_zero_for_empty_or_other_transforms(self):
        assert _parse_translate("") == (0.0, 0.0)
        assert _parse_translate(None) == (0.0, 0.0)
        assert _parse_translate("rotate(45)") == (0.0, 0.0)
        assert _parse_translate("scale(2)") == (0.0, 0.0)


class DescribePointsParser:
    def it_parses_comma_separated_pairs(self):
        assert _parse_points("10,20 30,40") == [(10.0, 20.0), (30.0, 40.0)]

    def it_parses_space_separated_numbers(self):
        assert _parse_points("10 20 30 40") == [(10.0, 20.0), (30.0, 40.0)]

    def it_drops_orphan_trailing_number(self):
        assert _parse_points("1 2 3") == [(1.0, 2.0)]

    def it_returns_empty_for_blank_input(self):
        assert _parse_points("") == []
        assert _parse_points(None) == []


class DescribePathSegmenter:
    def it_handles_simple_M_L_Z_path(self):
        segs = _path_to_segments("M 10 20 L 30 40 L 50 60 Z")
        assert len(segs) == 1
        seg = segs[0]
        assert seg[0] == (10.0, 20.0)
        assert seg[1] == (30.0, 40.0)
        assert seg[2] == (50.0, 60.0)
        # Z appends the start point so the consumer can detect closure.
        assert seg[-1] == (10.0, 20.0)

    def it_handles_relative_lowercase_commands(self):
        segs = _path_to_segments("m 10 20 l 5 0 l 0 5 z")
        assert len(segs) == 1
        seg = segs[0]
        assert seg[0] == (10.0, 20.0)
        assert seg[1] == (15.0, 20.0)
        assert seg[2] == (15.0, 25.0)
        assert seg[-1] == (10.0, 20.0)

    def it_handles_horizontal_and_vertical_shortcuts(self):
        segs = _path_to_segments("M 0 0 H 50 V 50 H 0 Z")
        seg = segs[0]
        assert seg == [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0), (0.0, 0.0)]

    def it_collapses_curves_to_endpoints(self):
        # A cubic Bezier with control points (10,40) and (40,40) and
        # endpoint (50,0): we drop the controls and jump to (50, 0).
        segs = _path_to_segments("M 0 0 C 10 40 40 40 50 0")
        assert segs[0] == [(0.0, 0.0), (50.0, 0.0)]

    def it_collapses_arcs_to_endpoints(self):
        segs = _path_to_segments("M 0 0 A 10 10 0 0 0 50 50")
        assert segs[0] == [(0.0, 0.0), (50.0, 50.0)]

    def it_splits_on_implicit_subpath_after_z(self):
        segs = _path_to_segments("M 0 0 L 10 0 Z M 20 0 L 30 0 Z")
        assert len(segs) == 2
        assert segs[0][0] == (0.0, 0.0)
        assert segs[1][0] == (20.0, 0.0)

    def it_returns_empty_for_blank_d(self):
        assert _path_to_segments("") == []


# ---------------------------------------------------------------------------
# Per-element importer tests
# ---------------------------------------------------------------------------


def _new_page(width: float = 4.0, height: float = 3.0):
    """Return a fresh page sized in inches.

    The default ``4x3`` matches the typical SVG test snippets'
    ``288x216 px`` canvas at 72 DPI so the Y-flip is visually
    intuitive.
    """
    doc = Visio()
    return doc.pages.add_page(name="SVG", width=width, height=height)


class DescribeAddSvgRect:
    def it_creates_a_rectangle_at_the_expected_position(self):
        page = _new_page()
        # 72 px wide, 36 px tall = 1 in × 0.5 in. Origin at (72, 0)
        # in SVG space — that's (1 in, 0 in) top-left in user space.
        # Visio pin is centre, so pin_x = 1.5 in, pin_y = page_h - 0.25.
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<rect x="72" y="0" width="72" height="36" fill="red"/>'
            '</svg>'
        )
        assert len(page.shapes) == 1
        shape = page.shapes[0]
        assert isinstance(shape, Rectangle)
        assert float(shape.width) == pytest.approx(1.0)
        assert float(shape.height) == pytest.approx(0.5)
        assert float(shape.pin_x) == pytest.approx(1.5)
        # canvas height = 216 / 72 = 3.0 in; centre = 0.25 in from top.
        assert float(shape.pin_y) == pytest.approx(2.75)
        assert shape.fill_foregnd == "#FF0000"

    def it_returns_the_top_level_shape_list(self):
        page = _new_page()
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<rect x="0" y="0" width="36" height="36" fill="blue"/>'
            '<rect x="40" y="40" width="36" height="36" fill="green"/>'
            '</svg>'
        )
        assert len(out) == 2
        assert all(isinstance(s, Rectangle) for s in out)

    def it_skips_zero_size_rects(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<rect x="0" y="0" width="0" height="36"/>'
            '<rect x="0" y="0" width="36" height="0"/>'
            '</svg>'
        )
        assert len(page.shapes) == 0


class DescribeAddSvgCircle:
    def it_creates_an_ellipse_proxy_with_equal_axes(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<circle cx="108" cy="108" r="36" fill="#abc"/>'
            '</svg>'
        )
        assert len(page.shapes) == 1
        shape = page.shapes[0]
        assert isinstance(shape, Ellipse)
        assert float(shape.width) == pytest.approx(1.0)
        assert float(shape.height) == pytest.approx(1.0)
        assert shape.fill_foregnd == "#AABBCC"


class DescribeAddSvgEllipse:
    def it_creates_an_ellipse_with_distinct_axes(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<ellipse cx="100" cy="100" rx="40" ry="20" '
            'fill="rgb(0, 128, 255)"/>'
            '</svg>'
        )
        assert len(page.shapes) == 1
        shape = page.shapes[0]
        assert isinstance(shape, Ellipse)
        assert float(shape.width) == pytest.approx(80.0 / PX_PER_INCH)
        assert float(shape.height) == pytest.approx(40.0 / PX_PER_INCH)
        assert shape.fill_foregnd == "#0080FF"


class DescribeAddSvgLine:
    def it_creates_a_two_point_polyline_shape(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<line x1="0" y1="0" x2="72" y2="0" stroke="red" '
            'stroke-width="2"/>'
            '</svg>'
        )
        assert len(page.shapes) == 1
        shape = page.shapes[0]
        # Stroke applied; fill skipped (stroke_only=True).
        assert shape.line_color == "#FF0000"
        assert shape.fill_foregnd is None
        # 2 px stroke-width at 72 DPI is exactly 2 pt.
        assert shape.line_weight == pytest.approx(2.0)


class DescribeAddSvgPolyline:
    def it_creates_an_open_polyline(self):
        page = _new_page()
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<polyline points="10,10 50,10 50,50" '
            'stroke="black" fill="none"/>'
            '</svg>'
        )
        assert len(out) == 1
        shape = out[0]
        assert shape.line_color == "#000000"
        # No fill on an open polyline (stroke-only).
        assert shape.fill_foregnd is None

    def it_handles_a_polygon_as_closed_polyline(self):
        page = _new_page()
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<polygon points="10,10 50,10 30,50" fill="green"/>'
            '</svg>'
        )
        assert len(out) == 1
        shape = out[0]
        # Closed polygon → fill applied.
        assert shape.fill_foregnd == "#008000"


class DescribeAddSvgPath:
    def it_imports_a_simple_M_L_Z_path(self):
        page = _new_page()
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<path d="M 10 10 L 50 10 L 50 50 Z" fill="orange"/>'
            '</svg>'
        )
        assert len(out) == 1
        shape = out[0]
        # Closed (Z) → filled.
        assert shape.fill_foregnd == "#FFA500"

    def it_emits_one_shape_per_subpath(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<path d="M 0 0 L 20 0 Z M 30 30 L 50 50 Z"/>'
            '</svg>'
        )
        # Two subpaths → two custom-geometry shapes.
        assert len(page.shapes) == 2

    def it_collapses_curve_segments_to_their_endpoints(self):
        page = _new_page()
        # The cubic bezier resolves to a straight line from (0, 0) to
        # (50, 0); the rest of the SVG is irrelevant beyond producing
        # one shape so the lossy fallback does not crash.
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<path d="M 0 0 C 10 40 40 40 50 0"/>'
            '</svg>'
        )
        assert len(out) == 1


class DescribeAddSvgText:
    def it_creates_a_text_shape_with_the_label(self):
        page = _new_page()
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<text x="36" y="36">Label</text>'
            '</svg>'
        )
        assert len(out) == 1
        shape = out[0]
        assert shape.text == "Label"

    def it_concatenates_tspan_children(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<text x="36" y="36">Hello <tspan>World</tspan></text>'
            '</svg>'
        )
        assert page.shapes[0].text.replace("  ", " ").strip() == "Hello World"

    def it_skips_empty_text(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<text x="0" y="0"></text>'
            '<text x="0" y="0">   </text>'
            '</svg>'
        )
        assert len(page.shapes) == 0


class DescribeAddSvgGroup:
    def it_aggregates_children_into_a_group_shape(self):
        page = _new_page()
        out = page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<g>'
            '  <rect x="0" y="0" width="36" height="36" fill="red"/>'
            '  <rect x="40" y="0" width="36" height="36" fill="blue"/>'
            '</g>'
            '</svg>'
        )
        # Top-level: one group containing the two rectangles.
        assert len(out) == 1
        group = out[0]
        assert isinstance(group, GroupShape)
        # The page sees the group at the top level only — the rectangles
        # have been reparented into the group's nested <Shapes>.
        assert len(page.shapes) == 1

    def it_applies_translate_to_descendants(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<g transform="translate(72, 0)">'
            '  <rect x="0" y="0" width="72" height="36" fill="red"/>'
            '</g>'
            '</svg>'
        )
        # A single descendant is a degenerate group — but vsdx still
        # wraps it. Check the absolute pin is shifted by 1 in (= 72 px
        # at 72 DPI) on the X axis relative to the no-translate case.
        group = page.shapes[0]
        assert isinstance(group, GroupShape)
        # Group bbox covers the rect; rect was 1 in wide starting at
        # (translate.x = 72 px = 1 in), so the centre is at 1.5 in.
        assert float(group.pin_x) == pytest.approx(1.5)


class DescribeAddSvgMixed:
    """Kitchen-sink integration scenario — every supported element type."""

    def it_imports_a_kitchen_sink_svg(self):
        svg = """\
<svg xmlns="http://www.w3.org/2000/svg" width="288" height="216">
  <rect x="10" y="10" width="50" height="30" fill="red" stroke="black"
        stroke-width="2"/>
  <circle cx="100" cy="25" r="15" fill="#0F0"/>
  <ellipse cx="160" cy="25" rx="20" ry="10" fill="blue"/>
  <line x1="10" y1="60" x2="60" y2="60" stroke="black"/>
  <polyline points="80,55 100,75 120,55" stroke="purple" fill="none"/>
  <polygon points="140,55 180,55 160,80" fill="yellow"/>
  <path d="M 10 100 L 50 100 L 30 130 Z" fill="orange"/>
  <text x="100" y="120">Hello</text>
  <g transform="translate(0,140)">
    <rect x="200" y="0" width="30" height="30" fill="cyan"/>
    <rect x="240" y="0" width="30" height="30" fill="magenta"/>
  </g>
</svg>
"""
        doc = Visio()
        page = doc.pages.add_page(name="Kitchen", width=4.0, height=3.0)
        out = page.add_svg_string(svg)
        # 7 plain shapes (rect/circle/ellipse/line/polyline/polygon/path)
        # + 1 text + 1 group = 9 top-level entries.
        assert len(out) == 9
        # The group really is a GroupShape — not flattened.
        groups = [s for s in out if isinstance(s, GroupShape)]
        assert len(groups) == 1
        # Document round-trips through .save() without raising.
        buf = io.BytesIO()
        doc.save(buf)
        assert len(buf.getvalue()) > 0


# ---------------------------------------------------------------------------
# add_svg(file path) entry
# ---------------------------------------------------------------------------


class DescribePageAddSvgPath:
    def it_reads_an_svg_file_from_disk(self, tmp_path):
        svg_path = tmp_path / "logo.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<rect x="0" y="0" width="72" height="72" fill="red"/>'
            '</svg>',
            encoding="utf-8",
        )
        page = _new_page()
        out = page.add_svg(str(svg_path))
        assert len(out) == 1
        assert isinstance(out[0], Rectangle)

    def it_accepts_a_pathlib_path(self, tmp_path):
        svg_path = tmp_path / "logo.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<circle cx="50" cy="50" r="20" fill="blue"/>'
            '</svg>',
            encoding="utf-8",
        )
        page = _new_page()
        # The signature is typed ``str`` for the page method, but
        # :func:`add_svg_to_page` takes any ``os.PathLike`` so a Path
        # object should round-trip through :func:`os.fspath` cleanly.
        from vsdx.from_svg import add_svg_to_page

        out = add_svg_to_page(page, svg_path)
        assert len(out) == 1


# ---------------------------------------------------------------------------
# Error / boundary handling
# ---------------------------------------------------------------------------


class DescribeAddSvgErrors:
    def it_raises_on_non_svg_root(self):
        page = _new_page()
        with pytest.raises(ValueError):
            page.add_svg_string("<html></html>")

    def it_resolves_canvas_height_from_viewbox_when_height_missing(self):
        page = _new_page()
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'viewBox="0 0 144 144">'
            '<rect x="0" y="0" width="72" height="72" fill="red"/>'
            '</svg>'
        )
        # viewBox 4th number = 144 px = 2 in canvas height. Rect top is
        # at y=0 (top of canvas), bottom at 72 px = 1 in. Visio Y-flip
        # gives the centre at 2 - 0.5 = 1.5 in.
        shape = page.shapes[0]
        assert float(shape.pin_y) == pytest.approx(1.5)

    def it_skips_unknown_elements_silently(self):
        page = _new_page()
        # ``<defs>`` / ``<title>`` / ``<filter>`` etc. should pass
        # through without authoring shapes.
        page.add_svg_string(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="216" height="216">'
            '<title>Logo</title>'
            '<defs><linearGradient id="g"/></defs>'
            '<rect x="0" y="0" width="36" height="36" fill="red"/>'
            '</svg>'
        )
        assert len(page.shapes) == 1
