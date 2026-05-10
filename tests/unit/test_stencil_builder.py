"""Behavioural tests for the 0.3.0 :class:`vsdx.Stencil` builder API.

Covers R16-2 deliverables:

- ``Stencil.new()`` — fresh empty stencil.
- ``Stencil.add_master(name, width, height, content_callback=...)``.
- ``Stencil.save(path)`` — write + reload round-trip.
- ``Master.add_shape(name, x, y, width, height)``.
- ``Stencil.from_shape_library(shapes)`` — bulk import.
- Backwards-compat: legacy ``Stencil()`` factory still returns a
  :class:`VisioDocument`.
"""

from __future__ import annotations

import io
import os
import tempfile

import pytest

import vsdx
from vsdx import Stencil, VisioDocument
from vsdx.constants import VSDX_KIND_STENCIL


class DescribeStencilNew:
    def it_builds_an_empty_stencil(self) -> None:
        sten = Stencil.new()
        assert isinstance(sten, Stencil)
        assert sten.package.kind == VSDX_KIND_STENCIL
        assert len(sten.masters) == 0

    def it_exposes_the_underlying_visiodocument(self) -> None:
        sten = Stencil.new()
        assert isinstance(sten.doc, VisioDocument)
        assert sten.doc.package is sten.package


class DescribeStencilAddMaster:
    def it_appends_a_master_with_the_given_name(self) -> None:
        sten = Stencil.new()
        m = sten.add_master("Cog", width=1.5, height=1.5)
        assert m.name_u == "Cog"
        assert len(sten.masters) == 1
        assert sten.masters["Cog"] is m

    def it_stamps_width_and_height_on_the_master_pagesheet(self) -> None:
        sten = Stencil.new()
        m = sten.add_master("Wide", width=2.25, height=0.5)
        # Width and Height cells live on the master-index <PageSheet>.
        assert m.get_cell("Width").get("V") == "2.25"
        assert m.get_cell("Height").get("V") == "0.5"

    def it_invokes_the_content_callback_with_the_master(self) -> None:
        captured = []

        def callback(master) -> None:
            captured.append(master)

        sten = Stencil.new()
        m = sten.add_master("X", 1.0, 1.0, content_callback=callback)
        assert captured == [m]

    def it_builds_three_masters_in_order(self) -> None:
        sten = Stencil.new()
        sten.add_master("A", 1.0, 1.0)
        sten.add_master("B", 2.0, 2.0)
        sten.add_master("C", 3.0, 3.0)
        assert [m.name_u for m in sten.masters] == ["A", "B", "C"]


class DescribeMasterAddShape:
    def it_appends_a_shape_to_master_contents(self) -> None:
        sten = Stencil.new()
        m = sten.add_master("Box", 1.0, 1.0)
        shape_el = m.add_shape("Sheet.1", x=0.5, y=0.5, width=1.0, height=1.0)
        assert shape_el is not None
        assert shape_el.get("Name") == "Sheet.1"
        assert shape_el.get("NameU") == "Sheet.1"

    def it_stamps_geometry_cells_on_the_shape(self) -> None:
        sten = Stencil.new()
        m = sten.add_master("Box", 1.0, 1.0)
        shape_el = m.add_shape("S1", x=0.5, y=0.75, width=1.25, height=2.0)
        cells = {c.get("N"): c.get("V") for c in shape_el.cell_lst}
        assert cells["PinX"] == "0.5"
        assert cells["PinY"] == "0.75"
        assert cells["Width"] == "1.25"
        assert cells["Height"] == "2"

    def it_allocates_page_scoped_shape_ids(self) -> None:
        sten = Stencil.new()
        m = sten.add_master("Box", 1.0, 1.0)
        s1 = m.add_shape("A", 0.0, 0.0, 1.0, 1.0)
        s2 = m.add_shape("B", 0.0, 0.0, 1.0, 1.0)
        assert int(s1.shape_id) == 1
        assert int(s2.shape_id) == 2

    def it_content_callback_can_add_shapes_inline(self) -> None:
        recorded = []

        def callback(master) -> None:
            recorded.append(master.add_shape("Inner", 0.0, 0.0, 1.0, 1.0))

        sten = Stencil.new()
        sten.add_master("Wrap", 1.0, 1.0, content_callback=callback)
        assert len(recorded) == 1
        assert recorded[0].get("Name") == "Inner"


