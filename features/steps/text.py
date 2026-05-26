"""Step implementations for ``text.feature`` — TextFrame / Paragraph
/ Run round-tripping at the public-API level.
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

from behave import then, when

# ---- When -----------------------------------------------------------------


@when('I set the shape text to "{value}"')
def when_set_shape_text(context, value):  # type: ignore[no-untyped-def]
    context.shape.text = value


@when('I set the text_frame text to "{value}"')
def when_set_text_frame_text(context, value):  # type: ignore[no-untyped-def]
    context.shape.text_frame.text = value


@when("I clear the text_frame")
def when_clear_text_frame(context):  # type: ignore[no-untyped-def]
    context.shape.text_frame.clear()


# ---- Then -----------------------------------------------------------------


@then("the shape exposes a text_frame")
def then_shape_exposes_text_frame(context):  # type: ignore[no-untyped-def]
    assert context.shape.text_frame is not None, (
        "shape.text_frame returned None"
    )


@then("the text_frame text is empty")
def then_text_frame_empty(context):  # type: ignore[no-untyped-def]
    assert context.shape.text_frame.text == "", (
        f"expected empty, got {context.shape.text_frame.text!r}"
    )


@then("the shape exposes has_text_frame True")
def then_has_text_frame_true(context):  # type: ignore[no-untyped-def]
    assert context.shape.has_text_frame is True


@then("the text_frame paragraphs list has length {n:d}")
def then_paragraphs_length(context, n):  # type: ignore[no-untyped-def]
    paras = context.shape.text_frame.paragraphs
    assert len(paras) == int(n), (
        f"expected {n} paragraphs, got {len(paras)}"
    )


@then('the shape\'s text reads back as ""')
def then_shape_text_empty(context):  # type: ignore[no-untyped-def]
    assert context.shape.text == "", (
        f"expected empty text, got {context.shape.text!r}"
    )
