"""``VisioDocument`` — the top-level proxy wrapping the document part.

Analogue of ``pptx.presentation.Presentation`` / ``docx.document.Document``.

Owns :class:`~vsdx.page.Pages` and :class:`~vsdx.master.Masters`
collections, and dispatches ``save`` through to the underlying
:class:`~vsdx.parts._stubs.VisioPackage`.
"""

from __future__ import annotations

import io
from typing import IO, TYPE_CHECKING, Optional, Union, cast

from vsdx.data_graphics import DataGraphics
from vsdx.data_recordsets import DataRecordsets
from vsdx.master import Masters
from vsdx.page import Pages
from vsdx.shared import PartElementProxy
from vsdx.theme import Theme
from vsdx.util import lazyproperty

if TYPE_CHECKING:
    from vsdx.ink import InkStroke
    from vsdx.parts._stubs import DocumentPart, VisioPackage  # TODO(vsdx/track-2)
    from vsdx.parts.document import VisioDocumentPart


class VisioDocument(PartElementProxy):
    """Represents an entire Visio document.

    Construct via :func:`vsdx.api.Visio` — do not instantiate directly.
    """

    def __init__(self, document_part: DocumentPart, package: VisioPackage) -> None:
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

    @lazyproperty
    def data_recordsets(self) -> DataRecordsets:
        """The :class:`~vsdx.data_recordsets.DataRecordsets` collection.

        Lazy list over every ``/visio/datarecordsets/datarecordset%d.xml``
        part in the package (content-type
        ``application/vnd.ms-visio.dataRecordSets+xml``). Author-from-
        scratch packages carry zero recordsets; real Visio drawings that
        have imported external data carry one part per bound source
        (ODBC query, Excel range, SharePoint list).

        Read-only in 0.2.0 — authoring (``add_data_recordset`` /
        ``shape.add_data_binding``) is deferred. See
        :mod:`vsdx.data_recordsets`.

        .. versionadded:: 0.2.0
        """
        return DataRecordsets(self)

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

        When the package carries several theme parts (e.g. per-page
        theme overrides at ``/visio/theme/theme2.xml``), this returns
        the theme related from the document part — i.e. the
        package-wide default. Use :attr:`themes` to enumerate them all.

        .. versionadded:: 0.1.0
        """
        document_part = cast("VisioDocumentPart", self._package.document_part)
        theme_part = document_part.theme_part
        if theme_part is None:
            return None
        return Theme(theme_part)

    @property
    def themes(self) -> list[Theme]:
        """Every theme part in the package, wrapped as :class:`Theme`.

        Walks every :class:`~vsdx.parts.theme.ThemePart` reachable from
        the package (regardless of what relates to it) and returns the
        matching proxy in package-iteration order. An empty list is
        returned when the package has no theme parts — authored-from-
        scratch packages until seed-template injection (track 4) lands.

        Order is *not* guaranteed to match partname order; callers that
        care about theme1 / theme2 ordering should sort by
        ``theme.part.partname``.

        .. versionadded:: 0.3.0
        """
        from vsdx.parts.theme import ThemePart

        return [
            Theme(p) for p in self._package.iter_parts() if isinstance(p, ThemePart)
        ]

    # -- ink annotations ------------------------------------------------

    @property
    def ink_strokes(self) -> list[InkStroke]:
        """Flat list of |InkStroke| across every page in this document.

        Concatenates :attr:`vsdx.page.Page.ink_strokes` for each page in
        :attr:`pages` (foreground + background) in source order. Returns
        an empty list when no page carries an ink part.

        .. versionadded:: 0.3.0
        """
        result: list[InkStroke] = []
        for page in self.pages:
            result.extend(page.ink_strokes)
        return result

    # -- convenience ----------------------------------------------------

    @property
    def package(self) -> VisioPackage:
        return self._package

    # -- save / open ----------------------------------------------------

    def save(
        self,
        target: Union[str, IO[bytes]],
        password: Optional[str] = None,
    ) -> None:
        """Write the document to *target* (path or file-like).

        When *password* is provided, the produced ``.vsdx`` zip is wrapped
        in an ECMA-376 Agile Encryption CFB container (the same container
        Microsoft Visio/Office produces when the user sets a password in
        the desktop app). Encryption requires the optional
        ``python-ooxml-crypto`` dependency; an :class:`ImportError` from
        the missing module is re-raised as
        :class:`~vsdx.exc.EncryptedPackageError`.

        Unicode passwords are accepted verbatim and encoded internally by
        ``ooxml_crypto`` (UTF-16-LE per MS-OFFCRYPTO). The password is
        never logged or included in exception messages raised by this
        method.

        .. versionadded:: 0.3.0
           The *password* parameter.
        """
        if password is None:
            self._package.save(target)
            return

        try:
            import ooxml_crypto
        except ImportError as exc:  # pragma: no cover - optional dep
            raise EncryptedPackageError(
                "Password-protected save requires the optional "
                "'python-ooxml-crypto' package."
            ) from exc

        plain_buf = io.BytesIO()
        self._package.save(plain_buf)
        # -- never include the password in error messages; re-raise as a
        # -- generic EncryptedPackageError so the secret is not surfaced.
        try:
            encrypted = ooxml_crypto.encrypt(plain_buf.getvalue(), password)
        except ooxml_crypto.OoxmlCryptoError as exc:
            # -- surface the exception type but never the password. --
            exc_name = type(exc).__name__
            raise EncryptedPackageError(
                "Encryption failed: %s" % exc_name
            ) from None

        if isinstance(target, str):
            with open(target, "wb") as fh:
                fh.write(encrypted)
        else:
            target.write(encrypted)

    @staticmethod
    def open(
        source: Union[str, IO[bytes]],
        password: Optional[str] = None,
    ) -> VisioDocument:
        """Open an existing ``.vsdx`` / ``.vsdm`` drawing, decrypting if needed.

        When *source* refers to an ECMA-376 Agile-Encryption CFB container,
        *password* is required to decrypt the inner zip before the OPC
        loader parses it. The decrypted bytes are held in memory only
        for the duration of ``_load`` and then discarded.

        :raises EncryptedPackageError: when *source* is encrypted and
            either *password* is ``None`` or the password does not
            match the verifier stored in the container. The password
            itself is never surfaced in the exception message.

        .. versionadded:: 0.3.0
        """
        # -- local import to avoid a cycle with vsdx.package --
        from vsdx.package import VisioPackage

        stream = _coerce_to_stream(source)
        if _looks_like_encrypted(stream):
            if password is None:
                raise EncryptedPackageError(
                    "Package is password-protected; pass password= to open it."
                )
            try:
                import ooxml_crypto
            except ImportError as exc:  # pragma: no cover - optional dep
                raise EncryptedPackageError(
                    "Password-protected open requires the optional "
                    "'python-ooxml-crypto' package."
                ) from exc

            stream.seek(0)
            cipher = stream.read()
            # -- keep the password out of the exception text --
            try:
                plain = ooxml_crypto.decrypt(cipher, password)
            except ooxml_crypto.WrongPasswordError:
                raise EncryptedPackageError(
                    "Supplied password does not match the stored verifier."
                ) from None
            except ooxml_crypto.OoxmlCryptoError as exc:
                exc_name = type(exc).__name__
                raise EncryptedPackageError(
                    "Decryption failed: %s" % exc_name
                ) from None

            package = VisioPackage.open(io.BytesIO(plain))
        else:
            stream.seek(0)
            package = VisioPackage.open(stream)

        return VisioDocument(package.main_document_part, package)


_OLE_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _coerce_to_stream(source: Union[str, IO[bytes]]) -> IO[bytes]:
    """Return a seekable binary stream for *source* (path or file-like)."""
    if isinstance(source, str):
        with open(source, "rb") as fh:
            return io.BytesIO(fh.read())
    # -- file-like: ensure we can peek without consuming the caller's stream --
    pos = source.tell() if hasattr(source, "tell") else 0
    data = source.read()
    # -- rewind caller's stream when possible so they can reuse it --
    try:
        source.seek(pos)
    except (OSError, AttributeError):
        pass
    return io.BytesIO(data)


def _looks_like_encrypted(stream: IO[bytes]) -> bool:
    """Return True when *stream* starts with the OLE CFB magic bytes.

    The password-protected OOXML family (docx/pptx/xlsx/vsdx) wraps the
    inner zip in an OLE2 compound-document container; the container
    magic is a stable 8-byte prefix independent of the algorithm.
    """
    stream.seek(0)
    head = stream.read(len(_OLE_CFB_MAGIC))
    stream.seek(0)
    return head == _OLE_CFB_MAGIC


class EncryptedPackageError(ValueError):
    """Raised when an encrypted vsdx is opened without a valid password,
    or when a password-protected save/open fails.

    Inherits from :class:`ValueError` for symmetry with the `python-pptx`
    and `python-docx` exception hierarchies; callers that want to catch
    all "bad input to an authoring API" signals may continue to use
    :class:`ValueError`.

    The stored password is **never** included in the exception message.
    """


__all__ = ["EncryptedPackageError", "VisioDocument"]