class DescribeStencilSave:
    def it_writes_to_a_file_like_object(self) -> None:
        sten = Stencil.new()
        sten.add_master("A", 1.0, 1.0)
        buf = io.BytesIO()
        sten.save(buf)
        assert buf.tell() > 0
        # PK zip magic — the .vssx is an OPC zip package.
        assert buf.getvalue()[:2] == b"PK"

    def it_writes_to_a_filesystem_path(self) -> None:
        sten = Stencil.new()
        sten.add_master("A", 1.0, 1.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "lib.vssx")
            sten.save(path)
            assert os.path.getsize(path) > 0
            with open(path, "rb") as fh:
                assert fh.read(2) == b"PK"

    def it_round_trips_a_three_master_stencil(self) -> None:
        """R16-2 headline test: build, save, reload, assert."""
        sten = Stencil.new()

        def populate_cog(master) -> None:
            master.add_shape("Sheet.1", 0.5, 0.5, 1.0, 1.0)

        sten.add_master("Box", width=1.0, height=1.0)
        sten.add_master(
            "Cog", width=2.0, height=2.0, content_callback=populate_cog
        )
        sten.add_master("Arrow", width=3.0, height=0.5)

        buf = io.BytesIO()
        sten.save(buf)
        buf.seek(0)

        reloaded = vsdx.Stencil(buf)  # legacy factory — returns VisioDocument
        assert isinstance(reloaded, VisioDocument)
        assert reloaded.package.kind == VSDX_KIND_STENCIL
        assert [m.name_u for m in reloaded.masters] == ["Box", "Cog", "Arrow"]

        # The Cog master kept its populated shape across the round-trip.
        cog = reloaded.masters["Cog"]
        content_shape = cog._content_shape_element  # noqa: SLF001
        assert content_shape is not None
        assert content_shape.get("Name") == "Sheet.1"


class DescribeStencilFromShapeLibrary:
    def it_builds_one_master_per_pair(self) -> None:
        pairs = [
            ("Alpha", b"<svg>a</svg>"),
            ("Beta", b"<svg>b</svg>"),
            ("Gamma", b"PNG-bytes-go-here"),
        ]
        sten = Stencil.from_shape_library(pairs)
        assert isinstance(sten, Stencil)
        assert [m.name_u for m in sten.masters] == ["Alpha", "Beta", "Gamma"]

    def it_round_trips_through_save_reload(self) -> None:
        sten = Stencil.from_shape_library(
            [("One", b"<svg/>"), ("Two", b"<svg/>")]
        )
        buf = io.BytesIO()
        sten.save(buf)
        buf.seek(0)

        reloaded = vsdx.Stencil(buf)
        assert [m.name_u for m in reloaded.masters] == ["One", "Two"]

    def it_stashes_the_raw_payload_bytes(self) -> None:
        sten = Stencil.from_shape_library(
            [("A", b"payload-A"), ("B", b"payload-B")]
        )
        # ``_payload`` is an explicit in-memory stash, documented
        # as 0.3.0 caller-visible state for callers that want to
        # refine their own format-specific import layer on top.
        assert sten.masters["A"]._payload == b"payload-A"
        assert sten.masters["B"]._payload == b"payload-B"


class DescribeStencilBackwardsCompat:
    """``Stencil()`` as factory function still returns a VisioDocument."""

    def it_returns_a_visiodocument_when_called_as_factory(self) -> None:
        doc = Stencil()
        assert isinstance(doc, VisioDocument)
        assert doc.package.kind == VSDX_KIND_STENCIL

    def it_loads_an_existing_stencil_via_factory_path(self) -> None:
        sten = Stencil.new()
        sten.add_master("Z", 1.0, 1.0)
        buf = io.BytesIO()
        sten.save(buf)
        buf.seek(0)

        loaded = Stencil(buf)
        assert isinstance(loaded, VisioDocument)
        assert loaded.package.kind == VSDX_KIND_STENCIL

    def it_rejects_a_non_stencil_via_factory(self) -> None:
        # A drawing should not load as a stencil via the factory path.
        doc = vsdx.Visio()
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        with pytest.raises(ValueError):
            Stencil(buf)
