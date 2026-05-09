"""``VisioDocument`` — the top-level proxy wrapping the document part.

Analogue of ``pptx.presentation.Presentation`` / ``docx.document.Document``.

Owns :class:`~vsdx.page.Pages` and :class:`~vsdx.master.Masters`
collections, and dispatches ``save`` through to the underlying
:class:`~vsdx.parts._stubs.VisioPackage`.
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING, Union

from vsdx.master import Masters
from vsdx.page import Pages
from vsdx.shared import PartElementProxy
from vsdx.util import lazyproperty

if TYPE_CHECKING:
    from vsdx.parts._stubs import DocumentPart, VisioPackage  # TODO(vsdx/track-2)


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

    # -- convenience ----------------------------------------------------

    @property
    def package(self) -> "VisioPackage":
        return self._package

    # -- save -----------------------------------------------------------

    def save(self, target: Union[str, "IO[bytes]"]) -> None:
        """Write the document to *target* (path or file-like)."""
        self._package.save(target)


__all__ = ["VisioDocument"]
