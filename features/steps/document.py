"""Step implementations for ``doc.feature`` — the Visio() factory
and the document open / save round-trip surface.

Steps go through the public ``vsdx`` API only; no peeking at the
``oxml`` or part layers from this module.
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import io
import os

from behave import given, then, when
from helpers import default_template_path, scratch_path

import vsdx

# ---- Given ----------------------------------------------------------------


@given("the bundled default.vsdx template")
def given_bundled_default_template(context):  # type: ignore[no-untyped-def]
    try:
        path = default_template_path()
    except FileNotFoundError as exc:
        context.scenario.skip(reason=f"default.vsdx template not bundled: {exc}")
        return
    context.template_path = path


@given("a freshly-saved stencil at a temporary path")
def given_freshly_saved_stencil(context):  # type: ignore[no-untyped-def]
    stencil = vsdx.Stencil()
    out = scratch_path("doc-fresh-stencil.vssx")
    stencil.save(out)
    context.stencil_path = out


@given("a freshly-saved drawing at a temporary path")
def given_freshly_saved_drawing(context):  # type: ignore[no-untyped-def]
    drawing = vsdx.Visio()
    out = scratch_path("doc-fresh-drawing.vsdx")
    drawing.save(out)
    context.drawing_path = out


# ---- When -----------------------------------------------------------------


@when("I create a new document with vsdx.Visio()")
def when_create_new_document(context):  # type: ignore[no-untyped-def]
    context.document = vsdx.Visio()


@when("I call doc.pages.add_page()")
def when_call_pages_add_page(context):  # type: ignore[no-untyped-def]
    context.document.pages.add_page()


@when("I save the document to an io.BytesIO")
def when_save_document_to_bytesio(context):  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    context.document.save(buf)
    buf.seek(0)
    context.buffer = buf


@when("I save the document to a temporary path")
def when_save_document_to_path(context):  # type: ignore[no-untyped-def]
    out = scratch_path("doc-saved.vsdx")
    context.document.save(out)
    context.saved_path = out


@when("I open the template with vsdx.Visio()")
def when_open_template_with_visio(context):  # type: ignore[no-untyped-def]
    context.document = vsdx.Visio(context.template_path)


# ---- Then -----------------------------------------------------------------


@then("the document has zero pages")
def then_document_has_zero_pages(context):  # type: ignore[no-untyped-def]
    assert len(context.document.pages) == 0, (
        f"expected zero pages, got {len(context.document.pages)}"
    )


@then("the document has one page")
def then_document_has_one_page(context):  # type: ignore[no-untyped-def]
    assert len(context.document.pages) == 1, (
        f"expected one page, got {len(context.document.pages)}"
    )


@then("the document exposes a Pages collection")
def then_document_exposes_pages(context):  # type: ignore[no-untyped-def]
    assert isinstance(context.document.pages, vsdx.Pages), (
        f"expected vsdx.Pages, got {type(context.document.pages).__name__}"
    )


@then("the document exposes a Masters collection")
def then_document_exposes_masters(context):  # type: ignore[no-untyped-def]
    assert isinstance(context.document.masters, vsdx.Masters), (
        f"expected vsdx.Masters, got {type(context.document.masters).__name__}"
    )


@then("the buffer contains a ZIP starting with PK")
def then_buffer_starts_with_pk(context):  # type: ignore[no-untyped-def]
    raw = context.buffer.getvalue()
    assert raw[:2] == b"PK", f"expected PK magic, got {raw[:4]!r}"
    assert len(raw) > 100, f"buffer suspiciously small: {len(raw)} bytes"


@then("I can re-open the saved bytes as a Visio document")
def then_reopen_saved_bytes(context):  # type: ignore[no-untyped-def]
    context.buffer.seek(0)
    reopened = vsdx.Visio(context.buffer)
    # Round-trip didn't blow up; confirm the basic accessor stays live.
    # Don't touch ``.masters`` — Visio-authored packages legitimately
    # ship without a ``RT_VISIO_MASTERS`` rel and the proxy raises
    # KeyError on access in that case.
    _ = reopened.pages


@then("the file exists on disk")
def then_file_exists_on_disk(context):  # type: ignore[no-untyped-def]
    assert os.path.isfile(context.saved_path), (
        f"expected file at {context.saved_path}"
    )
    size = os.path.getsize(context.saved_path)
    assert size > 100, f"saved file suspiciously small: {size} bytes"


@then("the file opens cleanly with vsdx.Visio()")
def then_file_opens_cleanly(context):  # type: ignore[no-untyped-def]
    reopened = vsdx.Visio(context.saved_path)
    _ = reopened.pages


@then("the document carries a non-None theme")
def then_document_carries_theme(context):  # type: ignore[no-untyped-def]
    assert context.document.theme is not None, "expected document.theme to be present"


@then("opening it with vsdx.Visio() raises ValueError")
def then_visio_rejects_stencil(context):  # type: ignore[no-untyped-def]
    try:
        vsdx.Visio(context.stencil_path)
    except ValueError:
        return
    raise AssertionError("vsdx.Visio() did not raise ValueError on a stencil source")


@then("opening it with vsdx.Stencil() raises ValueError")
def then_stencil_rejects_drawing(context):  # type: ignore[no-untyped-def]
    try:
        vsdx.Stencil(context.drawing_path)
    except ValueError:
        return
    raise AssertionError("vsdx.Stencil() did not raise ValueError on a drawing source")
