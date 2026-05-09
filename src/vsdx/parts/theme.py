"""Visio theme part — a DrawingML theme inside a ``.vsdx`` package.

Corresponds to ``/visio/theme/theme%d.xml``. The theme is a straight
ECMA-376 Part 1 DrawingML theme
(``application/vnd.openxmlformats-officedocument.theme+xml``), not a
Visio-specific schema — Visio embeds the exact same ``<a:theme>``
document docx / pptx / xlsx use. In 0.1.0 the part is a pass-through
(it holds the XML blob verbatim from the input package or the seed
template); native parsing into ``CT_OfficeStyleSheet`` is deferred to
a later track when the shared ``python-ooxml-theme`` package lands.

Relationship: :class:`~vsdx.parts.document.VisioDocumentPart` →
``RT.THEME`` → :class:`ThemePart`.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ooxml_opc import CONTENT_TYPE as CT
from ooxml_opc import Part

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage
    from ooxml_opc.packuri import PackURI


class ThemePart(Part):
    """The ``/visio/theme/theme%d.xml`` DrawingML theme part.

    Inherits :class:`~ooxml_opc.part.Part` (not :class:`XmlPart`) in
    0.1.0 so we can hand the blob through verbatim — native
    ``CT_OfficeStyleSheet`` hydration will be added when the shared
    theme package is adopted. Content-type is the shared
    ``CT.OFC_THEME`` string
    (``application/vnd.openxmlformats-officedocument.theme+xml``).
    """

    _PARTNAME_TMPL = "/visio/theme/theme%d.xml"

    @classmethod
    def new(
        cls,
        package: OpcPackage,
        blob: bytes,
    ) -> ThemePart:
        """Return a new theme part carrying `blob` verbatim.

        `blob` must be a serialised ``<a:theme>`` document. The caller
        owns the bytes — typical 0.1.0 usage is to read them out of
        the seed-template ``default.vsdx`` shipped with
        ``vsdx.templates`` (track 4).
        """
        partname = package.next_partname(cls._PARTNAME_TMPL)
        return cls(partname, CT.OFC_THEME, package, blob)

    @classmethod
    def load(
        cls,
        partname: PackURI,
        content_type: str,
        package: OpcPackage,
        blob: bytes,
    ) -> ThemePart:
        """Return a :class:`ThemePart` parsed from an existing package.

        Overrides the base ``Part.load`` signature only to narrow the
        return type — the loading mechanics are unchanged.
        """
        return cls(partname, content_type, package, blob)
