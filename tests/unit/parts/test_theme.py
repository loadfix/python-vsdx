"""Unit tests for `vsdx.parts.theme` module."""

from __future__ import annotations

import pytest
from ooxml_opc import CONTENT_TYPE as CT
from ooxml_opc import OpcPackage
from ooxml_opc.packuri import PackURI

from vsdx.parts.theme import ThemePart

_STUB_THEME = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
)


_RICH_THEME = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    b'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    b' name="Office Theme">'
    b"<a:themeElements>"
    b'<a:clrScheme name="Office">'
    b'<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
    b'<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
    b'<a:dk2><a:srgbClr val="1F497D"/></a:dk2>'
    b'<a:accent1><a:srgbClr val="4F81BD"/></a:accent1>'
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


class DescribeThemePart:
    def it_can_construct_a_new_theme_part_from_blob(self) -> None:
        package = OpcPackage()

        theme = ThemePart.new(package, _STUB_THEME)

        assert isinstance(theme, ThemePart)
        assert theme.content_type == CT.OFC_THEME
        assert theme.partname == "/visio/theme/theme1.xml"
        assert theme.blob == _STUB_THEME

    def it_mints_sequential_partnames(self) -> None:
        package = OpcPackage()

        first = ThemePart.new(package, _STUB_THEME)
        package.relate_to(first, "themeRel")
        second = ThemePart.new(package, _STUB_THEME)

        assert first.partname == "/visio/theme/theme1.xml"
        assert second.partname == "/visio/theme/theme2.xml"

    def it_can_be_loaded_by_the_shared_part_factory(self) -> None:
        # -- simulates what ``ooxml_opc``'s loader does on an open() call --
        theme = ThemePart.load(
            PackURI("/visio/theme/theme1.xml"),
            CT.OFC_THEME,
            OpcPackage(),
            _STUB_THEME,
        )

        assert isinstance(theme, ThemePart)
        assert theme.blob == _STUB_THEME


class DescribeThemePartTypedAccess:
    """Typed facade over the DrawingML theme subtree (0.1.0 adoption)."""

    def it_exposes_the_parsed_theme_element(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        element = part.theme_element

        # -- root is the <a:theme> lxml element --
        assert element.tag.endswith("}theme")
        assert element.get("name") == "Office Theme"

    def it_caches_the_parsed_tree_across_access(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        first = part.theme_element
        second = part.theme_element

        assert first is second

    def it_returns_none_name_when_theme_has_no_name(self) -> None:
        part = ThemePart.new(OpcPackage(), _STUB_THEME)

        assert part.name is None

    def it_returns_the_theme_name_when_set(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        assert part.name == "Office Theme"

    def it_can_mutate_the_theme_name(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        part.name = "Refactored"

        assert part.name == "Refactored"
        assert b"Refactored" in part.blob

    def it_can_clear_the_theme_name(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        part.name = None

        assert part.name is None

    def it_exposes_the_color_scheme_element(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        clr_scheme = part.color_scheme()

        assert clr_scheme is not None
        assert clr_scheme.tag.endswith("}clrScheme")
        assert clr_scheme.get("name") == "Office"

    def it_returns_none_color_scheme_when_absent(self) -> None:
        part = ThemePart.new(OpcPackage(), _STUB_THEME)

        assert part.color_scheme() is None

    def it_exposes_the_font_scheme_element(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        font_scheme = part.font_scheme()

        assert font_scheme is not None
        assert font_scheme.tag.endswith("}fontScheme")
        assert font_scheme.get("name") == "Office"

    def it_returns_none_font_scheme_when_absent(self) -> None:
        part = ThemePart.new(OpcPackage(), _STUB_THEME)

        assert part.font_scheme() is None

    def it_raises_on_theme_element_access_when_blob_is_empty(self) -> None:
        part = ThemePart.new(OpcPackage(), b"")

        with pytest.raises(ValueError, match="no payload"):
            _ = part.theme_element


class DescribeThemePartBlobRoundTrip:
    """Round-trip fidelity contract for mutating vs non-mutating reads."""

    def it_round_trips_byte_identically_on_an_untouched_load(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        # No typed access - blob must be verbatim.
        assert part.blob == _RICH_THEME

    def it_re_serialises_on_demand_after_a_mutation(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)

        part.name = "Refreshed"

        blob = part.blob
        assert b"Refreshed" in blob
        assert b'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"' in blob

    def it_invalidates_the_parse_cache_when_the_blob_setter_runs(self) -> None:
        part = ThemePart.new(OpcPackage(), _RICH_THEME)
        _ = part.theme_element  # prime the cache

        part.blob = _STUB_THEME

        # The new bytes should be what we see back, parsed fresh.
        assert part.blob == _STUB_THEME
        assert part.name is None
