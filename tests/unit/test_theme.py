"""Unit tests for the :class:`vsdx.theme.Theme` proxy."""

from __future__ import annotations

import pytest
from ooxml_opc import OpcPackage
from ooxml_opc import RELATIONSHIP_TYPE as RT

import vsdx
from vsdx.parts.theme import ThemePart
from vsdx.theme import (
    ColorScheme,
    EffectVariant,
    FontScheme,
    FontVariation,
    ShadowParams,
    Theme,
)

_THEME_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    b' name="Office Theme">'
    b"<a:themeElements>"
    b'<a:clrScheme name="Office">'
    b'<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
    b'<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
    b'<a:dk2><a:srgbClr val="1F497D"/></a:dk2>'
    b'<a:lt2><a:srgbClr val="EEECE1"/></a:lt2>'
    b'<a:accent1><a:srgbClr val="4F81BD"/></a:accent1>'
    b'<a:accent2><a:srgbClr val="C0504D"/></a:accent2>'
    b'<a:accent3><a:srgbClr val="9BBB59"/></a:accent3>'
    b'<a:accent4><a:srgbClr val="8064A2"/></a:accent4>'
    b'<a:accent5><a:srgbClr val="4BACC6"/></a:accent5>'
    b'<a:accent6><a:srgbClr val="F79646"/></a:accent6>'
    b'<a:hlink><a:srgbClr val="0000FF"/></a:hlink>'
    b'<a:folHlink><a:srgbClr val="800080"/></a:folHlink>'
    b"</a:clrScheme>"
    b'<a:fontScheme name="Office">'
    b'<a:majorFont><a:latin typeface="Calibri Light"/></a:majorFont>'
    b'<a:minorFont><a:latin typeface="Calibri"/></a:minorFont>'
    b"</a:fontScheme>"
    b"</a:themeElements>"
    b"</a:theme>"
)


_BARE_THEME_XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
)


def _theme_from(xml: bytes) -> Theme:
    return Theme(ThemePart.new(OpcPackage(), xml))


