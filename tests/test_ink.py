"""Unit tests for the 0.3.0 Visio ink-annotation surface.

Covers :attr:`vsdx.page.Page.ink_strokes`,
:meth:`vsdx.page.Page.add_ink_stroke`, and
:attr:`vsdx.document.VisioDocument.ink_strokes`.

Scope: the python-ooxml-ink 0.2 adoption (R11-7). Author a stroke, save,
reload, and assert the stroke survives with its geometry + brush styling.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import io
import zipfile

import pytest

import vsdx
from vsdx.ink import InkStroke


# ---------------------------------------------------------------------------
# Page.ink_strokes + Page.add_ink_stroke
# ---------------------------------------------------------------------------


class DescribePageInkStrokes:
    def it_is_empty_on_a_fresh_page(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.ink_strokes == []

    def it_appends_a_stroke_and_exposes_it(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        stroke = page.add_ink_stroke(
            [(0.0, 0.0), (10.0, 10.0), (20.0, 5.0)]
        )
        assert isinstance(stroke, InkStroke)
        assert stroke.points == [(0.0, 0.0), (10.0, 10.0), (20.0, 5.0)]
        assert page.ink_strokes == [stroke] or len(page.ink_strokes) == 1

    def it_records_brush_color_and_width(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        stroke = page.add_ink_stroke(
            [(0, 0), (5, 5)], color="FF0000", width=2.5
        )
        assert stroke.color == "#FF0000"
        assert stroke.width == 2.5

    def it_accepts_a_hash_prefixed_color(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        stroke = page.add_ink_stroke(
            [(0, 0), (5, 5)], color="#00FF00"
        )
        assert stroke.color == "#00FF00"

    def it_records_per_point_pressure_from_three_tuples(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        stroke = page.add_ink_stroke(
            [(0, 0, 0.1), (10, 10, 0.5), (20, 5, 0.9)],
        )
        assert stroke.pressure == [0.1, 0.5, 0.9]

    def it_records_per_point_pressure_from_kwarg(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        stroke = page.add_ink_stroke(
            [(0, 0), (10, 10)],
            pressure=[0.25, 0.75],
        )
        assert stroke.pressure == [0.25, 0.75]

    def it_reuses_a_single_ink_part_across_strokes(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_ink_stroke([(0, 0), (1, 1)])
        page.add_ink_stroke([(2, 2), (3, 3)])
        page.add_ink_stroke([(4, 4), (5, 5)])
        assert len(page.ink_strokes) == 3

        # Verify only one ink part was created on the page.
        from ooxml_ink import RELATIONSHIP_TYPE_INK

        ink_rels = [
            rel
            for rel in page.part.rels.values()
            if not rel.is_external and rel.reltype == RELATIONSHIP_TYPE_INK
        ]
        assert len(ink_rels) == 1

    def it_rejects_an_empty_points_list(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(ValueError):
            page.add_ink_stroke([])

    def it_rejects_mismatched_pressure_length(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(ValueError):
            page.add_ink_stroke([(0, 0), (1, 1)], pressure=[0.5])


# ---------------------------------------------------------------------------
# VisioDocument.ink_strokes
# ---------------------------------------------------------------------------


class DescribeDocumentInkStrokes:
    def it_is_empty_on_a_fresh_document(self) -> None:
        doc = vsdx.Visio()
        assert doc.ink_strokes == []

    def it_aggregates_strokes_across_pages(self) -> None:
        doc = vsdx.Visio()
        p1 = doc.pages.add_page(name="P1")
        p2 = doc.pages.add_page(name="P2")
        p1.add_ink_stroke([(0, 0), (1, 1)])
        p2.add_ink_stroke([(2, 2), (3, 3)])
        p2.add_ink_stroke([(4, 4), (5, 5)])
        strokes = doc.ink_strokes
        assert len(strokes) == 3
        assert all(isinstance(s, InkStroke) for s in strokes)


# ---------------------------------------------------------------------------
# Save + reload round-trip
# ---------------------------------------------------------------------------


class DescribeInkStrokeRoundTrip:
    def it_survives_save_and_reload(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_ink_stroke(
            [(0, 0), (10, 10), (20, 5)], color="#FF0000", width=2.0
        )
        page.add_ink_stroke(
            [(50, 50), (60, 80)], width=3.0, pressure=[0.1, 0.9]
        )

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reopened = vsdx.Visio(buf)
        strokes = reopened.ink_strokes
        assert len(strokes) == 2

        # First stroke: no pressure, red + 2px.
        s0 = strokes[0]
        assert s0.points == [(0.0, 0.0), (10.0, 10.0), (20.0, 5.0)]
        assert s0.color == "#FF0000"
        assert s0.width == 2.0
        assert s0.pressure is None

        # Second stroke: pressure carried as third channel.
        s1 = strokes[1]
        assert s1.pressure == [0.1, 0.9]
        assert s1.width == 3.0

    def it_writes_an_ink_part_into_the_saved_package(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_ink_stroke([(0, 0), (10, 10)])

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        with zipfile.ZipFile(buf) as zf:
            names = zf.namelist()
        assert any(n.startswith("visio/ink/ink") and n.endswith(".xml") for n in names), (
            f"no /visio/ink/ink*.xml part in saved package: {names!r}"
        )

    def it_declares_the_ink_content_type_in_content_types_xml(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_ink_stroke([(0, 0), (10, 10)])

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        with zipfile.ZipFile(buf) as zf:
            content_types = zf.read("[Content_Types].xml").decode("utf-8")
        assert "application/inkml+xml" in content_types

    def it_survives_two_consecutive_roundtrips(self) -> None:
        # A stronger regression: open-then-save the reopened package and
        # verify the strokes still parse. Catches bugs where the ink-part
        # factory registration only runs on the first open.
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_ink_stroke(
            [(0, 0), (5, 5), (10, 0)], color="#0000FF", width=1.5
        )

        buf1 = io.BytesIO()
        doc.save(buf1)

        buf1.seek(0)
        reopened = vsdx.Visio(buf1)
        buf2 = io.BytesIO()
        reopened.save(buf2)

        buf2.seek(0)
        final = vsdx.Visio(buf2)
        strokes = final.ink_strokes
        assert len(strokes) == 1
        s = strokes[0]
        assert s.points == [(0.0, 0.0), (5.0, 5.0), (10.0, 0.0)]
        assert s.color == "#0000FF"
        assert s.width == 1.5


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class DescribePublicSurface:
    def it_exports_inkstroke_on_the_vsdx_namespace(self) -> None:
        assert vsdx.InkStroke is InkStroke
