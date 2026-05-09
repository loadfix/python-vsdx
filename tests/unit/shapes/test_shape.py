"""Behavioural tests for the :class:`Shape` base-class named-cell API."""

from __future__ import annotations

import pytest

from vsdx import Visio
from vsdx.shapes import Ellipse, Rectangle, Triangle


def _fresh_page():
    doc = Visio()
    return doc.pages.add_page()


class DescribeShape:
    def it_exposes_the_geometry_as_Length_properties(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle", at=(1.0, 2.0), size=(3.0, 4.0))
        assert float(r.pin_x) == 1.0
        assert float(r.pin_y) == 2.0
        assert float(r.width) == 3.0
        assert float(r.height) == 4.0

    def it_can_rewrite_the_geometry(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        r.pin_x = 7
        r.width = 2.5
        assert float(r.pin_x) == 7.0
        assert float(r.width) == 2.5

    def its_id_is_unique_within_the_page(self):
        page = _fresh_page()
        a = page.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        b = page.shapes.add_shape("Ellipse", at=(0, 0), size=(1, 1))
        c = page.shapes.add_shape("Triangle", at=(0, 0), size=(1, 1))
        assert {a.shape_id, b.shape_id, c.shape_id} == {1, 2, 3}

    def its_name_is_readable_and_writable(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle")
        assert r.name is None
        r.name = "StartBox"
        assert r.name == "StartBox"

    def it_exposes_line_and_fill_cells(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle")
        assert r.line_weight is None
        r.line_weight = 0.5
        assert r.line_weight == 0.5
        r.line_color = "0"
        assert r.line_color == "0"
        r.fill_foregnd = "12"
        assert r.fill_foregnd == "12"


class DescribeAutoshapeDispatch:
    @pytest.mark.parametrize(
        "name_u, cls",
        [
            ("Rectangle", Rectangle),
            ("Ellipse", Ellipse),
            ("Triangle", Triangle),
        ],
    )
    def it_returns_the_right_subclass(self, name_u, cls):
        page = _fresh_page()
        s = page.shapes.add_shape(name_u, at=(0, 0), size=(1, 1))
        assert isinstance(s, cls)
        assert s.master_name_u == name_u


class DescribeTextShape:
    def it_reports_has_text_frame_true(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle")
        assert r.has_text_frame is True

    def it_passes_text_through_to_the_TextFrame(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle", text="Hello")
        assert r.text == "Hello"
        assert r.text_frame.text == "Hello"

    def it_can_rewrite_the_text(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle")
        r.text = "Goodbye"
        assert r.text == "Goodbye"
