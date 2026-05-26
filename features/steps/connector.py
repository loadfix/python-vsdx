"""Step implementations for ``connector.feature`` — ShapeTree.add_connector
glue, source / target resolution, route_style, reroute().
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from behave import given, then, when

import vsdx

# ---- Given ----------------------------------------------------------------


@given("two anchor shapes at ({x1:g}, {y1:g}) and ({x2:g}, {y2:g})")
def given_two_anchors(context, x1, y1, x2, y2):  # type: ignore[no-untyped-def]
    context.anchor1 = context.page.shapes.add_shape(
        vsdx.VS_SHAPE_TYPE.RECTANGLE,
        at=(float(x1), float(y1)),
        size=(1.0, 1.0),
    )
    context.anchor2 = context.page.shapes.add_shape(
        vsdx.VS_SHAPE_TYPE.RECTANGLE,
        at=(float(x2), float(y2)),
        size=(1.0, 1.0),
    )


# ---- When -----------------------------------------------------------------


@when("I connect the two shapes")
def when_connect_two_shapes(context):  # type: ignore[no-untyped-def]
    context.connector = context.page.shapes.add_connector(
        context.anchor1, context.anchor2
    )


@when("I set the route style to right-angle")
def when_set_route_right_angle(context):  # type: ignore[no-untyped-def]
    context.connector.route_style = vsdx.VS_CONNECTOR_STYLE.RIGHT_ANGLE


@when("I reroute the connector")
def when_reroute_connector(context):  # type: ignore[no-untyped-def]
    context.connector.reroute()


# ---- Then -----------------------------------------------------------------


@then("the connector is a vsdx.Connector")
def then_connector_is_connector(context):  # type: ignore[no-untyped-def]
    assert isinstance(context.connector, vsdx.Connector), type(
        context.connector
    ).__name__


@then("the connector has a unique shape_id")
def then_connector_has_id(context):  # type: ignore[no-untyped-def]
    sid = context.connector.shape_id
    assert isinstance(sid, int) and sid > 0, sid
    assert sid != context.anchor1.shape_id
    assert sid != context.anchor2.shape_id


@then("the connector source is the first anchor")
def then_connector_source(context):  # type: ignore[no-untyped-def]
    src = context.connector.source_shape
    assert src is not None, "connector source resolved to None"
    assert src.shape_id == context.anchor1.shape_id


@then("the connector target is the second anchor")
def then_connector_target(context):  # type: ignore[no-untyped-def]
    tgt = context.connector.target_shape
    assert tgt is not None, "connector target resolved to None"
    assert tgt.shape_id == context.anchor2.shape_id


@then('the connector master_name_u is "{name}"')
def then_connector_master(context, name):  # type: ignore[no-untyped-def]
    assert context.connector.master_name_u == name, (
        f"expected {name!r}, got {context.connector.master_name_u!r}"
    )


@then("the connector route_style reads back as right-angle")
def then_route_style_right_angle(context):  # type: ignore[no-untyped-def]
    val = context.connector.route_style
    expected = vsdx.VS_CONNECTOR_STYLE.RIGHT_ANGLE.value
    # The setter accepts the enum but the getter returns the raw @V
    # string for forward compatibility — accept either form.
    assert str(val) == str(expected), f"expected {expected!r}, got {val!r}"


@then("the connector begin and end coordinates are populated")
def then_connector_begin_end(context):  # type: ignore[no-untyped-def]
    assert context.connector.begin_x is not None
    assert context.connector.begin_y is not None
    assert context.connector.end_x is not None
    assert context.connector.end_y is not None


@then("the first anchor reports one outbound connection")
def then_anchor1_outbound(context):  # type: ignore[no-untyped-def]
    out = list(context.anchor1.connections_out)
    assert len(out) == 1, f"expected 1 outbound, got {len(out)}"


@then("the second anchor reports one inbound connection")
def then_anchor2_inbound(context):  # type: ignore[no-untyped-def]
    inb = list(context.anchor2.connections_in)
    assert len(inb) == 1, f"expected 1 inbound, got {len(inb)}"


@then("the re-opened first page has three shapes")
def then_reopened_three_shapes(context):  # type: ignore[no-untyped-def]
    assert len(context.page.shapes) == 3, len(context.page.shapes)
