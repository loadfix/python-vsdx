"""Visio windows part — viewport state for the drawing window(s).

Corresponds to ``/visio/windows.xml``. Root element is ``<Windows>``
containing zero-or-more ``<Window>`` entries that record the editor
window state Visio desktop restores on open (window type, container
type, size / position, zoom level, active page).

The part is referenced from :class:`~vsdx.parts.document.VisioDocumentPart`
via the ``RT_VISIO_WINDOWS`` relationship. It's technically optional —
Visio will synthesize a default on open if absent — but real
``.office.vsdx`` fixtures always carry one, so python-vsdx emits one
too for byte-fidelity round-trips.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc import XmlPart, parse_xml
from ooxml_opc.packuri import PackURI

from vsdx.constants import CT_VSDX_WINDOWS
from vsdx.parts._templates import DEFAULT_WINDOWS_XML

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


class WindowsPart(XmlPart):
    """The ``/visio/windows.xml`` part.

    Singleton within a package. Content-type
    ``application/vnd.ms-visio.windows+xml``.
    """

    @classmethod
    def new(cls, package: OpcPackage) -> WindowsPart:
        """Return a new, empty windows part.

        Carries a bare ``<Windows/>`` root. Track 3's proxy layer is
        expected to populate at least one ``<Window>`` child before
        save so Visio desktop restores a reasonable default viewport.
        """
        element = parse_xml(DEFAULT_WINDOWS_XML)
        return cls(
            PackURI("/visio/windows.xml"),
            CT_VSDX_WINDOWS,
            package,
            element,
        )
