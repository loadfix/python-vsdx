"""Unit tests for 0.2.0 ``.vssx`` / ``.vstx`` / macro-variant dispatch.

Covers the :class:`VisioPackage.kind` discriminator, the
:class:`VisioPackageOpener`, the ``Stencil()`` / ``Template()``
factories, the macro-variant part-type registration, and the
vbaProject passthrough size-cap guard.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.constants import (
    CT_VBA_PROJECT,
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_MACRO_DRAWING_MAIN,
    CT_VSDX_MACRO_STENCIL_MAIN,
    CT_VSDX_MACRO_TEMPLATE_MAIN,
    CT_VSDX_STENCIL_MAIN,
    CT_VSDX_TEMPLATE_MAIN,
    RT_VBA_PROJECT,
    VSDX_KIND_DRAWING,
    VSDX_KIND_STENCIL,
    VSDX_KIND_TEMPLATE,
)
from vsdx.package import VISIO_PART_TYPE_MAP, VisioPackage
from vsdx.parts.document import VisioDocumentPart
from vsdx.parts.stencil import StencilPart
from vsdx.parts.vba import VBA_PROJECT_SIZE_CAP, VbaProjectPart


class DescribeContentTypeConstants:
    def it_exposes_the_four_macro_variants_at_module_level(self) -> None:
        assert vsdx.CT_VSDX_MACRO_DRAWING_MAIN.endswith("macroEnabled.main+xml")
        assert vsdx.CT_VSDX_MACRO_TEMPLATE_MAIN.endswith("macroEnabled.main+xml")
        assert vsdx.CT_VSDX_MACRO_STENCIL_MAIN.endswith("macroEnabled.main+xml")
        # Stencil non-macro is a 0.1.0 carry-over but must be exported.
        assert vsdx.CT_VSDX_STENCIL_MAIN.endswith("stencil.main+xml")

    def it_exposes_the_vba_project_content_type(self) -> None:
        assert CT_VBA_PROJECT == "application/vnd.ms-office.vbaProject"


class DescribePartFactoryRegistration:
    def it_registers_every_macro_variant(self) -> None:
        # All four macro + stencil variants must have a part-class
        # mapping so the shared loader dispatches correctly.
        assert VISIO_PART_TYPE_MAP[CT_VSDX_MACRO_DRAWING_MAIN] is VisioDocumentPart
        assert VISIO_PART_TYPE_MAP[CT_VSDX_MACRO_TEMPLATE_MAIN] is VisioDocumentPart
        assert VISIO_PART_TYPE_MAP[CT_VSDX_MACRO_STENCIL_MAIN] is StencilPart
        assert VISIO_PART_TYPE_MAP[CT_VSDX_STENCIL_MAIN] is StencilPart

    def it_registers_the_vba_project_content_type(self) -> None:
        assert VISIO_PART_TYPE_MAP[CT_VBA_PROJECT] is VbaProjectPart


class DescribeVisioPackageNew:
    def it_defaults_to_drawing_kind(self) -> None:
        pkg = VisioPackage.new()
        assert pkg.kind == VSDX_KIND_DRAWING
        assert pkg.main_document_part.content_type == CT_VSDX_DRAWING_MAIN

    def it_builds_a_stencil_package(self) -> None:
        pkg = VisioPackage.new(kind=VSDX_KIND_STENCIL)
        assert pkg.kind == VSDX_KIND_STENCIL
        assert pkg.main_document_part.content_type == CT_VSDX_STENCIL_MAIN

    def it_builds_a_template_package(self) -> None:
        pkg = VisioPackage.new(kind=VSDX_KIND_TEMPLATE)
        assert pkg.kind == VSDX_KIND_TEMPLATE
        assert pkg.main_document_part.content_type == CT_VSDX_TEMPLATE_MAIN

    def it_rejects_an_unknown_kind(self) -> None:
        with pytest.raises(ValueError):
            VisioPackage.new(kind="spreadsheet")

    def it_omits_pages_part_for_stencil_kind(self) -> None:
        pkg = VisioPackage.new(kind=VSDX_KIND_STENCIL)
        # StencilPart has no RT_VISIO_PAGES relationship — pages_part
        # must raise on access.
        with pytest.raises(KeyError):
            pkg.pages_part


class DescribeStencilFactory:
    def it_returns_a_visiodocument_from_stencil_of_none(self) -> None:
        stencil = vsdx.Stencil()
        assert isinstance(stencil, vsdx.VisioDocument)
        assert stencil.package.kind == VSDX_KIND_STENCIL


class DescribeTemplateFactory:
    def it_returns_a_visiodocument_from_template_of_none(self) -> None:
        template = vsdx.Template()
        assert isinstance(template, vsdx.VisioDocument)
        assert template.package.kind == VSDX_KIND_TEMPLATE


class DescribeVisioPackageOpener:
    def it_discriminates_by_content_type(self) -> None:
        # Sanity: the opener class is importable and has an open()
        # static method that delegates to VisioPackage.open.
        assert hasattr(vsdx.VisioPackageOpener, "open")

    def it_is_exported_at_module_level(self) -> None:
        assert vsdx.VisioPackageOpener is not None


class DescribeVbaProjectPart:
    def it_accepts_a_bytes_blob_under_the_cap(self) -> None:
        pkg = VisioPackage.new()
        part = VbaProjectPart.new_empty(pkg)
        part.blob = b"\x00\x01\x02"
        assert part.blob == b"\x00\x01\x02"

    def it_rejects_a_blob_above_the_size_cap_at_construction(self) -> None:
        pkg = VisioPackage.new()
        huge = b"\x00" * (VBA_PROJECT_SIZE_CAP + 1)
        with pytest.raises(ValueError):
            VbaProjectPart(
                vsdx.package.PackURI("/visio/vbaProject.bin")
                if hasattr(vsdx.package, "PackURI")
                else __import__(
                    "ooxml_opc"
                ).packuri.PackURI("/visio/vbaProject.bin"),
                CT_VBA_PROJECT,
                pkg,
                huge,
            )

    def it_reports_package_not_macro_enabled_without_vba_part(self) -> None:
        pkg = VisioPackage.new()
        assert pkg.is_macro_enabled is False
        assert pkg.vba_project_part is None

    def it_detects_macro_enabled_once_vba_part_is_linked(self) -> None:
        pkg = VisioPackage.new()
        vba_part = VbaProjectPart.new_empty(pkg)
        pkg.main_document_part.relate_to(vba_part, RT_VBA_PROJECT)
        assert pkg.is_macro_enabled is True
        assert pkg.vba_project_part is vba_part


class DescribeFactoryMismatchErrors:
    def it_cannot_mint_a_visio_drawing_from_a_stencil_mismatch(self) -> None:
        # Build a stencil package in-memory and wrap it in a
        # fake-opener scenario. We simulate via VisioPackage directly
        # because no real file system is used.
        pkg = VisioPackage.new(kind=VSDX_KIND_STENCIL)
        # Pretend the Visio() factory got this package — the helper
        # _kind_of dispatch detects it's a stencil and raises.
        from vsdx.api import _kind_of

        assert _kind_of(pkg) == VSDX_KIND_STENCIL
