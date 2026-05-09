"""``VisioDocument`` — the top-level proxy wrapping the document part.

Analogue of ``pptx.presentation.Presentation`` / ``docx.document.Document``.

Owns :class:`~vsdx.page.Pages` and :class:`~vsdx.master.Masters`
collections, and dispatches ``save`` through to the underlying
:class:`~vsdx.parts._stubs.VisioPackage`.
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING, Optional, Union, cast

from vsdx.data_graphics import DataGraphics
from vsdx.master import Masters
from vsdx.page import Pages
from vsdx.shared import PartElementProxy
from vsdx.theme import Theme
from vsdx.util import lazyproperty

if TYPE_CHECKING:
    from vsdx.parts._stubs import DocumentPart, VisioPackage  # TODO(vsdx/track-2)
    from vsdx.parts.document import VisioDocumentPart


class VisioDocument(PartElementProxy):
    """Represents an entire Visio document.

    Construct via :func:`vsdx.api.Visio` — do not instantiate directly.
    """

    def __init__(self, document_part: "DocumentPart", package: "VisioPackage") -> None:
        super().__init__(document_part.element, document_part)
        self._package = package

    # -- collections ----------------------------------------------------

    @lazyproperty
    def pages(self) -> Pages:
        """The :class:`~vsdx.page.Pages` collection."""
        return Pages(self._package.pages_part, self)

    @lazyproperty
    def masters(self) -> Masters:
        """The :class:`~vsdx.master.Masters` collection."""
        return Masters(self._package.masters_part, self)

    @lazyproperty
    def data_graphics(self) -> DataGraphics:
        """The :class:`~vsdx.data_graphics.DataGraphics` collection.

        Iterates every ``<Section N="DataGraphic">`` at the document
        root. Packages authored outside Visio desktop (including the
        bare package produced by :func:`vsdx.Visio()`) carry an empty
        collection until a data graphic is imported.

        Read-only in 0.2.0 — authoring lands in 0.3.0. See
        :mod:`vsdx.data_graphics`.

        .. versionadded:: 0.2.0
        """
        return DataGraphics(self)

    @property
    def theme(self) -> Optional[Theme]:
        """The :class:`~vsdx.theme.Theme` proxy, or ``None`` if the
        package has no ``/visio/theme/theme1.xml`` part.

        Visio packages authored with Microsoft Visio always carry a
        theme — authoring against an empty package created with
        :func:`vsdx.Visio()` yields ``None`` because the seed-template
        injection (track 4) is still pending. Callers can guard with
        ``theme = doc.theme`` and fall back to authoring against the
        default colour list when ``None``.

        .. versionadded:: 0.1.0
        """
        document_part = cast("VisioDocumentPart", self._package.document_part)
        theme_part = document_part.theme_part
        if theme_part is None:
            return None
        return Theme(theme_part)

    # -- convenience ----------------------------------------------------

    @property
    def package(self) -> "VisioPackage":
        return self._package

    # -- save -----------------------------------------------------------

    def save(self, target: Union[str, "IO[bytes]"]) -> None:
        """Write the document to *target* (path or file-like)."""
        self._package.save(target)


__all__ = ["VisioDocument"]
