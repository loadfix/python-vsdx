"""Unit tests for `vsdx.parts.theme` module."""

from __future__ import annotations

from ooxml_opc import CONTENT_TYPE as CT
from ooxml_opc import OpcPackage
from ooxml_opc.packuri import PackURI

from vsdx.parts.theme import ThemePart


_STUB_THEME = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'


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
