"""Top-level :func:`Visio` factory — the public entry point.

Analogue of :func:`pptx.Presentation` / :func:`docx.Document`.
"""

from __future__ import annotations

from typing import IO, Optional, Union

from vsdx.document import VisioDocument
from vsdx.package import VisioPackage


def Visio(source: Optional[Union[str, "IO[bytes]"]] = None) -> VisioDocument:
    """Open an existing ``.vsdx`` or start a blank document.

    :param source: Path to an existing ``.vsdx`` file, a file-like
        object, or ``None`` to create a new blank document.
    :returns: A :class:`~vsdx.document.VisioDocument` proxy.

    A new document starts empty — call ``doc.pages.add_page()`` to
    add the first page before adding shapes.
    """
    if source is None:
        package = VisioPackage.new()
    else:
        package = VisioPackage.open(source)
    return VisioDocument(package.main_document_part, package)


__all__ = ["Visio"]
