# pyright: reportImportCycles=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUntypedBaseClass=false
# pyright: reportMissingTypeStubs=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportMissingImports=false
# pyright: reportPrivateUsage=false
"""``<Windows>``, ``<Window>`` — viewport / window state.

Lives at ``/visio/windows.xml``. Preserves the state Visio desktop
displays when the file is reopened (active window, window sizes,
stencil docking, zoom, pan).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    XsdString,
    XsdUnsignedInt,
    ZeroOrMore,
)

__all__ = [
    "CT_Window",
    "CT_Windows",
]


class CT_Window(BaseOxmlElement):
    """A single persisted window state.

    Visio persists these so the desktop reopens to the same layout.
    ``@WindowType`` is the important one (values
    ``Drawing``/``Stencil``/``Sheet``/``Icon`` per
    :class:`ST_WindowType`).

    .. versionadded:: 0.1.0
    """

    id_ = OptionalAttribute("ID", XsdUnsignedInt)
    window_type = OptionalAttribute("WindowType", XsdString)
    window_state = OptionalAttribute("WindowState", XsdUnsignedInt)
    window_left = OptionalAttribute("WindowLeft", XsdString)
    window_top = OptionalAttribute("WindowTop", XsdString)
    window_width = OptionalAttribute("WindowWidth", XsdString)
    window_height = OptionalAttribute("WindowHeight", XsdString)
    container_type = OptionalAttribute("ContainerType", XsdString)
    page = OptionalAttribute("Page", XsdUnsignedInt)
    parent_window = OptionalAttribute("ParentWindow", XsdUnsignedInt)
    stencil_group = OptionalAttribute("StencilGroup", XsdString)
    stencil_group_pos = OptionalAttribute("StencilGroupPos", XsdUnsignedInt)
    view_scale = OptionalAttribute("ViewScale", XsdString)
    view_center_x = OptionalAttribute("ViewCenterX", XsdString)
    view_center_y = OptionalAttribute("ViewCenterY", XsdString)
    show_rulers = OptionalAttribute("ShowRulers", XsdString)
    show_grid = OptionalAttribute("ShowGrid", XsdString)
    show_page_breaks = OptionalAttribute("ShowPageBreaks", XsdString)
    show_guides = OptionalAttribute("ShowGuides", XsdString)
    show_connection_points = OptionalAttribute(
        "ShowConnectionPoints", XsdString
    )
    glue_settings = OptionalAttribute("GlueSettings", XsdUnsignedInt)
    snap_settings = OptionalAttribute("SnapSettings", XsdUnsignedInt)
    snap_extensions = OptionalAttribute("SnapExtensions", XsdUnsignedInt)
    snap_angles = OptionalAttribute("SnapAngles", XsdString)
    dynamic_grid_enabled = OptionalAttribute(
        "DynamicGridEnabled", XsdString
    )
    tab_split_pos = OptionalAttribute("TabSplitterPos", XsdString)


class CT_Windows(BaseOxmlElement):
    """Root of ``/visio/windows.xml``.

    Attributes track global display state across all windows.

    .. versionadded:: 0.1.0
    """

    client_width = OptionalAttribute("ClientWidth", XsdUnsignedInt)
    client_height = OptionalAttribute("ClientHeight", XsdUnsignedInt)

    # Auto-generates ``window_lst`` getter.
    window = ZeroOrMore("vsdx:Window")
