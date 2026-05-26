"""Step implementations for ``page.feature`` — Pages.add_page /
remove / iteration plus Page width / height / name geometry.
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


@given("a fresh blank document with one page")
def given_fresh_doc_one_page(context):  # type: ignore[no-untyped-def]
    context.document = vsdx.Visio()
    context.page = context.document.pages.add_page()


# ---- When -----------------------------------------------------------------


@when("I read the page width and height")
def when_read_page_geometry(context):  # type: ignore[no-untyped-def]
    context.page_width = float(context.page.width.inches)
    context.page_height = float(context.page.height.inches)


@when('I set the page name to "{name}"')
def when_set_page_name(context, name):  # type: ignore[no-untyped-def]
    context.page.name = name


@when("I set the page width to {value:g} inches")
def when_set_page_width(context, value):  # type: ignore[no-untyped-def]
    context.page.width = float(value)


@when("I set the page height to {value:g} inches")
def when_set_page_height(context, value):  # type: ignore[no-untyped-def]
    context.page.height = float(value)


@when("I add a second page")
def when_add_second_page(context):  # type: ignore[no-untyped-def]
    context.page2 = context.document.pages.add_page(name="Second")


@when("I remove the second page")
def when_remove_second_page(context):  # type: ignore[no-untyped-def]
    context.document.pages.remove(context.page2)


@when("I add a background page")
def when_add_background_page(context):  # type: ignore[no-untyped-def]
    context.bg_page = context.document.pages.add_background_page(name="Bkgrd")


@when("I assign the background page to the foreground page")
def when_assign_background(context):  # type: ignore[no-untyped-def]
    context.page.background_page = context.bg_page


# ---- Then -----------------------------------------------------------------


@then("the page width matches {value:g} inches")
def then_page_width(context, value):  # type: ignore[no-untyped-def]
    actual = float(context.page.width.inches)
    assert abs(actual - float(value)) < 1e-6, (
        f"expected page width {value} in, got {actual}"
    )


@then("the page height matches {value:g} inches")
def then_page_height(context, value):  # type: ignore[no-untyped-def]
    actual = float(context.page.height.inches)
    assert abs(actual - float(value)) < 1e-6, (
        f"expected page height {value} in, got {actual}"
    )


@then('the page name reads back as "{name}"')
def then_page_name(context, name):  # type: ignore[no-untyped-def]
    assert context.page.name == name, (
        f"expected page name {name!r}, got {context.page.name!r}"
    )


@then("the document iterates two pages")
def then_doc_iterates_two_pages(context):  # type: ignore[no-untyped-def]
    assert len(context.document.pages) == 2, len(context.document.pages)


@then("the document iterates one page")
def then_doc_iterates_one_page(context):  # type: ignore[no-untyped-def]
    assert len(context.document.pages) == 1, len(context.document.pages)


@then("the document indexes the pages by 0 and 1")
def then_doc_indexes_pages(context):  # type: ignore[no-untyped-def]
    p0 = context.document.pages[0]
    p1 = context.document.pages[1]
    assert isinstance(p0, vsdx.Page), type(p0).__name__
    assert isinstance(p1, vsdx.Page), type(p1).__name__
    assert p0 is not p1


@then("iterating doc.pages yields two Page objects")
def then_iter_yields_two_pages(context):  # type: ignore[no-untyped-def]
    seen = list(context.document.pages)
    assert len(seen) == 2, len(seen)
    for p in seen:
        assert isinstance(p, vsdx.Page), type(p).__name__


@then("the document has one foreground page")
def then_one_foreground(context):  # type: ignore[no-untyped-def]
    assert len(context.document.pages.foreground) == 1, (
        len(context.document.pages.foreground)
    )


@then("the document has one background page")
def then_one_background(context):  # type: ignore[no-untyped-def]
    assert len(context.document.pages.backgrounds) == 1, (
        len(context.document.pages.backgrounds)
    )


@then("the foreground page reports its background_page")
def then_fg_reports_bg(context):  # type: ignore[no-untyped-def]
    assert context.page.background_page is not None
    assert context.page.background_page.is_background is True
