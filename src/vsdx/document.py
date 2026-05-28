"""``VisioDocument`` — the top-level proxy wrapping the document part.

Analogue of ``pptx.presentation.Presentation`` / ``docx.document.Document``.

Owns :class:`~vsdx.page.Pages` and :class:`~vsdx.master.Masters`
collections, and dispatches ``save`` through to the underlying
:class:`~vsdx.parts._stubs.VisioPackage`.
"""

from __future__ import annotations

import io
from typing import IO, TYPE_CHECKING, Any, Mapping, Optional, Union, cast

from vsdx.data_graphics import DataGraphics
from vsdx.data_recordsets import DataRecordsets
from vsdx.data_sources import DataSources
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

    @lazyproperty
    def data_sources(self) -> DataSources:
        """The document's :class:`~vsdx.data_sources.DataSources` collection.

        Higher-level CSV-backed data-source overlay introduced in 0.4.0
        for issue #118. Sits *above* :attr:`data_recordsets` — where
        recordsets mirror Visio's own external-data machinery,
        :class:`DataSources` is a vsdx-local authoring surface for
        binding shapes to CSV rows and rendering visual indicators.

        Use :meth:`vsdx.page.Page.add_data_source` rather than this
        collection's :meth:`~vsdx.data_sources.DataSources.add` for
        the public authoring spelling — pages forward to here so every
        page sees the same source pool.

        .. versionadded:: 0.4.0
        """
        return DataSources(self)

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

    # -- SVG batch export ------------------------------------------------

    def to_svg_all(self, directory: str) -> list[str]:
        """Render every page in this document into *directory* as SVG.

        *directory* is created if it does not exist. Each page emits
        a ``page-<index>-<safe-name>.svg`` file; the returned list
        carries the written paths in page-iteration order so callers
        can tee into a manifest or assemble a lightweight HTML
        gallery.

        See :meth:`vsdx.page.Page.to_svg` for the supported-shape
        list and the scale / coordinate conventions.

        .. versionadded:: 0.2.0
        """
        from vsdx.svg import document_to_svg_all

        return document_to_svg_all(self, directory)

    # -- ShapeSheet formula recomputation -------------------------------

    def recompute(self) -> int:
        """Re-evaluate every formula on every shape on every page.

        Convenience wrapper that calls :meth:`Page.recompute` for each
        page in :attr:`pages` and sums the change counts. Use this
        before :meth:`save` when you've authored a document with
        formula cells and need ``@V`` to reflect the formulas without
        a Visio open / save cycle.

        .. versionadded:: 0.3.0
        """

        total = 0
        for page in self.pages:
            total += page.recompute()
        return total

    # -- convenience ----------------------------------------------------

    @property
    def package(self) -> VisioPackage:
        return self._package

    # -- stencil hot-swap ----------------------------------------------

    def swap_stencil(
        self,
        from_set: "Any",
        to_set: "Any",
        on_missing: str = "keep-old",
        name_map: "Optional[Mapping[str, str]]" = None,
    ) -> "Any":
        """Bulk-rebind every shape from one stencil set to another.

        See :func:`vsdx.diagram.swap_stencil` for the full description
        and the worked walkthrough; this method is a thin
        delegating wrapper so the entry point lives on the document.

        :returns: a :class:`~vsdx.diagram.SwapReport`.

        .. versionadded:: 0.3.0
        """
        from vsdx.diagram import swap_stencil as _swap_stencil

        return _swap_stencil(
            self,
            from_set=from_set,
            to_set=to_set,
            on_missing=on_missing,
            name_map=name_map,
        )

    def swap_shapes(
        self,
        pattern: "Mapping[str, Any]",
        new_master: "Any",
    ) -> int:
        """Surgical per-shape master swap matching *pattern*.

        Thin delegating wrapper around :func:`vsdx.diagram.swap_shapes`.
        Returns the number of shapes rebound.

        .. versionadded:: 0.3.0
        """
        from vsdx.diagram import swap_shapes as _swap_shapes

        return _swap_shapes(self, pattern=pattern, new_master=new_master)

    def update_theme(self, theme: "Any") -> None:
        """Replace this document's theme element with *theme*'s.

        Thin delegating wrapper around :func:`vsdx.diagram.update_theme`.
        See that function for the *theme* parameter contract.

        .. versionadded:: 0.3.0
        """
        from vsdx.diagram import update_theme as _update_theme

        _update_theme(self, theme=theme)

    # -- save / open ----------------------------------------------------

    # -- strict / conformance -------------------------------------------

    @property
    def is_strict(self) -> bool:
        """``True`` when this package was loaded as ECMA-376 Strict.

        Delegates to :attr:`ooxml_opc.OpcPackage.is_strict`. Authoring-
        path packages (created via :func:`vsdx.Visio()`) are Transitional
        by default. Assigning ``True`` / ``False`` flips the flag so
        :meth:`save` emits the requested conformance class on the next
        write (unless the *strict* kwarg on :meth:`save` overrides it).

        .. versionadded:: 0.3.0
        """
        return self._package.is_strict

    @is_strict.setter
    def is_strict(self, value: bool) -> None:
        self._package.is_strict = bool(value)

    def save(
        self,
        target: Union[str, IO[bytes]],
        password: Optional[str] = None,
        strict: Optional[bool] = None,
        reproducible: bool = False,
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

        *strict* controls ECMA-376 conformance-class handling on emission:

        - ``None`` (default) — preserve the class the package was loaded
          with (:attr:`is_strict`). Round-trip-preserving.
        - ``True`` — emit a Strict package regardless of source.
        - ``False`` — emit a Transitional package regardless of source.

        ``reproducible=True`` is the deterministic-build shorthand
        (issue #150). Every zip-member is stamped with the fixed
        1980-01-01 timestamp, member writes are sorted alphabetically,
        and external file attributes are normalised so the saved
        ``.vsdx`` is byte-identical for byte-identical inputs across
        machines and runs. Composes with ``password`` — the inner
        plaintext zip is built reproducibly before the encryption
        wrapper is applied. The matching keyword is also accepted by
        the sibling ``python-docx`` / ``python-pptx`` / ``python-xlsx``
        parents.

        .. versionadded:: 0.3.0
           The *password* and *strict* parameters.
        .. versionadded:: 0.3.1
           The *reproducible* parameter (issue #150).
        """
        # Auto-resize containers whose ``auto_resize`` flag is set, so
        # the on-disk ``Width``/``Height`` reflect the current
        # membership without the caller having to call
        # :meth:`Container.fit_to_members` manually. Pages may be
        # absent on stencil-flavoured packages (``.vssx``) so the
        # whole pass is best-effort.
        try:
            pages = self.pages
        except Exception:  # noqa: BLE001 - stencils have no pages part
            pages = []
        for page in pages:
            try:
                page._apply_container_auto_resize()
            except Exception:  # noqa: BLE001 -- best-effort fitter
                # A misbehaving fitter must never block a save —
                # callers can still :meth:`fit_to_members` explicitly
                # to surface the error.
                pass

        if password is None:
            self._package.save(target, strict=strict, reproducible=reproducible)
            return

        try:
            import ooxml_crypto
        except ImportError as exc:  # pragma: no cover - optional dep
            raise EncryptedPackageError(
                "Password-protected save requires the optional "
                "'python-ooxml-crypto' package."
            ) from exc

        plain_buf = io.BytesIO()
        self._package.save(plain_buf, strict=strict, reproducible=reproducible)
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
        strict: bool = False,
    ) -> VisioDocument:
        """Open an existing ``.vsdx`` / ``.vsdm`` drawing, decrypting if needed.

        When *source* refers to an ECMA-376 Agile-Encryption CFB container,
        *password* is required to decrypt the inner zip before the OPC
        loader parses it. The decrypted bytes are held in memory only
        for the duration of ``_load`` and then discarded.

        *strict* controls ECMA-376 conformance-class handling at load:

        - ``False`` (default) — auto-detect. Packages declaring the
          Strict OOXML namespace family (``purl.oclc.org/ooxml``) are
          opened in Strict mode and :attr:`is_strict` becomes ``True``.
        - ``True`` — explicitly opt in. Useful for Flat-OPC Strict
          packages whose sniff is inconclusive.

        :raises EncryptedPackageError: when *source* is encrypted and
            either *password* is ``None`` or the password does not
            match the verifier stored in the container. The password
            itself is never surfaced in the exception message.

        .. versionadded:: 0.3.0
           The *strict* parameter.
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

            package = VisioPackage.open(io.BytesIO(plain), strict=strict)
        else:
            stream.seek(0)
            package = VisioPackage.open(stream, strict=strict)

        return VisioDocument(package.main_document_part, package)


_OLE_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


#: Hard input-size ceiling for ``VisioDocument.open``. Visio desktop tops
#: out well below this for real drawings; an attacker-supplied multi-GB
#: blob otherwise forces an unbounded ``source.read()`` into a
#: :class:`~io.BytesIO` allocation before any zip header is sniffed. 512
#: MiB is generous enough that legitimate enterprise drawings with large
#: embedded raster data still open, yet tight enough to fail closed on
#: pathological inputs without resorting to streaming zip decoders.
MAX_VSDX_BYTES = 512 * 1024 * 1024


class OoxmlVsdxError(ValueError):
    """Raised by ``python-vsdx`` on malformed or policy-rejected input.

    Inherits from :class:`ValueError` for symmetry with the other
    python-ooxml parent libraries' exception hierarchies. Callers that
    want to catch every "unacceptable input" signal may continue to use
    :class:`ValueError`.

    Currently surfaced when the input stream exceeds
    :data:`MAX_VSDX_BYTES`. Other policy rejections will reuse this
    class as they land.
    """


def _coerce_to_stream(source: Union[str, IO[bytes]]) -> IO[bytes]:
    """Return a seekable binary stream for *source* (path or file-like).

    Reads are capped at :data:`MAX_VSDX_BYTES`. A source that yields more
    bytes than the cap raises :class:`OoxmlVsdxError` without returning
    a stream (so callers never see the oversize buffer).
    """
    cap = MAX_VSDX_BYTES
    if isinstance(source, str):
        with open(source, "rb") as fh:
            data = fh.read(cap + 1)
        if len(data) > cap:
            raise OoxmlVsdxError(
                "Input file exceeds %d-byte cap; refusing to load."
                % cap
            )
        return io.BytesIO(data)
    # -- file-like: ensure we can peek without consuming the caller's stream --
    pos = source.tell() if hasattr(source, "tell") else 0
    data = source.read(cap + 1)
    # -- rewind caller's stream when possible so they can reuse it --
    try:
        source.seek(pos)
    except (OSError, AttributeError):
        pass
    if len(data) > cap:
        raise OoxmlVsdxError(
            "Input stream exceeds %d-byte cap; refusing to load." % cap
        )
    return io.BytesIO(data)


def _looks_like_encrypted(stream: IO[bytes]) -> bool:
    """Return True when *stream* starts with the OLE CFB magic bytes.

    The password-protected OOXML family (docx/pptx/xlsx/vsdx) wraps the
    inner zip in an OLE2 compound-document container; the container
    magic is a stable 8-byte prefix independent of the algorithm.

    Only reads the fixed 8-byte magic — the :data:`MAX_VSDX_BYTES` cap
    is enforced upstream in :func:`_coerce_to_stream`, so by the time
    this helper runs the stream is already size-bounded.
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


__all__ = [
    "EncryptedPackageError",
    "MAX_VSDX_BYTES",
    "OoxmlVsdxError",
    "VisioDocument",
]
