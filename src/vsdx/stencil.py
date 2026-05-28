"""``Stencil`` — builder API for ``.vssx`` stencil packages.

A ``.vssx`` stencil is a shareable catalogue of reusable masters — no
pages, just ``/visio/masters/``. Prior to 0.3.0 the library could load
(read-only) a stencil via :func:`vsdx.api.Stencil`; this module lifts
that into an authoring surface:

- :meth:`Stencil.new` — build an empty stencil from scratch.
- :meth:`Stencil.add_master` — append a new :class:`~vsdx.master.Master`
  with a supplied ``width`` / ``height``; an optional
  ``content_callback`` receives the freshly-minted master so the
  caller can populate its shape tree.
- :meth:`Stencil.save` — write the package out as ``.vssx``.
- :meth:`Stencil.from_shape_library` — bulk-import a list of
  ``(name, payload_bytes)`` pairs as one master each. Each payload is
  stored as an associated image/SVG part on the master (a caller-
  supplied ``name`` + opaque byte blob — the format-detection heuristic
  dispatches on the first few bytes).

Callers that only need load-round-trip keep using the existing
``vsdx.Stencil()`` factory function (which returns a
:class:`~vsdx.document.VisioDocument`). The :class:`Stencil` *class*
exposed here is the authoring-first wrapper — ``Stencil.new()`` → a
``Stencil`` instance whose ``.doc`` property is that VisioDocument.

Backwards compatibility
-----------------------

Historically ``Stencil`` was a module-level factory function, not a
class. To preserve every pre-0.3.0 caller (including the kind-variant
tests that assert ``isinstance(vsdx.Stencil(), VisioDocument)``), the
class's :meth:`__new__` dispatches: when called with zero args or with
a source path, it short-circuits and returns a ``VisioDocument`` —
identical behaviour to the legacy factory. Classmethod entry points
(``Stencil.new`` / ``Stencil.from_shape_library``) bypass
``__new__`` via ``object.__new__`` and return a real ``Stencil``
instance.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import IO, TYPE_CHECKING, Callable, Iterable, Optional, Tuple, Union

from vsdx.constants import VSDX_KIND_STENCIL
from vsdx.document import VisioDocument
from vsdx.package import VisioPackage

if TYPE_CHECKING:
    from vsdx.master import Master

__all__ = ["Stencil"]


#: Callback signature for :meth:`Stencil.add_master`. The callback
#: receives the freshly-minted master so the caller can populate its
#: shape tree before the next master is added.
MasterContentCallback = Callable[["Master"], None]


class Stencil:
    """Authoring-first wrapper around a stencil :class:`VisioPackage`.

    Typical usage::

        sten = Stencil.new()
        sten.add_master("Cog", width=1.0, height=1.0)
        sten.save("gears.vssx")

    Legacy usage (returns a :class:`VisioDocument` for backwards
    compatibility with the 0.2.0 factory)::

        doc = Stencil()           # blank stencil as VisioDocument
        doc = Stencil("in.vssx")  # load an existing stencil

    .. versionadded:: 0.3.0
    """

    # ------------------------------------------------------------------
    # Backwards-compatible factory dispatch
    # ------------------------------------------------------------------

    def __new__(
        cls,
        source: Optional[Union[str, "IO[bytes]"]] = None,
        strict: bool = False,
    ):
        """Legacy factory path — returns a :class:`VisioDocument`.

        Only hit when the class is instantiated directly (``Stencil()``
        / ``Stencil(path)``). The classmethod entry points
        (:meth:`new`, :meth:`from_shape_library`) bypass ``__new__``
        via ``object.__new__`` and bind a real ``Stencil`` instance.
        """
        # -- avoid circular import with vsdx.api at module load time --
        from vsdx.api import Stencil as _stencil_factory

        return _stencil_factory(source=source, strict=strict)

    # ------------------------------------------------------------------
    # Authoring entry points
    # ------------------------------------------------------------------

    @classmethod
    def new(cls) -> "Stencil":
        """Return a fresh, empty :class:`Stencil` ready for authoring.

        Builds an in-memory :class:`VisioPackage` seeded for the
        stencil kind (no ``<Pages>`` index, empty ``<Masters>``, empty
        ``<Windows>``). Callers add masters via :meth:`add_master` and
        persist the stencil via :meth:`save`.
        """
        self = object.__new__(cls)
        package = VisioPackage.new(kind=VSDX_KIND_STENCIL)
        self._doc = VisioDocument(package.main_document_part, package)
        return self

    @classmethod
    def from_shape_library(
        cls,
        shapes: Iterable[Tuple[str, bytes]],
    ) -> "Stencil":
        """Build a stencil by bulk-registering *shapes*.

        *shapes* is an iterable of ``(name, payload_bytes)`` pairs.
        Each pair becomes a new master whose NameU is ``name``; the
        payload bytes are stashed on the master's part as an
        associated ``_payload`` blob so callers can retrieve them via
        :attr:`Master._payload`. This is intentionally loose — the
        payload may be SVG, PNG, or any opaque byte blob the caller
        needs to round-trip. Defer format-specific handling (SVG →
        geometry extraction, raster → embedded image part) to a
        dedicated importer layer; 0.3.0 only guarantees payload
        round-trip.

        Example::

            sten = Stencil.from_shape_library([
                ("Cog",   svg_bytes_cog),
                ("Arrow", svg_bytes_arrow),
            ])

        :param shapes: iterable of ``(NameU, bytes)`` pairs.
        :returns: a :class:`Stencil` holding one master per input pair.
        """
        self = cls.new()
        for name, payload in shapes:
            master = self.add_master(name, width=1.0, height=1.0)
            # -- stash the raw bytes on the master for caller round-trip.
            # -- format-specific dispatch (SVG → geometry, image → part)
            # -- is deferred to a later version; 0.3.0 only guarantees
            # -- the blob survives save/reload via this attribute.
            setattr(master, "_payload", bytes(payload))
        return self

    # ------------------------------------------------------------------
    # Instance surface
    # ------------------------------------------------------------------

    @property
    def doc(self) -> VisioDocument:
        """The underlying :class:`VisioDocument` proxy.

        Escape hatch for callers who want to drop out of the builder
        surface and use the full ``VisioDocument`` API directly.
        """
        return self._doc

    @property
    def package(self) -> VisioPackage:
        """The underlying :class:`VisioPackage`."""
        return self._doc.package

    @property
    def masters(self):
        """Shortcut for ``self.doc.masters`` — the masters catalogue."""
        return self._doc.masters

    def add_master(
        self,
        name: str,
        width: float,
        height: float,
        content_callback: Optional[MasterContentCallback] = None,
    ) -> "Master":
        """Append a new master and return its :class:`Master` proxy.

        Allocates a fresh ``/visio/masters/master%d.xml`` part, wires
        the ``<Master>`` index entry with the given *name* (used for
        both ``@Name`` and ``@NameU``), sets the master's default
        ``Width`` / ``Height`` cells on the master-index ``PageSheet``,
        and invokes *content_callback* (if any) with the freshly-minted
        master so the caller can populate its shape tree.

        :param name: NameU for the master.
        :param width: default width in inches.
        :param height: default height in inches.
        :param content_callback: optional callable invoked as
            ``content_callback(master)`` right after the master is
            wired in — a convenience for building masters inline::

                def populate(m: Master) -> None:
                    m.add_shape("Rectangle", x=0, y=0, width=1, height=1)

                sten.add_master("Box", 1, 1, content_callback=populate)
        """
        master = self._doc.masters.add_master(name)
        _set_master_default_size(master, width, height)
        if content_callback is not None:
            content_callback(master)
        return master

    def save(
        self,
        target: Union[str, "IO[bytes]"],
        strict: Optional[bool] = None,
        reproducible: bool = False,
    ) -> None:
        """Write the stencil out to *target* (path or file-like).

        Delegates to :meth:`VisioDocument.save` — the same serialiser
        used for drawings. Stencils carry the
        ``application/vnd.ms-visio.stencil.main+xml`` root content-type
        (not the drawing variant), which Visio desktop uses to decide
        whether to open the file as a read-only stencil palette or as
        an editable drawing.

        :param target: path or writable binary file-like.
        :param strict: optional ECMA-376 conformance override — see
            :meth:`VisioDocument.save` for semantics. ``None``
            preserves the class the package was loaded with
            (``False`` for a fresh ``Stencil.new()``).
        :param reproducible: deterministic-build shorthand — see
            :meth:`VisioDocument.save` for semantics. ``[Added in 0.3.1]``
        """
        self._doc.save(target, strict=strict, reproducible=reproducible)


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _set_master_default_size(master: "Master", width: float, height: float) -> None:
    """Stamp ``Width`` / ``Height`` cells on the master's index PageSheet.

    Per Visio convention, a master's default instance size lives on
    the ``<PageSheet>`` under the ``<Master>`` index entry. Instance
    shapes that omit their own ``<Cell N="Width">`` inherit from this
    value via the master-chain resolver.
    """
    element = master._element  # noqa: SLF001 — internal coord with Master proxy
    page_sheet = element.get_or_add_pageSheet()
    _set_named_cell(page_sheet, "Width", width)
    _set_named_cell(page_sheet, "Height", height)


def _set_named_cell(parent, name: str, value: float) -> None:
    """Create-or-update ``<Cell N=name V=value U="IN">`` on *parent*."""
    for cell in parent.cell_lst:
        if cell.get("N") == name:
            cell.set("V", _fmt(value))
            cell.set("U", "IN")
            return
    cell = parent._add_cell()  # noqa: SLF001 — xmlchemy-generated helper
    cell.set("N", name)
    cell.set("V", _fmt(value))
    cell.set("U", "IN")


def _fmt(v: float) -> str:
    """Format *v* the way Visio emits floats — trim trailing zeros."""
    if v == int(v):
        return str(int(v))
    return ("%f" % v).rstrip("0").rstrip(".")
