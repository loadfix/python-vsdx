"""Step implementations for ``shape.feature`` — ShapeTree.add_shape
on the four built-in masters plus geometry / text / iteration.
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import io

from behave import then, when

import vsdx

# ---- helpers --------------------------------------------------------------


def _add(context, kind: str, x: float, y: float, w: float, h: float, text=None):  # type: ignore[no-untyped-def]
    return context.page.shapes.add_shape(
        kind, at=(float(x), float(y)), size=(float(w), float(h)), text=text
    )


# ---- When -----------------------------------------------------------------


@when("I add a Rectangle at ({x:g}, {y:g}) sized ({w:g}, {h:g})")
def when_add_rectangle(context, x, y, w, h):  # type: ignore[no-untyped-def]
    context.shape = _add(context, vsdx.VS_SHAPE_TYPE.RECTANGLE, x, y, w, h)


@when("I add a Triangle at ({x:g}, {y:g}) sized ({w:g}, {h:g})")
def when_add_triangle(context, x, y, w, h):  # type: ignore[no-untyped-def]
    shape = _add(context, vsdx.VS_SHAPE_TYPE.TRIANGLE, x, y, w, h)
    # Carry both ``shape`` and ``shape2`` so the dual-add scenario can
    # reference the latest shape under either name.
    context.shape2 = shape
    context.shape = shape


@when("I add an Ellipse at ({x:g}, {y:g}) sized ({w:g}, {h:g})")
def when_add_ellipse_two(context, x, y, w, h):  # type: ignore[no-untyped-def]
    shape = _add(context, vsdx.VS_SHAPE_TYPE.ELLIPSE, x, y, w, h)
    context.shape2 = shape
    context.shape = shape


@when('I add a shape with master_name "{master}" at ({x:g}, {y:g}) sized ({w:g}, {h:g})')
def when_add_by_string(context, master, x, y, w, h):  # type: ignore[no-untyped-def]
    context.shape = _add(context, master, x, y, w, h)


@when('I add a Rectangle at ({x:g}, {y:g}) sized ({w:g}, {h:g}) with text "{text}"')
def when_add_rectangle_with_text(context, x, y, w, h, text):  # type: ignore[no-untyped-def]
    context.shape = _add(
        context, vsdx.VS_SHAPE_TYPE.RECTANGLE, x, y, w, h, text=text
    )


@when("I move the shape to ({x:g}, {y:g}) and resize to ({w:g}, {h:g})")
def when_move_and_resize(context, x, y, w, h):  # type: ignore[no-untyped-def]
    context.shape.set_geometry(float(x), float(y), float(w), float(h))


@when("I save the document and re-open from the buffer")
def when_roundtrip_buffer(context):  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    context.document.save(buf)
    buf.seek(0)
    context.document = vsdx.Visio(buf)
    if len(context.document.pages) > 0:
        context.page = context.document.pages[0]


# ---- Then -----------------------------------------------------------------


@then('the shape\'s master_name_u is "{name}"')
def then_master_name_u(context, name):  # type: ignore[no-untyped-def]
    assert context.shape.master_name_u == name, (
        f"expected master_name_u {name!r}, got {context.shape.master_name_u!r}"
    )


@then("the shape's pin is ({x:g}, {y:g})")
def then_shape_pin(context, x, y):  # type: ignore[no-untyped-def]
    px = float(context.shape.pin_x.inches)
    py = float(context.shape.pin_y.inches)
    assert abs(px - float(x)) < 1e-6, f"pin_x: expected {x}, got {px}"
    assert abs(py - float(y)) < 1e-6, f"pin_y: expected {y}, got {py}"


@then("the shape's size is ({w:g}, {h:g})")
def then_shape_size(context, w, h):  # type: ignore[no-untyped-def]
    sw = float(context.shape.width.inches)
    sh = float(context.shape.height.inches)
    assert abs(sw - float(w)) < 1e-6, f"width: expected {w}, got {sw}"
    assert abs(sh - float(h)) < 1e-6, f"height: expected {h}, got {sh}"


@then("the shape has a unique shape_id")
def then_shape_has_id(context):  # type: ignore[no-untyped-def]
    sid = context.shape.shape_id
    assert isinstance(sid, int) and sid > 0, f"unexpected shape_id {sid!r}"


@then('the shape\'s text reads back as "{text}"')
def then_shape_text(context, text):  # type: ignore[no-untyped-def]
    assert context.shape.text == text, (
        f"expected text {text!r}, got {context.shape.text!r}"
    )


@then("the page iterates two shapes")
def then_page_iterates_two_shapes(context):  # type: ignore[no-untyped-def]
    n = len(context.page.shapes)
    assert n == 2, n
    seen = list(context.page.shapes)
    assert len(seen) == 2, len(seen)


@then('the first shape\'s master_name_u is "{name}"')
def then_first_shape_master(context, name):  # type: ignore[no-untyped-def]
    assert context.page.shapes[0].master_name_u == name, (
        context.page.shapes[0].master_name_u
    )


@then('the second shape\'s master_name_u is "{name}"')
def then_second_shape_master(context, name):  # type: ignore[no-untyped-def]
    assert context.page.shapes[1].master_name_u == name, (
        context.page.shapes[1].master_name_u
    )


@then("the re-opened first page has one shape")
def then_reopened_one_shape(context):  # type: ignore[no-untyped-def]
    assert len(context.page.shapes) == 1, len(context.page.shapes)


@then('the re-opened first shape\'s text reads back as "{text}"')
def then_reopened_text(context, text):  # type: ignore[no-untyped-def]
    shape = context.page.shapes[0]
    assert shape.text == text, f"expected {text!r}, got {shape.text!r}"
