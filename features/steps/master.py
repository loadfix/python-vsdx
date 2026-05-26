"""Step implementations for ``master.feature`` — Masters.add_master /
ensure / resolve plus iteration / contains / indexing.
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from behave import then, when

import vsdx

# ---- When -----------------------------------------------------------------


@when("I add the Rectangle master")
def when_add_rectangle_master(context):  # type: ignore[no-untyped-def]
    context.master = context.document.masters.add_master(
        vsdx.VS_SHAPE_TYPE.RECTANGLE.value
    )


@when("I add the Ellipse master")
def when_add_ellipse_master(context):  # type: ignore[no-untyped-def]
    context.master = context.document.masters.add_master(
        vsdx.VS_SHAPE_TYPE.ELLIPSE.value
    )


@when("I add the Triangle master")
def when_add_triangle_master(context):  # type: ignore[no-untyped-def]
    context.master = context.document.masters.add_master(
        vsdx.VS_SHAPE_TYPE.TRIANGLE.value
    )


@when("I ensure the Triangle master")
def when_ensure_triangle_master(context):  # type: ignore[no-untyped-def]
    context.master = context.document.masters.ensure(
        vsdx.VS_SHAPE_TYPE.TRIANGLE.value
    )


@when("I ensure the Triangle master again")
def when_ensure_triangle_again(context):  # type: ignore[no-untyped-def]
    context.master_again = context.document.masters.ensure(
        vsdx.VS_SHAPE_TYPE.TRIANGLE.value
    )


# ---- Then -----------------------------------------------------------------


@then("the document has zero masters")
def then_zero_masters(context):  # type: ignore[no-untyped-def]
    assert len(context.document.masters) == 0, len(context.document.masters)


@then("the document has one master")
def then_one_master(context):  # type: ignore[no-untyped-def]
    assert len(context.document.masters) == 1, len(context.document.masters)


@then('the master\'s name_u is "{name}"')
def then_master_name_u(context, name):  # type: ignore[no-untyped-def]
    assert context.master.name_u == name, (
        f"expected {name!r}, got {context.master.name_u!r}"
    )


@then('the master_id is "{mid}"')
def then_master_id(context, mid):  # type: ignore[no-untyped-def]
    assert str(context.master.master_id) == mid, (
        f"expected {mid!r}, got {context.master.master_id!r}"
    )


@then("iterating masters yields one Master")
def then_iter_one_master(context):  # type: ignore[no-untyped-def]
    seen = list(context.document.masters)
    assert len(seen) == 1, len(seen)
    assert isinstance(seen[0], vsdx.Master), type(seen[0]).__name__


@then('the document masters contain "{name}"')
def then_masters_contain(context, name):  # type: ignore[no-untyped-def]
    assert name in context.document.masters, (
        f"expected {name!r} in masters, got {list(m.name_u for m in context.document.masters)}"
    )


@then('the document masters do not contain "{name}"')
def then_masters_not_contain(context, name):  # type: ignore[no-untyped-def]
    assert name not in context.document.masters


@then("doc.masters['{name}'] returns a Master with name_u \"{expected}\"")
def then_masters_getitem(context, name, expected):  # type: ignore[no-untyped-def]
    m = context.document.masters[name]
    assert isinstance(m, vsdx.Master), type(m).__name__
    assert m.name_u == expected, m.name_u


@then("doc.masters.resolve(None) returns None")
def then_resolve_none(context):  # type: ignore[no-untyped-def]
    assert context.document.masters.resolve(None) is None


@then("the re-opened document has one master")
def then_reopened_one_master(context):  # type: ignore[no-untyped-def]
    assert len(context.document.masters) == 1, len(context.document.masters)


@then('the re-opened master\'s name_u is "{name}"')
def then_reopened_master_name_u(context, name):  # type: ignore[no-untyped-def]
    masters = list(context.document.masters)
    assert masters, "no masters after re-open"
    assert masters[0].name_u == name, masters[0].name_u