class DescribeThemeIdentity:
    def it_exposes_its_underlying_part(self) -> None:
        part = ThemePart.new(OpcPackage(), _THEME_XML)

        proxy = Theme(part)

        assert proxy.part is part

    def it_exposes_the_theme_name(self) -> None:
        proxy = _theme_from(_THEME_XML)

        assert proxy.name == "Office Theme"

    def it_returns_none_for_unset_name(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.name is None

    def it_can_mutate_the_theme_name(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.name = "Renamed"

        assert proxy.name == "Renamed"


class DescribeThemeColorScheme:
    def it_exposes_the_scheme_name(self) -> None:
        proxy = _theme_from(_THEME_XML)

        assert proxy.color_scheme_name == "Office"

    def it_returns_none_scheme_name_for_a_bare_theme(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.color_scheme_name is None

    @pytest.mark.parametrize(
        ("slot", "expected"),
        [
            ("dk2", "1F497D"),
            ("lt2", "EEECE1"),
            ("accent1", "4F81BD"),
            ("accent6", "F79646"),
            ("hlink", "0000FF"),
            ("folHlink", "800080"),
        ],
    )
    def it_returns_srgb_slot_values(self, slot: str, expected: str) -> None:
        proxy = _theme_from(_THEME_XML)

        assert proxy.color(slot) == expected

    def it_returns_none_when_slot_wraps_a_sysClr(self) -> None:
        # -- dk1 is a sysClr in the Office theme; the proxy exposes only
        # -- srgbClr slots through the simple .color() accessor. --
        proxy = _theme_from(_THEME_XML)

        assert proxy.color("dk1") is None

    def it_rejects_unknown_slot_names(self) -> None:
        proxy = _theme_from(_THEME_XML)

        with pytest.raises(ValueError, match="unknown colour-scheme slot"):
            proxy.color("bogus")

    def it_exposes_the_raw_slot_element_for_escape_hatching(self) -> None:
        proxy = _theme_from(_THEME_XML)

        slot = proxy.color_slot("dk1")

        assert slot is not None
        # sysClr wrapper child present
        sysclr = slot.find(
            "{http://schemas.openxmlformats.org/drawingml/2006/main}sysClr"
        )
        assert sysclr is not None
        assert sysclr.get("val") == "windowText"

    def it_returns_none_for_color_when_scheme_absent(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.color("accent1") is None

    def it_can_set_a_slot_color(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.set_color("accent1", "#ff0000")

        assert proxy.color("accent1") == "FF0000"

    def it_normalises_hex_case_and_strips_hash_on_set(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.set_color("accent2", "aabbcc")

        assert proxy.color("accent2") == "AABBCC"

    def it_replaces_sysClr_with_srgbClr_on_set(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.set_color("dk1", "112233")

        assert proxy.color("dk1") == "112233"

    def it_rejects_invalid_rgb_values(self) -> None:
        proxy = _theme_from(_THEME_XML)

        with pytest.raises(ValueError, match="6 hex digits"):
            proxy.set_color("accent1", "not-hex")

    def it_rejects_wrong_length_rgb_values(self) -> None:
        proxy = _theme_from(_THEME_XML)

        with pytest.raises(ValueError, match="6 hex digits"):
            proxy.set_color("accent1", "FFF")

    def it_raises_setting_a_color_when_the_scheme_is_absent(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        with pytest.raises(ValueError, match="no <a:clrScheme>"):
            proxy.set_color("accent1", "000000")


class DescribeThemeFontScheme:
    def it_exposes_the_font_scheme_name(self) -> None:
        proxy = _theme_from(_THEME_XML)

        assert proxy.font_scheme_name == "Office"

    def it_returns_none_font_scheme_name_for_a_bare_theme(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.font_scheme_name is None

    def it_exposes_the_major_latin_typeface(self) -> None:
        proxy = _theme_from(_THEME_XML)

        assert proxy.major_latin_typeface == "Calibri Light"

    def it_exposes_the_minor_latin_typeface(self) -> None:
        proxy = _theme_from(_THEME_XML)

        assert proxy.minor_latin_typeface == "Calibri"

    def it_returns_none_typefaces_when_font_scheme_absent(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.major_latin_typeface is None
        assert proxy.minor_latin_typeface is None

    def it_can_set_the_major_latin_typeface(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.set_major_latin_typeface("Helvetica Neue")

        assert proxy.major_latin_typeface == "Helvetica Neue"

    def it_can_set_the_minor_latin_typeface(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.set_minor_latin_typeface("Inter")

        assert proxy.minor_latin_typeface == "Inter"

    def it_rejects_an_empty_typeface(self) -> None:
        proxy = _theme_from(_THEME_XML)

        with pytest.raises(ValueError, match="non-empty"):
            proxy.set_major_latin_typeface("")

    def it_raises_setting_typeface_when_font_scheme_absent(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        with pytest.raises(ValueError, match="no <a:fontScheme>"):
            proxy.set_major_latin_typeface("Inter")


class DescribeThemeRoundTrip:
    def it_propagates_mutations_into_the_part_blob(self) -> None:
        proxy = _theme_from(_THEME_XML)

        proxy.set_color("accent1", "ff0000")
        proxy.set_major_latin_typeface("Helvetica Neue")
        proxy.name = "Brand"

        blob = proxy.part.blob
        assert b"FF0000" in blob
        assert b"Helvetica Neue" in blob
        assert b"Brand" in blob
        # DrawingML namespace preserved on round-trip.
        assert b"http://schemas.openxmlformats.org/drawingml/2006/main" in blob


class DescribeColorSchemeProxy:
    def it_is_returned_from_theme_color_scheme(self) -> None:
        proxy = _theme_from(_THEME_XML)
        scheme = proxy.color_scheme
        assert isinstance(scheme, ColorScheme)
        assert scheme.name == "Office"

    def it_returns_none_when_the_theme_has_no_scheme(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)
        assert proxy.color_scheme is None

    @pytest.mark.parametrize(
        ("slot", "expected"),
        [
            ("dk2", "1F497D"),
            ("lt2", "EEECE1"),
            ("accent1", "4F81BD"),
            ("accent2", "C0504D"),
            ("accent3", "9BBB59"),
            ("accent4", "8064A2"),
            ("accent5", "4BACC6"),
            ("accent6", "F79646"),
            ("hlink", "0000FF"),
            ("folHlink", "800080"),
        ],
    )
    def it_exposes_srgb_slots_as_dotted_attributes(
        self, slot: str, expected: str
    ) -> None:
        scheme = _theme_from(_THEME_XML).color_scheme
        assert scheme is not None
        assert getattr(scheme, slot) == expected

    def it_returns_the_sysClr_val_for_system_colour_slots(self) -> None:
        scheme = _theme_from(_THEME_XML).color_scheme
        assert scheme is not None
        # The Office theme's dk1 / lt1 slots wrap a:sysClr — the proxy
        # surfaces the sysClr @val (e.g. "windowText") rather than
        # collapsing to None (that's the documented contract).
        assert scheme.dk1 == "windowText"
        assert scheme.lt1 == "window"

    def it_round_trips_a_colour_slot_via_set_color(self) -> None:
        theme = _theme_from(_THEME_XML)
        theme.set_color("accent1", "ff00aa")

        scheme = theme.color_scheme
        assert scheme is not None
        assert scheme.accent1 == "FF00AA"


class DescribeFontSchemeProxy:
    def it_is_returned_from_theme_font_scheme(self) -> None:
        proxy = _theme_from(_THEME_XML)
        fs = proxy.font_scheme
        assert isinstance(fs, FontScheme)
        assert fs.name == "Office"

    def it_returns_none_when_the_theme_has_no_font_scheme(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)
        assert proxy.font_scheme is None

    def it_exposes_major_and_minor_font_latin_typefaces(self) -> None:
        fs = _theme_from(_THEME_XML).font_scheme
        assert fs is not None
        major = fs.major_font
        minor = fs.minor_font
        assert major is not None
        assert minor is not None
        assert major.latin_typeface == "Calibri Light"
        assert minor.latin_typeface == "Calibri"


# -- per-page theme override + document.themes ----------------------


def _attach_doc_theme(doc: "vsdx.VisioDocument", xml: bytes) -> ThemePart:
    """Create a ThemePart inside *doc*'s package and rel it to the document."""
    part = ThemePart.new(doc.package, xml)
    doc.package.document_part.relate_to(part, RT.THEME)
    return part


class DescribeVisioDocumentThemes:
    def it_returns_an_empty_list_for_a_fresh_package(self) -> None:
        doc = vsdx.Visio()
        assert doc.themes == []

    def it_lists_every_theme_part_in_the_package(self) -> None:
        doc = vsdx.Visio()
        _attach_doc_theme(doc, _THEME_XML)
        # Second (unrelated) theme part — simulating a per-page override.
        extra = ThemePart.new(doc.package, _BARE_THEME_XML)
        page = doc.pages.add_page(name="Page-1")
        page.part.relate_to(extra, RT.THEME)

        themes = doc.themes
        assert len(themes) == 2
        assert all(isinstance(t, Theme) for t in themes)
        # The original theme is the document-scoped default.
        assert doc.theme is not None
        assert doc.theme.part is themes[0].part or doc.theme.part is themes[1].part


class DescribePageThemeOverride:
    def it_falls_back_to_the_document_theme_when_no_override(self) -> None:
        doc = vsdx.Visio()
        _attach_doc_theme(doc, _THEME_XML)

        page = doc.pages.add_page(name="Page-1")

        assert page.theme is not None
        assert page.theme.name == "Office Theme"
        # Same underlying part as the document-wide theme.
        assert page.theme.part is doc.theme.part

    def it_returns_none_when_the_package_has_no_theme(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        assert page.theme is None

    def it_reads_an_override_bound_to_the_page_part(self) -> None:
        doc = vsdx.Visio()
        _attach_doc_theme(doc, _THEME_XML)
        override_part = ThemePart.new(doc.package, _BARE_THEME_XML)

        page = doc.pages.add_page(name="Page-1")
        page.part.relate_to(override_part, RT.THEME)

        assert page.theme is not None
        assert page.theme.part is override_part
        # Different part than the document-wide theme.
        assert page.theme.part is not doc.theme.part

    def it_can_set_a_per_page_theme_override(self) -> None:
        doc = vsdx.Visio()
        _attach_doc_theme(doc, _THEME_XML)
        page = doc.pages.add_page(name="Page-1")
        override = Theme(ThemePart.new(doc.package, _BARE_THEME_XML))

        page.theme = override

        # The page part now carries exactly one RT.THEME rel — to override.
        theme_rels = [
            r for r in page.part.rels.values()
            if not r.is_external and r.reltype == RT.THEME
        ]
        assert len(theme_rels) == 1
        assert theme_rels[0].target_part is override.part
        assert page.theme is not None
        assert page.theme.part is override.part

    def it_replaces_any_existing_override_on_set(self) -> None:
        doc = vsdx.Visio()
        _attach_doc_theme(doc, _THEME_XML)
        page = doc.pages.add_page(name="Page-1")
        first = Theme(ThemePart.new(doc.package, _BARE_THEME_XML))
        second = Theme(ThemePart.new(doc.package, _BARE_THEME_XML))

        page.theme = first
        page.theme = second

        theme_rels = [
            r for r in page.part.rels.values()
            if not r.is_external and r.reltype == RT.THEME
        ]
        assert len(theme_rels) == 1
        assert theme_rels[0].target_part is second.part

    def it_removes_the_override_when_set_to_none(self) -> None:
        doc = vsdx.Visio()
        _attach_doc_theme(doc, _THEME_XML)
        page = doc.pages.add_page(name="Page-1")
        override = Theme(ThemePart.new(doc.package, _BARE_THEME_XML))
        page.theme = override

        page.theme = None

        theme_rels = [
            r for r in page.part.rels.values()
            if not r.is_external and r.reltype == RT.THEME
        ]
        assert theme_rels == []
        # The page falls back to the document theme.
        assert page.theme is not None
        assert page.theme.part is doc.theme.part

    def it_rejects_non_theme_non_none_assignments(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        with pytest.raises(TypeError, match="Theme or None"):
            page.theme = "nope"  # type: ignore[assignment]


# -- effect variants + font variations ----------------------------------


_THEME_WITH_EFFECTS = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    b' name="Effects">'
    b"<a:themeElements>"
    b'<a:clrScheme name="Effects"/>'
    b"<a:fontScheme/>"
    b'<a:fmtScheme name="Effects">'
    b"<a:fillStyleLst/>"
    b"<a:lnStyleLst/>"
    b"<a:effectStyleLst>"
    b"<a:effectStyle><a:effectLst/></a:effectStyle>"
    b"<a:effectStyle><a:effectLst>"
    b'<a:outerShdw blurRad="50800" dist="38100" dir="5400000"'
    b' algn="t" rotWithShape="0">'
    b'<a:srgbClr val="000000"><a:alpha val="40000"/></a:srgbClr>'
    b"</a:outerShdw>"
    b"</a:effectLst></a:effectStyle>"
    b"<a:effectStyle><a:effectLst>"
    b'<a:innerShdw blurRad="63500" dist="25400" dir="2700000">'
    b'<a:srgbClr val="ff00aa"/>'
    b"</a:innerShdw>"
    b"</a:effectLst></a:effectStyle>"
    # A 4th + 5th entry that must be ignored — only the first 3 are
    # exposed as canonical DrawingML variants.
    b"<a:effectStyle><a:effectLst/></a:effectStyle>"
    b"<a:effectStyle><a:effectLst/></a:effectStyle>"
    b"</a:effectStyleLst>"
    b"<a:bgFillStyleLst/>"
    b"</a:fmtScheme>"
    b"</a:themeElements>"
    b"</a:theme>"
)


_THEME_WITH_FONT_VARIATIONS = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    b"<a:themeElements>"
    b"<a:fontVariations>"
    b'<a:fontVariation name="primary">'
    b'<a:majorFont><a:latin typeface="Inter"/></a:majorFont>'
    b'<a:minorFont><a:latin typeface="Inter Tight"/></a:minorFont>'
    b"</a:fontVariation>"
    b"<a:fontVariation>"
    b'<a:majorFont><a:latin typeface="Roboto"/></a:majorFont>'
    b"</a:fontVariation>"
    b"</a:fontVariations>"
    b"</a:themeElements>"
    b"</a:theme>"
)


class DescribeThemeEffectVariants:
    def it_returns_an_empty_list_for_a_bare_theme(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.effect_variants == []

    def it_returns_an_empty_list_when_fmt_scheme_has_no_effect_list(
        self,
    ) -> None:
        xml = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b"<a:theme"
            b' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            b"<a:themeElements>"
            b'<a:fmtScheme name="x">'
            b"<a:fillStyleLst/>"
            b"<a:lnStyleLst/>"
            b"<a:bgFillStyleLst/>"
            b"</a:fmtScheme>"
            b"</a:themeElements>"
            b"</a:theme>"
        )
        proxy = _theme_from(xml)

        assert proxy.effect_variants == []

    def it_exposes_three_named_variants(self) -> None:
        proxy = _theme_from(_THEME_WITH_EFFECTS)

        variants = proxy.effect_variants

        assert len(variants) == 3
        assert all(isinstance(v, EffectVariant) for v in variants)
        assert [v.name for v in variants] == ["subtle", "moderate", "intense"]
        assert [v.preset_num for v in variants] == [1, 2, 3]

    def it_caps_at_the_canonical_three_when_theme_ships_more(self) -> None:
        # The fixture ships five effect styles; the proxy truncates.
        proxy = _theme_from(_THEME_WITH_EFFECTS)

        assert len(proxy.effect_variants) == 3

    def it_exposes_typed_outer_shadow_params(self) -> None:
        variants = _theme_from(_THEME_WITH_EFFECTS).effect_variants

        moderate = variants[1]
        shadow = moderate.shadow_outer_params

        assert isinstance(shadow, ShadowParams)
        assert shadow.blur_rad == 50800
        assert shadow.dist == 38100
        assert shadow.direction == 5400000
        assert shadow.color == "000000"

    def it_exposes_typed_inner_shadow_params(self) -> None:
        variants = _theme_from(_THEME_WITH_EFFECTS).effect_variants

        intense = variants[2]
        shadow = intense.shadow_inner_params

        assert isinstance(shadow, ShadowParams)
        assert shadow.blur_rad == 63500
        assert shadow.dist == 25400
        assert shadow.direction == 2700000
        # Colour is normalised to uppercase.
        assert shadow.color == "FF00AA"

    def it_returns_none_shadow_params_for_variants_without_shadows(
        self,
    ) -> None:
        variants = _theme_from(_THEME_WITH_EFFECTS).effect_variants

        subtle = variants[0]

        assert subtle.shadow_outer_params is None
        assert subtle.shadow_inner_params is None

    def it_returns_none_for_the_outer_shadow_of_an_inner_shadow_variant(
        self,
    ) -> None:
        variants = _theme_from(_THEME_WITH_EFFECTS).effect_variants

        intense = variants[2]

        assert intense.shadow_outer_params is None


class DescribeThemeFontVariations:
    def it_returns_an_empty_list_for_a_bare_theme(self) -> None:
        proxy = _theme_from(_BARE_THEME_XML)

        assert proxy.font_variations == []

    def it_returns_an_empty_list_when_default_visio_theme(self) -> None:
        # The stock Office theme uses a vt:fontStylesGroup ext element
        # rather than a:fontVariations — so the proxy must report [].
        proxy = _theme_from(_THEME_XML)

        assert proxy.font_variations == []

    def it_parses_font_variation_entries(self) -> None:
        proxy = _theme_from(_THEME_WITH_FONT_VARIATIONS)

        variations = proxy.font_variations

        assert len(variations) == 2
        assert all(isinstance(v, FontVariation) for v in variations)
        assert variations[0] == FontVariation(
            name="primary",
            major_latin_typeface="Inter",
            minor_latin_typeface="Inter Tight",
        )
        assert variations[1] == FontVariation(
            name=None,
            major_latin_typeface="Roboto",
            minor_latin_typeface=None,
        )


class DescribeThemeEffectsRoundTrip:
    def it_survives_a_serialisation_round_trip(self) -> None:
        proxy = _theme_from(_THEME_WITH_EFFECTS)

        # Trigger blob regeneration via any name-preserving mutation.
        proxy.name = "Effects"
        blob = proxy.part.blob

        reparsed = Theme(ThemePart.new(OpcPackage(), blob))
        variants = reparsed.effect_variants

        assert len(variants) == 3
        assert variants[1].shadow_outer_params == ShadowParams(
            blur_rad=50800,
            dist=38100,
            direction=5400000,
            color="000000",
        )
        assert variants[2].shadow_inner_params is not None
        assert variants[2].shadow_inner_params.color == "FF00AA"


class DescribePageSetEffectVariant:
    def it_writes_the_quickstyleeffectmatrix_cell_on_every_shape(
        self,
    ) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        s1 = page.shapes.add_shape("Rectangle", at=(1, 1), size=(2, 1))
        s2 = page.shapes.add_shape("Ellipse", at=(4, 1), size=(2, 1))

        page.set_effect_variant(1)

        for shape in (s1, s2):
            cell = shape._get_cell("QuickStyleEffectMatrix")
            assert cell is not None
            # index 1 → preset 2 (moderate)
            assert cell.get("V") == "2"

    def it_updates_existing_quickstyleeffectmatrix_cells_in_place(
        self,
    ) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        shape = page.shapes.add_shape("Rectangle", at=(1, 1), size=(2, 1))

        page.set_effect_variant(2)
        page.set_effect_variant(0)

        cell = shape._get_cell("QuickStyleEffectMatrix")
        assert cell is not None
        # Only one such cell (the setter updates in place).
        matching = [
            c for c in shape._element.cell_lst
            if c.get("N") == "QuickStyleEffectMatrix"
        ]
        assert len(matching) == 1
        assert cell.get("V") == "1"

    def it_accepts_preset_indexes_0_1_and_2(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")
        shape = page.shapes.add_shape("Rectangle", at=(1, 1), size=(2, 1))

        for index, expected in ((0, "1"), (1, "2"), (2, "3")):
            page.set_effect_variant(index)
            cell = shape._get_cell("QuickStyleEffectMatrix")
            assert cell is not None
            assert cell.get("V") == expected

    def it_is_a_no_op_on_a_page_with_no_shapes(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")

        # Must not raise.
        page.set_effect_variant(0)

    def it_rejects_non_int_index(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")

        with pytest.raises(TypeError, match="must be an int"):
            page.set_effect_variant("0")  # type: ignore[arg-type]

    def it_rejects_bool_index(self) -> None:
        # Python treats bool as int; reject it explicitly to avoid the
        # silent True → 1 coercion from the caller's perspective.
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")

        with pytest.raises(TypeError, match="must be an int"):
            page.set_effect_variant(True)  # type: ignore[arg-type]

    @pytest.mark.parametrize("index", [-1, 3, 99])
    def it_rejects_out_of_range_indexes(self, index: int) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="Page-1")

        with pytest.raises(ValueError, match="out of range"):
            page.set_effect_variant(index)
