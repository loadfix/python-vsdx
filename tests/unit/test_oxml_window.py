"""Unit tests for CT_Windows and CT_Window."""

from __future__ import annotations

from vsdx.oxml import nsdecls, parse_xml
from vsdx.oxml.window import CT_Window, CT_Windows


class Describe_CT_Window:
    def it_round_trips_a_drawing_window(self) -> None:
        xml = (
            '<vsdx:Window %s ID="1" WindowType="Drawing" WindowState="67109377"'
            ' WindowLeft="0" WindowTop="0" WindowWidth="1024" WindowHeight="768"'
            ' ContainerType="Drawing" Page="0" ViewScale="-1"'
            ' ViewCenterX="4.25" ViewCenterY="5.5"/>' % nsdecls("vsdx")
        ).encode()
        win = parse_xml(xml)
        assert isinstance(win, CT_Window)
        assert win.id_ == 1
        assert win.window_type == "Drawing"
        assert win.window_state == 67109377
        assert win.page == 0
        assert win.view_scale == "-1"
        assert win.container_type == "Drawing"


class Describe_CT_Windows:
    def it_round_trips_global_dimensions_and_windows(self) -> None:
        xml = (
            '<vsdx:Windows %s ClientWidth="1024" ClientHeight="768">'
            '<vsdx:Window ID="1" WindowType="Drawing" Page="0"/>'
            '<vsdx:Window ID="2" WindowType="Stencil"/>'
            "</vsdx:Windows>" % nsdecls("vsdx")
        ).encode()
        windows = parse_xml(xml)
        assert isinstance(windows, CT_Windows)
        assert windows.client_width == 1024
        assert windows.client_height == 768
        lst = windows.window_lst
        assert len(lst) == 2
        assert lst[0].window_type == "Drawing"
        assert lst[1].window_type == "Stencil"
