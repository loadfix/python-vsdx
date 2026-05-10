"""Behavioural tests for the R14 connector auto-route surface.

Covers:

- :meth:`Page.connect` — high-level drop-a-connector helper, including
  nearest-edge connection-point selection and custom master.
- :attr:`Shape.connections_in` / :attr:`Shape.connections_out` — the
  connector-neighbourhood properties.
- :attr:`Connector.source_shape` / :attr:`Connector.target_shape` /
  :attr:`Connector.source_point` / :attr:`Connector.target_point` —
  typed endpoint proxies over the ``<Connect>`` rows.
- :meth:`Connector.reroute` — re-snaps endpoint cells to the current
  glue.
- End-to-end save-and-reload round trip.
"""

from __future__ import annotations

import io

import vsdx
from vsdx import Visio
from vsdx.connection_points import CONNECTION_TYPE, ConnectionPoint
from vsdx.shapes import Connector


def _two_shape_page():
    doc = Visio()
    page = doc.pages.add_page(name="Flow")
    a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(2, 1))
    b = page.shapes.add_shape("Ellipse", at=(6, 1), size=(2, 1))
    return doc, page, a, b


class DescribePageConnect:
    def it_drops_a_Connector_between_two_shapes(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        assert isinstance(c, Connector)

    def it_glues_begin_and_end_to_the_two_anchor_shape_pins_by_default(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        assert c.begin_x == float(a.pin_x)
        assert c.begin_y == float(a.pin_y)
        assert c.end_x == float(b.pin_x)
        assert c.end_y == float(b.pin_y)

    def it_accepts_a_custom_master(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b, connector_master="Dynamic connector")
        # Master-name round-trips through the shape element
        assert c.master_name_u == "Dynamic connector"

    def it_uses_an_explicit_source_point_when_given(self):
        _, page, a, b = _two_shape_page()
        # Add a connection point on the right edge of ``a``
        p_right = a.connection_points.add(2.0, 0.5, type=CONNECTION_TYPE.INWARD)
        c = page.connect(a, b, source_point=p_right)
        # World-x of the point is a.pin_x - a.width/2 + 2.0 = 1 - 1 + 2 = 2.0
        assert c.begin_x == 2.0
        assert c.source_point is not None
        assert c.source_point.index == p_right.index

    def it_auto_picks_the_nearest_edge_connection_point(self):
        _, page, a, b = _two_shape_page()
        # Add two connection points on ``a``: one left-edge, one right-edge.
        a.connection_points.add(0.0, 0.5)  # world x=0.0
        right = a.connection_points.add(2.0, 0.5)  # world x=2.0
        # Target sits to the right — nearest-edge pick is the right point.
        c = page.connect(a, b)
        assert c.source_point is not None
        assert c.source_point.index == right.index

    def it_writes_two_Connect_entries(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        entries = list(page.shapes._element.connects_element)
        assert len(entries) == 2
        assert entries[0].get("FromCell") == "BeginX"
        assert entries[0].get("FromSheet") == str(c.shape_id)
        assert entries[0].get("ToSheet") == str(a.shape_id)
        assert entries[1].get("FromCell") == "EndX"

    def it_writes_Connections_XN_ToCell_for_a_specific_connection_point(self):
        _, page, a, b = _two_shape_page()
        p = a.connection_points.add(2.0, 0.5)
        page.connect(a, b, source_point=p)
        entries = list(page.shapes._element.connects_element)
        assert entries[0].get("ToCell") == "Connections.X%d" % p.index

    def it_falls_back_to_PinX_ToCell_when_the_shape_has_no_connection_points(self):
        _, page, a, b = _two_shape_page()
        # Neither shape carries a Connection section
        page.connect(a, b)
        entries = list(page.shapes._element.connects_element)
        assert entries[0].get("ToCell") == "PinX"
        assert entries[1].get("ToCell") == "PinX"


class DescribeConnectorEndpoints:
    def it_resolves_source_and_target_shapes_from_glue(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        assert c.source_shape is not None
        assert c.source_shape.shape_id == a.shape_id
        assert c.target_shape is not None
        assert c.target_shape.shape_id == b.shape_id

    def it_returns_None_for_ungluedendpoints(self):
        # Directly instantiating a connector via the tree skips <Connects>.
        _, page, _, _ = _two_shape_page()
        conn_shape = page.shapes._element.shapes_element.add_shape(
            master_name_u="Dynamic connector"
        )
        conn_shape.shape_id = page.next_shape_id()
        c = Connector(conn_shape, page.shapes)
        assert c.source_shape is None
        assert c.target_shape is None

    def it_resolves_source_and_target_points_when_glued_to_connections(self):
        _, page, a, b = _two_shape_page()
        pa = a.connection_points.add(2.0, 0.5)
        pb = b.connection_points.add(0.0, 0.5)
        c = page.connect(a, b, source_point=pa, target_point=pb)
        assert isinstance(c.source_point, ConnectionPoint)
        assert c.source_point.index == pa.index
        assert isinstance(c.target_point, ConnectionPoint)
        assert c.target_point.index == pb.index

    def it_returns_None_source_point_for_centre_pin_glue(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        assert c.source_point is None
        assert c.target_point is None


class DescribeShapeConnections:
    def it_reports_incoming_connectors_on_the_target(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        incoming = b.connections_in
        assert len(incoming) == 1
        assert incoming[0].shape_id == c.shape_id

    def it_reports_outgoing_connectors_on_the_source(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        outgoing = a.connections_out
        assert len(outgoing) == 1
        assert outgoing[0].shape_id == c.shape_id

    def it_reports_empty_lists_for_an_isolated_shape(self):
        _, page, a, b = _two_shape_page()
        # no connectors yet
        assert a.connections_in == []
        assert a.connections_out == []
        assert b.connections_in == []
        assert b.connections_out == []

    def it_handles_multiple_connectors_on_the_same_shape(self):
        doc = Visio()
        page = doc.pages.add_page()
        hub = page.shapes.add_shape("Ellipse", at=(4, 4), size=(1, 1))
        n1 = page.shapes.add_shape("Rectangle", at=(1, 4), size=(1, 1))
        n2 = page.shapes.add_shape("Rectangle", at=(7, 4), size=(1, 1))
        page.connect(n1, hub)
        page.connect(n2, hub)
        assert len(hub.connections_in) == 2
        assert hub.connections_out == []


class DescribeConnectorReroute:
    def it_resnaps_endpoints_after_the_anchors_move(self):
        _, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        assert c.begin_x == 1.0
        # move ``a`` to a new pin; cells are stale until reroute.
        a.pin_x = 3.0
        a.pin_y = 2.0
        assert c.begin_x == 1.0  # cached value on the connector shape
        c.reroute()
        assert c.begin_x == 3.0
        assert c.begin_y == 2.0

    def it_resnaps_to_a_glued_connection_point(self):
        _, page, a, b = _two_shape_page()
        p = a.connection_points.add(2.0, 0.5)
        c = page.connect(a, b, source_point=p)
        # move the connection-point's local offset — reroute pulls the
        # world coordinate through the current cell values.
        p.x = 1.0
        c.reroute()
        # world x = 1 - 1 + 1 = 1.0
        assert c.begin_x == 1.0

    def it_is_a_noop_on_a_bare_connector_with_no_glue(self):
        _, page, _, _ = _two_shape_page()
        conn_shape = page.shapes._element.shapes_element.add_shape(
            master_name_u="Dynamic connector"
        )
        conn_shape.shape_id = page.next_shape_id()
        c = Connector(conn_shape, page.shapes)
        # no raise
        c.reroute()
        # cells remain untouched (none were ever set).
        assert c.begin_x is None
        assert c.end_x is None


class DescribeRoundTrip:
    def it_survives_save_and_reload(self):
        """Build a 2-shape + connector page, save, reload, assert connectivity survives.

        Reload uses raw ``lxml.etree`` walks rather than the authoring
        proxies because the PagePart parse-path goes through the
        ``ooxml_opc`` shared parser, which doesn't carry the vsdx
        element-class lookup — reloaded parts come back as plain
        ``_Element``.  Round-trip fidelity at the *bytes* level is the
        tested invariant for R14; the proxy-rebind round-trip is a
        documented follow-up on the PagePart load path.
        """
        from lxml import etree

        doc, page, a, b = _two_shape_page()
        pa = a.connection_points.add(2.0, 0.5)
        pb = b.connection_points.add(0.0, 0.5)
        c = page.connect(a, b, source_point=pa, target_point=pb)
        orig_conn_id = c.shape_id
        orig_a_id = a.shape_id
        orig_b_id = b.shape_id

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        assert len(reopened.pages) == 1
        page2 = reopened.pages[0]
        page_contents = page2._page_part.element

        NS = "{http://schemas.microsoft.com/office/visio/2011/1/core}"
        shapes_el = page_contents.find(f"{NS}Shapes")
        assert shapes_el is not None
        shape_ids = {int(s.get("ID")) for s in shapes_el.findall(f"{NS}Shape")}
        assert orig_a_id in shape_ids
        assert orig_b_id in shape_ids
        assert orig_conn_id in shape_ids

        # Two <Connect> entries land in the reloaded <Connects>.
        connects_el = page_contents.find(f"{NS}Connects")
        assert connects_el is not None
        entries = connects_el.findall(f"{NS}Connect")
        assert len(entries) == 2

        # Source glue — ``BeginX`` → source_shape + ``Connections.X<pa.index>``.
        begin_entry = next(e for e in entries if e.get("FromCell") == "BeginX")
        assert begin_entry.get("FromSheet") == str(orig_conn_id)
        assert begin_entry.get("ToSheet") == str(orig_a_id)
        assert begin_entry.get("ToCell") == "Connections.X%d" % pa.index

        # Target glue — ``EndX`` → target_shape + ``Connections.X<pb.index>``.
        end_entry = next(e for e in entries if e.get("FromCell") == "EndX")
        assert end_entry.get("FromSheet") == str(orig_conn_id)
        assert end_entry.get("ToSheet") == str(orig_b_id)
        assert end_entry.get("ToCell") == "Connections.X%d" % pb.index

    def it_round_trips_centre_pin_glue(self):
        """Centre-pin glue (no connection points) round-trips as ``ToCell="PinX"``."""
        doc, page, a, b = _two_shape_page()
        c = page.connect(a, b)
        orig_conn_id = c.shape_id

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        page_contents = reopened.pages[0]._page_part.element
        NS = "{http://schemas.microsoft.com/office/visio/2011/1/core}"
        connects = page_contents.find(f"{NS}Connects")
        assert connects is not None
        entries = connects.findall(f"{NS}Connect")
        assert len(entries) == 2
        for e in entries:
            assert e.get("FromSheet") == str(orig_conn_id)
            assert e.get("ToCell") == "PinX"
