"""Top-level factories — :func:`Visio`, :func:`Stencil`, :func:`Template`.

Analogues of :func:`pptx.Presentation` / :func:`docx.Document`, extended
with Visio's stencil / template sibling packages. All three go through
a single :class:`VisioPackage` — the three factories differ in which
root content-type they stamp on ``/visio/document.xml`` (drawing /
stencil / template) and which macro-enabled variant they register for
round-trip.

.. versionchanged:: 0.2.0
    Added :func:`Stencil`, :func:`Template`, and
    :class:`VisioPackageOpener`. The shared ``VisioPackage.open()``
    discriminates on root content-type; the three public factories
    assert the *expected* kind and raise on mismatch.
"""

from __future__ import annotations

from typing import IO, Optional, Union

from vsdx.constants import (
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_MACRO_DRAWING_MAIN,
    CT_VSDX_MACRO_STENCIL_MAIN,
    CT_VSDX_MACRO_TEMPLATE_MAIN,
    CT_VSDX_STENCIL_MAIN,
    CT_VSDX_TEMPLATE_MAIN,
    VSDX_KIND_DRAWING,
    VSDX_KIND_STENCIL,
    VSDX_KIND_TEMPLATE,
)
from vsdx.document import VisioDocument
from vsdx.package import VisioPackage


def _kind_of(package: VisioPackage) -> str:
    """Return the ``kind`` discriminator string for *package*.

    Dispatches on the root document-part content-type.
    """
    ct = package.main_document_part.content_type
    if ct in (CT_VSDX_DRAWING_MAIN, CT_VSDX_MACRO_DRAWING_MAIN):
        return VSDX_KIND_DRAWING
    if ct in (CT_VSDX_STENCIL_MAIN, CT_VSDX_MACRO_STENCIL_MAIN):
        return VSDX_KIND_STENCIL
    if ct in (CT_VSDX_TEMPLATE_MAIN, CT_VSDX_MACRO_TEMPLATE_MAIN):
        return VSDX_KIND_TEMPLATE
    raise ValueError(
        "unrecognised Visio root content-type %r" % ct
    )


class VisioPackageOpener:
    """Content-type-aware opener — dispatches on extension / CT.

    Usage::

        doc = VisioPackageOpener.open("report.vsdx")
        stencil = VisioPackageOpener.open("shapes.vssx")
        template = VisioPackageOpener.open("seed.vstx")

    Each call returns a :class:`~vsdx.document.VisioDocument` bound
    to the matching :class:`VisioPackage`; inspect :attr:`VisioPackage.kind`
    to discover whether the file was loaded as drawing / stencil /
    template.

    .. versionadded:: 0.2.0
    """

    @staticmethod
    def open(
        source: Union[str, "IO[bytes]"],
        strict: bool = False,
    ) -> VisioDocument:
        package = VisioPackage.open(source, strict=strict)
        return VisioDocument(package.main_document_part, package)


def Visio(
    source: Optional[Union[str, "IO[bytes]"]] = None,
    strict: bool = False,
) -> VisioDocument:
    """Open an existing ``.vsdx`` / ``.vsdm`` or start a blank drawing.

    :param source: Path to an existing Visio drawing, a file-like
        object, or ``None`` to create a new blank document.
    :param strict: When ``True``, forces Strict ECMA-376 conformance
        handling even if the namespace sniff is inconclusive.
        Defaults to ``False`` (auto-detect). ``[Added in 0.3.0]``
    :returns: A :class:`~vsdx.document.VisioDocument` proxy.

    A new document starts empty — call ``doc.pages.add_page()`` to
    add the first page before adding shapes.

    .. versionchanged:: 0.2.0
        Accepts ``.vsdm`` files as well as ``.vsdx``. Raises
        :class:`ValueError` if the file's root content-type is a
        stencil or template (use :func:`Stencil` / :func:`Template`).
    .. versionadded:: 0.3.0
        The *strict* parameter.
    """
    if source is None:
        package = VisioPackage.new()
        return VisioDocument(package.main_document_part, package)
    package = VisioPackage.open(source, strict=strict)
    kind = _kind_of(package)
    if kind != VSDX_KIND_DRAWING:
        raise ValueError(
            "Visio() expected a drawing, got a %s — use %s() instead"
            % (kind, kind.capitalize())
        )
    return VisioDocument(package.main_document_part, package)


def Stencil(
    source: Optional[Union[str, "IO[bytes]"]] = None,
    strict: bool = False,
) -> VisioDocument:
    """Open a ``.vssx`` / ``.vssm`` stencil or start a blank stencil.

    Stencils are structurally identical to drawings but carry a
    stencil root content-type and typically have no ``<Pages>`` —
    they exist to share reusable masters across documents.

    :param source: Path to an existing stencil, a file-like object,
        or ``None`` to create a new blank stencil.
    :param strict: ``True`` forces Strict ECMA-376 conformance
        handling; defaults to auto-detect. ``[Added in 0.3.0]``
    :raises ValueError: when opening a file whose root content-type
        is not a stencil.

    .. versionadded:: 0.2.0
    .. versionadded:: 0.3.0
        The *strict* parameter.
    """
    if source is None:
        package = VisioPackage.new(kind=VSDX_KIND_STENCIL)
        return VisioDocument(package.main_document_part, package)
    package = VisioPackage.open(source, strict=strict)
    kind = _kind_of(package)
    if kind != VSDX_KIND_STENCIL:
        raise ValueError(
            "Stencil() expected a stencil, got a %s — use %s() instead"
            % (kind, kind.capitalize())
        )
    return VisioDocument(package.main_document_part, package)


def Template(
    source: Optional[Union[str, "IO[bytes]"]] = None,
    strict: bool = False,
) -> VisioDocument:
    """Open a ``.vstx`` / ``.vstm`` template or start a blank template.

    Templates behave identically to drawings at the file-format level
    — Visio desktop treats them as read-only seeds and prompts the
    user to Save-As on open, but the XML schema is identical.

    :param source: Path to an existing template, a file-like object,
        or ``None`` to create a new blank template.
    :param strict: ``True`` forces Strict ECMA-376 conformance
        handling; defaults to auto-detect. ``[Added in 0.3.0]``
    :raises ValueError: when opening a file whose root content-type
        is not a template.

    .. versionadded:: 0.2.0
    .. versionadded:: 0.3.0
        The *strict* parameter.
    """
    if source is None:
        package = VisioPackage.new(kind=VSDX_KIND_TEMPLATE)
        return VisioDocument(package.main_document_part, package)
    package = VisioPackage.open(source, strict=strict)
    kind = _kind_of(package)
    if kind != VSDX_KIND_TEMPLATE:
        raise ValueError(
            "Template() expected a template, got a %s — use %s() instead"
            % (kind, kind.capitalize())
        )
    return VisioDocument(package.main_document_part, package)


__all__ = ["Stencil", "Template", "Visio", "VisioPackageOpener"]
