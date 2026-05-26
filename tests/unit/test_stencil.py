"""Behavioural tests for the 0.3.0 ``.vssx`` authoring surface.

Covers the public stencil API requested for vsdx-maturity-stencil:

- ``Stencil.new()`` + ``Stencil(path)`` — the two construction forms.
- ``Stencil.save(path)`` — write a ``.vssx`` round-trippably.
- ``Masters.add_master(name, base_id=...)`` + ``Masters.by_name(name)``.
- ``Master.shapes.add_shape(...)`` — keyword-form authoring.
- Cross-document master reuse via
  ``ShapeTree.add_master_instance(master, at=...)``.
- Byte-identical round-trip for unmodified reads.
- Content-type discrimination between ``.vsdx`` and ``.vssx``.

Sibling test files cover deeper builder semantics
(:mod:`tests.unit.test_stencil_builder`) and the part-layer
construction (:mod:`tests.unit.parts.test_stencil`).
"""

from __future__ import annotations

import io
import os
import tempfile

import pytest

import vsdx
from vsdx import Stencil, VisioDocument
from vsdx.constants import (
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_STENCIL_MAIN,
    VSDX_KIND_DRAWING,
    VSDX_KIND_STENCIL,
)

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class DescribeStencil:
    def it_can_be_created_from_scratch(self) -> None:
        sten = Stencil.new()

        assert isinstance(sten, Stencil)
        assert sten.package.kind == VSDX_KIND_STENCIL
        assert len(sten.masters) == 0

    def it_can_be_opened_from_a_file_like(self) -> None:
        # Author one, save to BytesIO, reopen via the legacy factory.
        sten = Stencil.new()
        sten.add_master("Box", 1.0, 1.0)
        buf = io.BytesIO()
        sten.save(buf)
        buf.seek(0)

        reopened = Stencil(buf)
        assert isinstance(reopened, VisioDocument)
        assert reopened.package.kind == VSDX_KIND_STENCIL
        assert [m.name_u for m in reopened.masters] == ["Box"]

    def it_can_be_opened_from_a_path(self) -> None:
        sten = Stencil.new()
        sten.add_master("Disk", 1.0, 1.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "lib.vssx")
            sten.save(path)
            assert os.path.getsize(path) > 0

            reopened = Stencil(path)
            assert isinstance(reopened, VisioDocument)
            assert reopened.package.kind == VSDX_KIND_STENCIL
            assert [m.name_u for m in reopened.masters] == ["Disk"]

    def it_writes_the_pk_zip_magic_to_a_file_like(self) -> None:
        sten = Stencil.new()
        buf = io.BytesIO()
        sten.save(buf)
        # OPC packages are zip files; first two bytes are ``PK``.
        assert buf.getvalue()[:2] == b"PK"

    def it_round_trips_byte_identical_for_unmodified_reads(self) -> None:
        """Three conformance constraints, #1: unmodified reads must round-trip."""
        sten = Stencil.new()
        sten.add_master("Box", 1.0, 1.0)
        sten.add_master("Cog", 2.0, 2.0)

        buf1 = io.BytesIO()
        sten.save(buf1)
        original = buf1.getvalue()

        # Reopen without any modifications, re-save.
        buf1.seek(0)
        reopened = Stencil(buf1)
        buf2 = io.BytesIO()
        reopened.save(buf2)
        resaved = buf2.getvalue()

        assert resaved == original, (
            "Unmodified read+save dropped byte parity — see the verbatim-blob "
            "preservation contract in vsdx.parts._verbatim."
        )

    def it_distinguishes_vssx_from_vsdx_content_type(self) -> None:
        """Round-trip a fresh stencil and a fresh drawing; verify they
        carry distinct root content-types and round-trip with their
        respective ``Stencil`` / ``Visio`` factories."""
        sten = Stencil.new()
        buf_s = io.BytesIO()
        sten.save(buf_s)

        doc = vsdx.Visio()
        buf_d = io.BytesIO()
        doc.save(buf_d)

        # -- the two packages' main-document parts carry distinct CTs --
        assert sten.package.main_document_part.content_type == CT_VSDX_STENCIL_MAIN
        assert doc.package.main_document_part.content_type == CT_VSDX_DRAWING_MAIN
        assert sten.package.kind == VSDX_KIND_STENCIL
        assert doc.package.kind == VSDX_KIND_DRAWING

        # -- the public factories round-trip respect the kinds --
        buf_s.seek(0)
        assert Stencil(buf_s).package.kind == VSDX_KIND_STENCIL
        buf_d.seek(0)
        assert vsdx.Visio(buf_d).package.kind == VSDX_KIND_DRAWING

    def it_stencil_factory_rejects_a_drawing(self) -> None:
        # The Stencil() factory path must reject a .vsdx package.
        doc = vsdx.Visio()
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        with pytest.raises(ValueError):
            Stencil(buf)

    def it_visio_factory_rejects_a_stencil(self) -> None:
        # The Visio() factory must reject a .vssx package.
        sten = Stencil.new()
        buf = io.BytesIO()
        sten.save(buf)
        buf.seek(0)
        with pytest.raises(ValueError):
            vsdx.Visio(buf)


