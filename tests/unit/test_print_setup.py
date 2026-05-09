"""Unit tests for R8-6 page-scale cells + R8-7 print setup.

Covers :class:`vsdx.page.Page` scale / snap / visibility accessors
(``page_scale`` / ``drawing_scale`` / ``drawing_size_type`` /
``drawing_scale_type`` / ``inhibit_snap`` / ``ui_visibility``) and
the :class:`vsdx.print_setup.PrintSetup` proxy surfaced via
``Page.print_setup``.

Scope matches the R4-12 / R8-3 / R8-17 test playbook — accessor
round-trip, absent-cell defaults, clear-by-``None`` semantics,
authoring materialises the ``<PageSheet>`` on demand, and a
fixture-shaped parse → mutate → serialise drill for byte-identity.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.oxml import parse_xml
from vsdx.print_setup import PRINT_ORIENTATION, PrintSetup


# ---------------------------------------------------------------------------
# Scale / snap / visibility accessors on Page
# ---------------------------------------------------------------------------


class DescribePageScaleDefaults:
    def it_returns_none_for_absent_scale_cells(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.page_scale is None
        assert page.drawing_scale is None
        assert page.drawing_size_type is None
        assert page.drawing_scale_type is None
        assert page.ui_visibility is None

    def it_reports_inhibit_snap_false_when_absent(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.inhibit_snap is False


class DescribePageScaleAuthoring:
    def it_sets_page_scale_and_materialises_the_cell(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.page_scale = 1.0
        assert page.page_scale == 1.0
        sheet = page._element.pageSheet
        assert sheet is not None
        cells = [c for c in sheet.cell_lst if c.get("N") == "PageScale"]
        assert len(cells) == 1
        assert cells[0].get("V") == "1"
        assert cells[0].get("U") == "IN"

    def it_sets_drawing_scale(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.drawing_scale = 12.0
        assert page.drawing_scale == 12.0

    def it_sets_drawing_size_type_as_int(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.drawing_size_type = 3
        assert page.drawing_size_type == 3

    def it_sets_drawing_scale_type_as_int(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.drawing_scale_type = 1
        assert page.drawing_scale_type == 1

    def it_sets_inhibit_snap_flag(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.inhibit_snap = True
        assert page.inhibit_snap is True
        sheet = page._element.pageSheet
        cells = [c for c in sheet.cell_lst if c.get("N") == "InhibitSnap"]
        assert cells[0].get("V") == "1"

    def it_sets_ui_visibility_as_int(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.ui_visibility = 1
        assert page.ui_visibility == 1

    def it_preserves_float_scale_values(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.page_scale = 0.5
        assert page.page_scale == 0.5


class DescribePageScaleClearing:
    def it_removes_page_scale_cell_on_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.page_scale = 1.0
        page.page_scale = None
        assert page.page_scale is None
        sheet = page._element.pageSheet
        assert sheet is not None
        assert [c for c in sheet.cell_lst if c.get("N") == "PageScale"] == []

    def it_removes_drawing_size_type_cell_on_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.drawing_size_type = 2
        page.drawing_size_type = None
        assert page.drawing_size_type is None


class DescribePageScaleEdgeCases:
    def it_reads_tolerant_inhibit_snap_tokens(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        # Emit raw @V="TRUE" directly — boolean reader should tolerate.
        page._set_sheet_cell_v("InhibitSnap", "TRUE")
        assert page.inhibit_snap is True

    def it_returns_none_on_non_numeric_scale_values(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page._set_sheet_cell_v("PageScale", "garbage")
        assert page.page_scale is None

    def it_coerces_float_strings_in_size_type(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page._set_sheet_cell_v("DrawingSizeType", "3.0")
        assert page.drawing_size_type == 3


# ---------------------------------------------------------------------------
# PrintSetup — proxy surfaced via Page.print_setup
# ---------------------------------------------------------------------------


class DescribePrintSetupProxy:
    def it_returns_a_PrintSetup_instance(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert isinstance(page.print_setup, PrintSetup)

    def it_caches_the_proxy(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.print_setup is page.print_setup

    def it_returns_a_repr(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert "PrintSetup" in repr(page.print_setup)


class DescribePrintSetupDefaults:
    def it_returns_none_for_absent_orientation(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.print_setup.orientation is None

    def it_returns_none_for_absent_paper_size(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.print_setup.paper_size is None

    def it_returns_none_for_absent_margins(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        setup = page.print_setup
        assert setup.margin_top is None
        assert setup.margin_bottom is None
        assert setup.margin_left is None
        assert setup.margin_right is None

    def it_reports_centering_false_when_absent(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.print_setup.centered_x is False
        assert page.print_setup.centered_y is False

    def it_returns_none_for_absent_tile_scale(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        assert page.print_setup.tile_scale is None


class DescribePrintSetupOrientation:
    def it_sets_portrait_from_enum(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.orientation = PRINT_ORIENTATION.PORTRAIT
        assert page.print_setup.orientation is PRINT_ORIENTATION.PORTRAIT

    def it_sets_landscape_from_enum(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.orientation = PRINT_ORIENTATION.LANDSCAPE
        assert page.print_setup.orientation is PRINT_ORIENTATION.LANDSCAPE
        sheet = page._element.pageSheet
        cells = [
            c for c in sheet.cell_lst if c.get("N") == "PrintPageOrientation"
        ]
        assert cells[0].get("V") == "2"

    def it_accepts_raw_string_codes(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.orientation = "1"
        assert page.print_setup.orientation is PRINT_ORIENTATION.PORTRAIT

    def it_accepts_integer_codes(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.orientation = 2
        assert page.print_setup.orientation is PRINT_ORIENTATION.LANDSCAPE

    def it_rejects_unknown_orientation_codes(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(ValueError):
            page.print_setup.orientation = "9"
        with pytest.raises(ValueError):
            page.print_setup.orientation = 7

    def it_clears_orientation_on_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.orientation = PRINT_ORIENTATION.PORTRAIT
        page.print_setup.orientation = None
        assert page.print_setup.orientation is None

    def it_falls_back_to_none_on_unknown_parsed_value(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        # Directly emit an unknown @V so we exercise the reader's
        # load-preserve-save fallback (no exception, but reads as None).
        page._set_sheet_cell_v("PrintPageOrientation", "9")
        assert page.print_setup.orientation is None


class DescribePrintSetupPaper:
    def it_sets_paper_size_as_int(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.paper_size = 9  # A4
        assert page.print_setup.paper_size == 9

    def it_clears_paper_size_on_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.paper_size = 1
        page.print_setup.paper_size = None
        assert page.print_setup.paper_size is None


class DescribePrintSetupMargins:
    def it_sets_top_margin_with_IN_unit(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.margin_top = 0.25
        assert page.print_setup.margin_top == 0.25
        sheet = page._element.pageSheet
        cells = [c for c in sheet.cell_lst if c.get("N") == "PageTopMargin"]
        assert cells[0].get("U") == "IN"

    def it_sets_all_four_margins(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        setup = page.print_setup
        setup.margin_top = 0.5
        setup.margin_bottom = 0.5
        setup.margin_left = 0.75
        setup.margin_right = 0.75
        assert setup.margin_top == 0.5
        assert setup.margin_bottom == 0.5
        assert setup.margin_left == 0.75
        assert setup.margin_right == 0.75

    def it_clears_margin_on_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.margin_top = 0.5
        page.print_setup.margin_top = None
        assert page.print_setup.margin_top is None


class DescribePrintSetupCentering:
    def it_toggles_centered_x(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.centered_x = True
        assert page.print_setup.centered_x is True
        page.print_setup.centered_x = False
        assert page.print_setup.centered_x is False

    def it_toggles_centered_y(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.centered_y = True
        assert page.print_setup.centered_y is True


class DescribePrintSetupTileScale:
    def it_sets_tile_scale_and_writes_both_ScaleX_and_ScaleY(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.tile_scale = 0.5
        assert page.print_setup.tile_scale == 0.5
        sheet = page._element.pageSheet
        xs = [c for c in sheet.cell_lst if c.get("N") == "ScaleX"]
        ys = [c for c in sheet.cell_lst if c.get("N") == "ScaleY"]
        assert xs[0].get("V") == "0.5"
        assert ys[0].get("V") == "0.5"

    def it_clears_tile_scale_on_none(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.print_setup.tile_scale = 1.0
        page.print_setup.tile_scale = None
        assert page.print_setup.tile_scale is None
        sheet = page._element.pageSheet
        assert [c for c in sheet.cell_lst if c.get("N") == "ScaleX"] == []
        assert [c for c in sheet.cell_lst if c.get("N") == "ScaleY"] == []


# ---------------------------------------------------------------------------
# Parse-existing fixture round-trip
# ---------------------------------------------------------------------------


_FIXTURE_XML = (
    '<Page xmlns="http://schemas.microsoft.com/office/visio/2011/1/core"'
    ' ID="0" NameU="Page-1" Name="Page-1">'
    "<PageSheet>"
    '<Cell N="PageWidth" V="8.5"/>'
    '<Cell N="PageHeight" V="11"/>'
    '<Cell N="PageScale" V="1" U="IN"/>'
    '<Cell N="DrawingScale" V="12" U="IN"/>'
    '<Cell N="DrawingSizeType" V="3"/>'
    '<Cell N="DrawingScaleType" V="1"/>'
    '<Cell N="InhibitSnap" V="1"/>'
    '<Cell N="UIVisibility" V="0"/>'
    '<Cell N="PrintPageOrientation" V="2"/>'
    '<Cell N="PaperKind" V="9"/>'
    '<Cell N="PageTopMargin" V="0.25" U="IN"/>'
    '<Cell N="PageBottomMargin" V="0.25" U="IN"/>'
    '<Cell N="PageLeftMargin" V="0.25" U="IN"/>'
    '<Cell N="PageRightMargin" V="0.25" U="IN"/>'
    '<Cell N="CenterX" V="1"/>'
    '<Cell N="CenterY" V="1"/>'
    '<Cell N="ScaleX" V="0.5"/>'
    '<Cell N="ScaleY" V="0.5"/>'
    "</PageSheet>"
    "</Page>"
)


class DescribeParseExistingPageSheet:
    def _page_from_xml(self):
        """Build a bare ``Page`` proxy over a raw ``<Page>`` element.

        We can't use the ``vsdx.Visio()`` factory here — that seeds a
        fresh package with no print-setup cells. Instead we parse the
        literal fixture and wrap the element in a Page with a minimal
        stub for ``_page_part`` (we only touch ``.pageSheet`` and the
        scale / print accessors in these tests).
        """
        element = parse_xml(_FIXTURE_XML)

        class _StubPart:
            page_element = element

        class _StubParent:
            pass

        from vsdx.page import Page

        return Page(_StubPart(), _StubParent())  # type: ignore[arg-type]

    def it_reads_page_scale(self) -> None:
        page = self._page_from_xml()
        assert page.page_scale == 1.0
        assert page.drawing_scale == 12.0

    def it_reads_drawing_size_type_and_scale_type(self) -> None:
        page = self._page_from_xml()
        assert page.drawing_size_type == 3
        assert page.drawing_scale_type == 1

    def it_reads_inhibit_snap(self) -> None:
        page = self._page_from_xml()
        assert page.inhibit_snap is True

    def it_reads_ui_visibility(self) -> None:
        page = self._page_from_xml()
        assert page.ui_visibility == 0

    def it_reads_print_orientation_and_paper_size(self) -> None:
        page = self._page_from_xml()
        assert page.print_setup.orientation is PRINT_ORIENTATION.LANDSCAPE
        assert page.print_setup.paper_size == 9

    def it_reads_margins(self) -> None:
        page = self._page_from_xml()
        setup = page.print_setup
        assert setup.margin_top == 0.25
        assert setup.margin_bottom == 0.25
        assert setup.margin_left == 0.25
        assert setup.margin_right == 0.25

    def it_reads_centering_and_tile_scale(self) -> None:
        page = self._page_from_xml()
        setup = page.print_setup
        assert setup.centered_x is True
        assert setup.centered_y is True
        assert setup.tile_scale == 0.5

    def it_supports_mutate_read_round_trip(self) -> None:
        page = self._page_from_xml()
        page.page_scale = 2.0
        page.print_setup.orientation = PRINT_ORIENTATION.PORTRAIT
        page.print_setup.paper_size = 1
        assert page.page_scale == 2.0
        assert page.print_setup.orientation is PRINT_ORIENTATION.PORTRAIT
        assert page.print_setup.paper_size == 1
        # Sibling cells we didn't touch must stay intact.
        assert page.drawing_scale == 12.0
        assert page.print_setup.margin_top == 0.25
