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

    # -- hyperlink base --------------------------------------------------

    @property
    def hyperlink_base(self) -> Optional[str]:
        """The document-wide relative-URL base (``<Cell N="HyperlinkBase">``).

        Visio's ``HyperlinkBase`` on the document sheet is prepended to
        any shape-level relative hyperlink :attr:`~vsdx.hyperlinks.
        Hyperlink.address` before resolution. Typical values: an
        intranet root (``\\\\fileserver\\visio\\``), a project URL
        (``https://example.com/docs/``), or a local directory.

        Returns ``None`` when the cell is absent. The setter materialises
        ``<DocumentSheet><Cell N="HyperlinkBase" V=...>`` on demand;
        assigning ``None`` or the empty string removes the cell.

        .. versionadded:: 0.3.0
        """
        sheet = self._element.documentSheet
        if sheet is None:
            return None
        for cell in sheet.cell_lst:
            if cell.get("N") == "HyperlinkBase":
                return cell.get("V")
        return None

    @hyperlink_base.setter
    def hyperlink_base(self, value: Optional[str]) -> None:
        sheet = self._element.documentSheet
        if value is None or value == "":
            # Clearing: if there's no sheet, or no HyperlinkBase cell,
            # nothing to do. Otherwise delete the cell (leave the sheet
            # in place even if empty — it carries other state Visio
            # cares about).
            if sheet is None:
                return
            for cell in sheet.cell_lst:
                if cell.get("N") == "HyperlinkBase":
                    sheet.remove(cell)
                    return
            return
        if sheet is None:
            sheet = self._element.get_or_add_documentSheet()
        # Locate-or-create the cell.
        target = None
        for cell in sheet.cell_lst:
            if cell.get("N") == "HyperlinkBase":
                target = cell
                break
        if target is None:
            target = sheet._add_cell()
            target.set("N", "HyperlinkBase")
        target.set("V", str(value))

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
