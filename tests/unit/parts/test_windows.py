"""Unit tests for `vsdx.parts.windows` module."""

from __future__ import annotations

from vsdx.constants import CT_VSDX_WINDOWS, NS_VSDX_CORE
from vsdx.parts.windows import WindowsPart


class DescribeWindowsPart:
    def it_can_construct_a_default_windows_part(self) -> None:
        windows = WindowsPart.new(None)  # type: ignore[arg-type]

        assert isinstance(windows, WindowsPart)
        assert windows.content_type == CT_VSDX_WINDOWS
        assert windows.partname == "/visio/windows.xml"
        assert windows.element.tag == f"{{{NS_VSDX_CORE}}}Windows"
