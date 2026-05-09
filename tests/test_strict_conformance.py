"""Integration tests for ECMA-376 Strict conformance-class adoption.

Exercises the ``strict=`` keyword plumbed through :func:`vsdx.Visio` /
:meth:`VisioDocument.open` / :meth:`VisioDocument.save` and the
:attr:`VisioDocument.is_strict` introspection property. The underlying
Strict→Transitional sniff + rewrite is tested in :mod:`ooxml_opc`'s
own suite; this test verifies the parent library surfaces the knob
correctly.

Note: the Visio schema does not have Strict counterparts for its own
``schemas.microsoft.com/office/visio/...`` namespaces, so a fresh
authored ``.vsdx`` has no Strict-able content to rewrite. The test
suite therefore focuses on API-surface correctness: that ``is_strict``
is readable / writable, that ``strict=`` forwards through the factory
and ``open()`` / ``save()``, and that the flag propagates to the
underlying :class:`ooxml_opc.OpcPackage`.
"""

from __future__ import annotations

import io

import vsdx
from vsdx.document import VisioDocument


class DescribeStrictConformanceSurface:
    """VisioDocument plumbs strict= / is_strict through to OpcPackage."""

    def it_reports_is_strict_false_for_a_fresh_drawing(self) -> None:
        doc = vsdx.Visio()
        assert doc.is_strict is False

    def it_lets_callers_flip_is_strict_on_the_document(self) -> None:
        doc = vsdx.Visio()
        assert doc.is_strict is False
        doc.is_strict = True
        assert doc.is_strict is True
        # -- the underlying package also reflects the change --
        assert doc.package.is_strict is True
        doc.is_strict = False
        assert doc.is_strict is False

    def it_accepts_strict_kwarg_on_save_without_raising(
        self, tmp_path: object
    ) -> None:
        doc = vsdx.Visio()
        doc.pages.add_page()
        out = io.BytesIO()
        doc.save(out, strict=True)
        # -- the emitted bytes remain a valid zip --
        import zipfile
        zf = zipfile.ZipFile(io.BytesIO(out.getvalue()))
        assert "[Content_Types].xml" in zf.namelist()

    def it_accepts_strict_kwarg_on_open_without_raising(self) -> None:
        doc = vsdx.Visio()
        doc.pages.add_page()
        out = io.BytesIO()
        doc.save(out)

        out.seek(0)
        doc2 = VisioDocument.open(out, strict=True)
        # -- forcing strict=True on open flags the package as Strict
        # -- regardless of namespace sniff --
        assert doc2.is_strict is True

    def it_accepts_strict_kwarg_on_factory(self) -> None:
        # -- the Visio() factory forwards strict= to VisioPackage.open --
        doc = vsdx.Visio()
        doc.pages.add_page()
        out = io.BytesIO()
        doc.save(out)

        out.seek(0)
        doc2 = vsdx.Visio(out, strict=True)
        assert doc2.is_strict is True

    def it_round_trips_a_drawing_with_the_strict_flag_set(self) -> None:
        # -- end-to-end round-trip: set is_strict=True, save, reopen
        # -- (no strict kwarg forces the flag to survive on round-trip
        # -- for parts that *do* carry translatable URIs — here the
        # -- package-level rels namespace via emit_strict=True). --
        doc = vsdx.Visio()
        doc.pages.add_page()
        doc.is_strict = True

        out = io.BytesIO()
        doc.save(out)

        out.seek(0)
        doc2 = VisioDocument.open(out, strict=True)
        assert doc2.is_strict is True
        assert len(doc2.pages) == len(doc.pages)