# ---------------------------------------------------------------------------
# Masters collection
# ---------------------------------------------------------------------------


class DescribeStencilMasters:
    def it_adds_a_master(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master("Alpha")

        assert m.name_u == "Alpha"
        assert len(sten.masters) == 1

    def it_appends_masters_in_call_order(self) -> None:
        sten = Stencil.new()
        sten.masters.add_master("First")
        sten.masters.add_master("Second")
        sten.masters.add_master("Third")

        assert [m.name_u for m in sten.masters] == ["First", "Second", "Third"]

    def it_accepts_a_base_id_kwarg(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master(
            "WithGuid", base_id="{12345678-1234-1234-1234-123456789ABC}"
        )

        assert m.base_id == "{12345678-1234-1234-1234-123456789ABC}"

    def it_accepts_a_unique_id_kwarg(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master(
            "WithUid", unique_id="{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
        )

        assert m.unique_id == "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"

    def it_can_be_looked_up_by_name(self) -> None:
        sten = Stencil.new()
        a = sten.masters.add_master("Alpha")
        b = sten.masters.add_master("Beta")

        assert sten.masters.by_name("Alpha") is a
        assert sten.masters.by_name("Beta") is b

    def it_returns_none_for_missing_name(self) -> None:
        sten = Stencil.new()
        sten.masters.add_master("Present")

        assert sten.masters.by_name("Absent") is None

    def it_supports_dict_style_lookup(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master("Disk")

        # ``masters["Disk"]`` is the existing dict-style accessor —
        # reaffirmed alongside ``by_name`` so contract drift is caught.
        assert sten.masters["Disk"] is m

    def it_supports_indexed_access(self) -> None:
        sten = Stencil.new()
        a = sten.masters.add_master("A")
        b = sten.masters.add_master("B")

        assert sten.masters[0] is a
        assert sten.masters[1] is b

    def it_supports_contains_check(self) -> None:
        sten = Stencil.new()
        sten.masters.add_master("Present")

        assert "Present" in sten.masters
        assert "Absent" not in sten.masters


# ---------------------------------------------------------------------------
# Master.shapes — keyword-form authoring
# ---------------------------------------------------------------------------


class DescribeMasterShapes:
    def it_exposes_a_shape_tree_proxy(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master("Box")

        from vsdx.master import MasterShapeTree

        assert isinstance(m.shapes, MasterShapeTree)

    def it_adds_a_shape_via_keyword_form(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master("Box")
        shape_el = m.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))

        assert shape_el.get("Name") == "Rectangle"
        cells = {c.get("N"): c.get("V") for c in shape_el.cell_lst}
        assert cells["PinX"] == "0"
        assert cells["PinY"] == "0"
        assert cells["Width"] == "1"
        assert cells["Height"] == "1"

    def it_accepts_a_vs_shape_type_member(self) -> None:
        from vsdx.enum.shapes import VS_SHAPE_TYPE

        sten = Stencil.new()
        m = sten.masters.add_master("Box")
        shape_el = m.shapes.add_shape(
            VS_SHAPE_TYPE.ELLIPSE, at=(2, 3), size=(1, 1)
        )

        assert shape_el.get("Name") == "Ellipse"

    def it_iterates_over_master_shapes(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master("Box")
        m.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        m.shapes.add_shape("Ellipse", at=(2, 0), size=(1, 1))

        names = [s.get("Name") for s in m.shapes]
        assert names == ["Rectangle", "Ellipse"]

    def it_reports_master_shape_count_via_len(self) -> None:
        sten = Stencil.new()
        m = sten.masters.add_master("Box")
        assert len(m.shapes) == 0
        m.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))
        assert len(m.shapes) == 1


# ---------------------------------------------------------------------------
# Cross-document master reuse
# ---------------------------------------------------------------------------


class DescribeMasterReuse:
    def it_copies_a_master_into_a_destination_document(self) -> None:
        # Build a stencil with one master holding a single shape.
        sten = Stencil.new()
        m_src = sten.masters.add_master("MyBox")
        m_src.shapes.add_shape("Rectangle", at=(0.5, 0.5), size=(1, 1))

        # Drop an instance of the stencil's master onto a drawing.
        doc = vsdx.Visio()
        page = doc.pages.add_page()
        instance = page.shapes.add_master_instance(m_src, at=(2, 2))

        # The destination document has acquired its own copy of the master.
        assert "MyBox" in doc.masters
        # And the freshly-dropped shape references that master by NameU.
        assert instance.pin_x == 2.0
        assert instance.pin_y == 2.0

    def it_carries_master_contents_into_the_destination(self) -> None:
        # Master shapes in the source must round-trip into the destination's
        # master-contents part — the destination is now self-contained
        # (no live reference back into the source stencil).
        sten = Stencil.new()
        m_src = sten.masters.add_master("Wedge")
        m_src.shapes.add_shape("Triangle", at=(0.5, 0.5), size=(1, 1))

        doc = vsdx.Visio()
        page = doc.pages.add_page()
        page.shapes.add_master_instance(m_src, at=(1, 1))

        m_dst = doc.masters.by_name("Wedge")
        assert m_dst is not None
        assert len(m_dst.shapes) == 1
        # The destination's contents element is a *separate* tree,
        # not a live alias into the stencil's tree.
        src_contents = m_src._master_part.element  # noqa: SLF001
        dst_contents = m_dst._master_part.element  # noqa: SLF001
        assert src_contents is not dst_contents

    def it_does_not_duplicate_an_already_imported_master(self) -> None:
        sten = Stencil.new()
        m_src = sten.masters.add_master("Once")

        doc = vsdx.Visio()
        page = doc.pages.add_page()

        page.shapes.add_master_instance(m_src, at=(1, 1))
        page.shapes.add_master_instance(m_src, at=(2, 2))
        page.shapes.add_master_instance(m_src, at=(3, 3))

        # Same NameU re-used → only one master entry on the destination.
        assert [m.name_u for m in doc.masters] == ["Once"]

    def it_propagates_base_id_on_import(self) -> None:
        sten = Stencil.new()
        m_src = sten.masters.add_master(
            "Ident", base_id="{11111111-1111-1111-1111-111111111111}"
        )

        doc = vsdx.Visio()
        page = doc.pages.add_page()
        page.shapes.add_master_instance(m_src, at=(1, 1))

        m_dst = doc.masters.by_name("Ident")
        assert m_dst is not None
        assert m_dst.base_id == "{11111111-1111-1111-1111-111111111111}"

    def it_matches_a_pre_existing_master_by_base_id(self) -> None:
        # If the destination already has a master with the same BaseID
        # (lineage marker), the importer must reuse it rather than
        # adding a duplicate under a slightly-different NameU.
        guid = "{22222222-2222-2222-2222-222222222222}"
        sten = Stencil.new()
        m_src = sten.masters.add_master("StencilName", base_id=guid)

        doc = vsdx.Visio()
        # Pre-register a master with the same lineage but a different NameU.
        doc.masters.add_master("DocLocalName", base_id=guid)
        page = doc.pages.add_page()
        page.shapes.add_master_instance(m_src, at=(1, 1))

        # No new master got added — the BaseID match wins.
        assert len(doc.masters) == 1
        assert doc.masters[0].name_u == "DocLocalName"

    def it_round_trips_a_drawing_with_imported_masters(self) -> None:
        # The full flow: stencil → drawing → save → reopen → assert.
        sten = Stencil.new()
        m_src = sten.masters.add_master("Cog")
        m_src.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))

        doc = vsdx.Visio()
        page = doc.pages.add_page()
        page.shapes.add_master_instance(m_src, at=(1, 1))
        page.shapes.add_master_instance(m_src, at=(3, 3))

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        reloaded = vsdx.Visio(buf)
        assert "Cog" in reloaded.masters
        assert len(list(reloaded.pages[0].shapes)) == 2

    def it_rejects_a_non_master_argument(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page()

        with pytest.raises(TypeError):
            page.shapes.add_master_instance("not-a-master", at=(0, 0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stencil → drawing flow (the headline scenario from the goal example)
# ---------------------------------------------------------------------------


class DescribeStencilEndToEnd:
    def it_supports_the_goal_example_flow(self) -> None:
        # Mirrors the goal-example block from the maturity brief.
        stencil = Stencil.new()
        master = stencil.masters.add_master(
            name="MyBox",
            base_id="{12345678-1234-1234-1234-123456789ABC}",
        )
        master.shapes.add_shape("Rectangle", at=(0, 0), size=(1, 1))

        with tempfile.TemporaryDirectory() as tmpdir:
            stencil_path = os.path.join(tmpdir, "my-stencil.vssx")
            stencil.save(stencil_path)
            assert os.path.getsize(stencil_path) > 0

            # Reopen the stencil.
            s2 = Stencil(stencil_path)
            assert [m.name_u for m in s2.masters] == ["MyBox"]

            # Drop an instance of the master onto a fresh drawing.
            doc = vsdx.Visio()
            page = doc.pages.add_page()
            my_master = stencil.masters.by_name("MyBox")
            assert my_master is not None
            instance = page.shapes.add_master_instance(my_master, at=(2, 2))
            assert instance is not None
            assert "MyBox" in doc.masters
