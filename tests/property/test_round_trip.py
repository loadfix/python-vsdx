"""Round-trip property tests for python-vsdx.

Each property generates a random valid input, drives the public
authoring API, saves the Visio document to an in-memory buffer,
reloads it, and asserts the resulting document matches the input.

Pattern
-------

The strategies are deliberately narrow — they generate values that
the Visio schema considers valid (no lone surrogates, no XML control
characters; pin / size in the conventional inch range). When a
property test fails, Hypothesis's shrinker reports the minimal
failing input, which is usually a 1-2 character / single-shape
payload exposing a real fidelity bug.

To extend: add a new ``@composite`` strategy near the others, then a
new ``def it_round_trips_<thing>`` test that consumes it. Per-test
``@settings`` cap ``max_examples`` for the multi-shape property
since each example writes an entire .vsdx package.
"""

from __future__ import annotations

import io
import math
from typing import List, Tuple

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import given, settings, strategies as st  # noqa: E402

import vsdx  # noqa: E402


# ---- strategies -----------------------------------------------------


# XML 1.0 forbids most C0 control codepoints (only \t, \n, \r are
# allowed) and lone surrogates. lxml refuses to set element text
# containing any C0 control byte, so we keep the alphabet
# conservative: printable Unicode minus surrogates and minus all
# control characters.
_OOXML_TEXT_ALPHABET = st.characters(
    blacklist_categories=("Cs", "Cc"),
)


# Pin coordinates and shape size live in the inch coordinate space.
# Bound them to the conventional letter-page range so the round-trip
# property exercises typical values without bumping into Visio's
# edge-case behaviour around extremely large coordinates.
_INCH_COORD = st.floats(
    min_value=0.5,
    max_value=10.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)
_INCH_SIZE = st.floats(
    min_value=0.25,
    max_value=4.0,
    allow_nan=False,
    allow_infinity=False,
    width=64,
)


_SHAPE_KINDS = st.sampled_from(["Rectangle", "Ellipse", "Triangle"])


@st.composite
def shape_spec(
    draw: st.DrawFn,
) -> "Tuple[str, float, float, float, float, str]":
    kind = draw(_SHAPE_KINDS)
    pin_x = draw(_INCH_COORD)
    pin_y = draw(_INCH_COORD)
    width = draw(_INCH_SIZE)
    height = draw(_INCH_SIZE)
    text = draw(st.text(alphabet=_OOXML_TEXT_ALPHABET, min_size=0, max_size=40))
    return kind, pin_x, pin_y, width, height, text


@st.composite
def shape_specs(
    draw: st.DrawFn,
) -> "List[Tuple[str, float, float, float, float, str]]":
    return draw(st.lists(shape_spec(), min_size=1, max_size=4))


# ---- helpers --------------------------------------------------------


def _round_trip(doc: "vsdx.document.VisioDocument") -> "vsdx.document.VisioDocument":
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return vsdx.Visio(buf)


def _approx(actual: float, expected: float) -> bool:
    # Visio writes ``Cell/@V`` with six decimal digits of precision —
    # ``1.2890625`` rounds to ``1.289062`` on save. Tolerate that when
    # comparing pin / size after a round trip; the mantissa loss is
    # the format's, not a python-vsdx bug.
    return math.isclose(actual, expected, rel_tol=1e-5, abs_tol=1e-6)


# ---- tests ----------------------------------------------------------


class DescribeShapeRoundTrip:
    @given(shape_spec())
    def it_preserves_shape_pin_size_kind_and_text(
        self,
        spec: "Tuple[str, float, float, float, float, str]",
    ) -> None:
        kind, pin_x, pin_y, width, height, text = spec
        doc = vsdx.Visio()
        page = doc.pages.add_page("Page-1")
        page.shapes.add_shape(kind, at=(pin_x, pin_y), size=(width, height), text=text)

        doc2 = _round_trip(doc)
        out = list(doc2.pages[0].shapes)
        assert len(out) == 1
        sh = out[0]
        assert sh.master_name_u == kind
        assert _approx(sh.pin_x, pin_x)
        assert _approx(sh.pin_y, pin_y)
        assert _approx(sh.width, width)
        assert _approx(sh.height, height)
        assert sh.text == text


class DescribePageRoundTrip:
    @settings(max_examples=20)
    @given(shape_specs())
    def it_preserves_a_page_of_shapes(
        self,
        specs: "List[Tuple[str, float, float, float, float, str]]",
    ) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page("Page-1")
        for kind, pin_x, pin_y, width, height, text in specs:
            page.shapes.add_shape(
                kind, at=(pin_x, pin_y), size=(width, height), text=text,
            )

        doc2 = _round_trip(doc)
        out_shapes = list(doc2.pages[0].shapes)
        assert len(out_shapes) == len(specs)
        for sh, (kind, pin_x, pin_y, width, height, text) in zip(out_shapes, specs):
            assert sh.master_name_u == kind
            assert _approx(sh.pin_x, pin_x)
            assert _approx(sh.pin_y, pin_y)
            assert _approx(sh.width, width)
            assert _approx(sh.height, height)
            assert sh.text == text
