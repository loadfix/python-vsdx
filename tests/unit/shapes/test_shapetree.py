"""Behavioural tests for :class:`ShapeTree`."""

from __future__ import annotations

import pytest

from vsdx import VS_SHAPE_TYPE, Visio
from vsdx.shapes import Connector, Ellipse, Rectangle, Shape


def _fresh_page():
    doc = Visio()
    return doc.pages.add_page()


class DescribeShapeTree:
    def it_starts_empty(self):
        assert len(_fresh_page().shapes) == 0

    def it_grows_as_shapes_are_added(self):
        page = _fresh_page()
        page.shapes.add_shape("Rectangle")
        page.shapes.add_shape("Ellipse")
        assert len(page.shapes) == 2

    def it_yields_shape_proxies_on_iteration(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle")
        e = page.shapes.add_shape("Ellipse")
        shapes = list(page.shapes)
        assert len(shapes) == 2
        assert isinstance(shapes[0], Rectangle)
        assert isinstance(shapes[1], Ellipse)
        # identity via element — proxy objects compare by wrapped element
        assert shapes[0] == r
        assert shapes[1] == e

    def it_accepts_VS_SHAPE_TYPE_members(self):
        page = _fresh_page()
        r = page.shapes.add_shape(VS_SHAPE_TYPE.RECTANGLE)
        assert isinstance(r, Rectangle)
        assert r.master_name_u == "Rectangle"

    def it_sets_geometry_from_at_and_size_tuples(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle", at=(5.0, 6.0), size=(2.0, 1.5))
        assert float(r.pin_x) == 5.0
        assert float(r.pin_y) == 6.0
        assert float(r.width) == 2.0
        assert float(r.height) == 1.5

    def it_passes_initial_text_through(self):
        page = _fresh_page()
        r = page.shapes.add_shape("Rectangle", text="Hi")
        assert r.text == "Hi"

    def it_can_add_a_shape_from_an_arbitrary_master(self):
        page = _fresh_page()
        s = page.shapes.add_shape_from_master("Star", at=(2, 2), size=(1, 1))
        assert s.master_name_u == "Star"
        assert float(s.pin_x) == 2.0


class DescribeAddConnector:
    def it_creates_a_Connector_proxy(self):
        page = _fresh_page()
        a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        b = page.shapes.add_shape("Ellipse", at=(5, 1), size=(1, 1))
        c = page.shapes.add_connector(a, b)
        assert isinstance(c, Connector)

    def it_glues_endpoints_to_anchor_pins(self):
        page = _fresh_page()
        a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        b = page.shapes.add_shape("Ellipse", at=(5, 3), size=(1, 1))
        c = page.shapes.add_connector(a, b)
        assert c.begin_x == 1.0
        assert c.begin_y == 1.0
        assert c.end_x == 5.0
        assert c.end_y == 3.0

    def it_writes_two_Connect_entries(self):
        page = _fresh_page()
        a = page.shapes.add_shape("Rectangle")
        b = page.shapes.add_shape("Ellipse")
        page.shapes.add_connector(a, b)
        # look into the oxml stub for the Connects element — two entries
        page_contents = page.shapes._element
        connects = page_contents.connects_element
        assert len(list(connects)) == 2
        first = list(connects)[0]
        assert first.get("FromCell") == "BeginX"
        assert first.get("ToCell") == "PinX"
        assert first.get("ToSheet") == str(a.shape_id)
        second = list(connects)[1]
        assert second.get("FromCell") == "EndX"
        assert second.get("ToSheet") == str(b.shape_id)

    def its_connector_id_is_unique(self):
        page = _fresh_page()
        a = page.shapes.add_shape("Rectangle")
        b = page.shapes.add_shape("Ellipse")
        c = page.shapes.add_connector(a, b)
        assert c.shape_id not in {a.shape_id, b.shape_id}

    def its_connector_route_style_is_writable(self):
        page = _fresh_page()
        a = page.shapes.add_shape("Rectangle")
        b = page.shapes.add_shape("Ellipse")
        c = page.shapes.add_connector(a, b)
        from vsdx.enum.shapes import VS_CONNECTOR_STYLE
        c.route_style = VS_CONNECTOR_STYLE.STRAIGHT
        assert c.route_style == VS_CONNECTOR_STYLE.STRAIGHT.value
