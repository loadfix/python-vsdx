"""Top-level :class:`VisioPackage` class — the OPC assembly for a ``.vsdx``.

Mirrors ``python-pptx``'s :class:`pptx.package.Package` shape: subclass
:class:`ooxml_opc.OpcPackage`, override :attr:`main_document_part` to
narrow the return type to :class:`VisioDocumentPart`, and provide
convenience factories / part-graph properties for the specialised
part classes (pages, masters, windows, theme).

The 0.1.0 scope covers:

- :class:`VisioPackage.new` — build a minimal in-memory package
  (VisioDocument + empty Pages + empty Masters + Windows) from
  scratch, suitable as the starting point for authoring.
- Lazy accessor properties for each well-known inner part so the
  proxy layer (track 3) can walk the graph without touching raw
  relationships.
- Content-type → part-class registration (see
  :func:`register_visio_parts`) so the shared ``ooxml_opc`` loader
  materialises the correct subclass when opening an existing
  ``.vsdx`` from disk.

Reference: ``python-pptx/src/pptx/package.py`` (closest architectural
analogue — presentation-part-plus-children mirrors the VisioDocument-
part-plus-children layout).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, cast

from ooxml_opc import CONTENT_TYPE as CT
from ooxml_opc import OpcPackage, Part, PartFactory

from vsdx.constants import (
    CT_VBA_PROJECT,
    CT_VSDX_DRAWING_MAIN,
    CT_VSDX_MACRO_DRAWING_MAIN,
    CT_VSDX_MACRO_STENCIL_MAIN,
    CT_VSDX_MACRO_TEMPLATE_MAIN,
    CT_VSDX_MASTER,
    CT_VSDX_MASTERS,
    CT_VSDX_PAGE,
    CT_VSDX_PAGES,
    CT_VSDX_STENCIL_MAIN,
    CT_VSDX_TEMPLATE_MAIN,
    CT_VSDX_WINDOWS,
    RT_VBA_PROJECT,
    RT_VISIO_DOCUMENT,
    RT_VISIO_MASTERS,
    RT_VISIO_PAGES,
    RT_VISIO_WINDOWS,
    VSDX_KIND_DRAWING,
    VSDX_KIND_STENCIL,
    VSDX_KIND_TEMPLATE,
)
from vsdx.parts.document import VisioDocumentPart
from vsdx.parts.master import MasterPart, MastersPart
from vsdx.parts.page import PagePart, PagesPart
from vsdx.parts.stencil import StencilPart
from vsdx.parts.theme import ThemePart
from vsdx.parts.vba import VbaProjectPart
from vsdx.parts.windows import WindowsPart

if TYPE_CHECKING:
    from typing_extensions import Self


__all__ = [
    "VISIO_PART_TYPE_MAP",
    "VisioPackage",
    "register_visio_parts",
]


#: Content-type → :class:`~ooxml_opc.part.Part` class registration
#: table. Applied to :attr:`ooxml_opc.PartFactory.part_type_for` by
#: :func:`register_visio_parts` at import time so the shared loader
#: minted the correct subclass when encountering a Visio part.
VISIO_PART_TYPE_MAP: dict[str, type[Part]] = {
    # -- Visio root variants: drawing / template / stencil + macro twins --
    CT_VSDX_DRAWING_MAIN: VisioDocumentPart,
    CT_VSDX_MACRO_DRAWING_MAIN: VisioDocumentPart,
    CT_VSDX_TEMPLATE_MAIN: VisioDocumentPart,
    CT_VSDX_MACRO_TEMPLATE_MAIN: VisioDocumentPart,
    CT_VSDX_STENCIL_MAIN: StencilPart,
    CT_VSDX_MACRO_STENCIL_MAIN: StencilPart,
    # -- pages + masters: index + per-entry --
    CT_VSDX_PAGES: PagesPart,
    CT_VSDX_PAGE: PagePart,
    CT_VSDX_MASTERS: MastersPart,
    CT_VSDX_MASTER: MasterPart,
    # -- singletons --
    CT_VSDX_WINDOWS: WindowsPart,
    # -- shared theme (DrawingML) --
    CT.OFC_THEME: ThemePart,
    # -- VBA project (opaque blob, macro-enabled variants only) --
    # .. versionadded:: 0.2.0
    CT_VBA_PROJECT: VbaProjectPart,
}


def register_visio_parts(
    factory: type[PartFactory] = PartFactory,
) -> None:
    """Register every entry in :data:`VISIO_PART_TYPE_MAP` with `factory`.

    Defaults to the shared :class:`ooxml_opc.PartFactory` class (the
    class-level ``part_type_for`` dict that the
    :class:`~ooxml_opc.package.OpcPackage` loader consults). Callers
    that operate a private :class:`~ooxml_opc.part.PartFactory`
    subclass can supply it here.

    Idempotent — re-registering the same entry is a no-op. Does not
    overwrite entries already present under a different class (first
    registration wins; allowing later overrides would break
    downstream libraries that registered competing classes earlier).
    """
    for content_type, part_cls in VISIO_PART_TYPE_MAP.items():
        factory.part_type_for.setdefault(content_type, part_cls)


# -- module-level side effect: register with the shared PartFactory --
# -- so ``import vsdx.package`` wires the loader hooks for free.     --
register_visio_parts()


class VisioPackage(OpcPackage):
    """Top-level ``.vsdx`` package.

    Obtain via :meth:`new` (build from scratch) or
    :meth:`~ooxml_opc.package.OpcPackage.open` (load existing). The
    class exposes lazy accessor properties for each well-known inner
    part; the proxy layer (track 3) layers higher-level ``Pages`` /
    ``Masters`` facades on top.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def new(cls, kind: str = VSDX_KIND_DRAWING) -> Self:
        """Return a new, empty :class:`VisioPackage` ready for authoring.

        Wires up the minimum part graph Microsoft Visio expects:

        - :class:`VisioDocumentPart` (drawing/template) or
          :class:`StencilPart` (stencil) at ``/visio/document.xml``
          related from the package root via ``RT_VISIO_DOCUMENT``.
        - Empty :class:`PagesPart` at ``/visio/pages/pages.xml``
          related from the document part via ``RT_VISIO_PAGES``.
          *Not wired for stencils* — stencils legitimately have no
          ``<Pages>`` (scoping doc §3.4).
        - Empty :class:`MastersPart` at ``/visio/masters/masters.xml``
          related from the document part via ``RT_VISIO_MASTERS``.
        - Empty :class:`WindowsPart` at ``/visio/windows.xml`` related
          from the document part via ``RT_VISIO_WINDOWS``.

        Theme and docProps parts are deliberately *not* seeded here —
        :mod:`vsdx.templates` is responsible for injecting the
        seed-template theme + docProps via ``default.vsdx``.

        :param kind: One of ``"drawing"`` / ``"stencil"`` / ``"template"``.
            Drawings and templates share the same parts graph and the
            same root part class (:class:`VisioDocumentPart`) — the
            only diff is the root content-type. Stencils substitute a
            :class:`StencilPart` root and omit the ``PagesPart``.

        .. versionchanged:: 0.2.0
            Added the *kind* parameter. Previous (0.1.0) callers that
            passed no argument still get a drawing.
        """
        package = cls()
        if kind == VSDX_KIND_DRAWING:
            document_part = VisioDocumentPart.new(package)
        elif kind == VSDX_KIND_TEMPLATE:
            document_part = VisioDocumentPart.new_template(package)
        elif kind == VSDX_KIND_STENCIL:
            document_part = StencilPart.new(package)
        else:
            raise ValueError("unknown VisioPackage kind: %r" % kind)
        package.relate_to(document_part, RT_VISIO_DOCUMENT)

        if kind != VSDX_KIND_STENCIL:
            pages_part = PagesPart.new(package)
            document_part.relate_to(pages_part, RT_VISIO_PAGES)

        masters_part = MastersPart.new(package)
        document_part.relate_to(masters_part, RT_VISIO_MASTERS)

        windows_part = WindowsPart.new(package)
        document_part.relate_to(windows_part, RT_VISIO_WINDOWS)

        return package

    # ------------------------------------------------------------------
    # Kind / macro discrimination
    # ------------------------------------------------------------------

    @property
    def kind(self) -> str:
        """Which of ``"drawing"`` / ``"stencil"`` / ``"template"`` this is.

        Dispatches on the root document-part content-type.

        .. versionadded:: 0.2.0
        """
        ct = self.main_document_part.content_type
        if ct in (CT_VSDX_DRAWING_MAIN, CT_VSDX_MACRO_DRAWING_MAIN):
            return VSDX_KIND_DRAWING
        if ct in (CT_VSDX_STENCIL_MAIN, CT_VSDX_MACRO_STENCIL_MAIN):
            return VSDX_KIND_STENCIL
        if ct in (CT_VSDX_TEMPLATE_MAIN, CT_VSDX_MACRO_TEMPLATE_MAIN):
            return VSDX_KIND_TEMPLATE
        raise ValueError(
            "unrecognised Visio root content-type %r" % ct
        )

    @property
    def is_macro_enabled(self) -> bool:
        """``True`` when this package carries a ``vbaProject.bin`` part.

        Macro-enabled variants (``.vsdm`` / ``.vssm`` / ``.vstm``) are
        discriminated purely by the root content-type override (there
        is no schema difference). This property surfaces that
        distinction for UIs that need to warn the user before stripping
        macros on a save-as to a non-macro variant.

        .. versionadded:: 0.2.0
        """
        document_part = self.main_document_part
        for rel in document_part.rels.values():
            if rel.is_external:
                continue
            if rel.reltype == RT_VBA_PROJECT:
                return True
        return False

    @property
    def vba_project_part(self) -> "Optional[VbaProjectPart]":  # noqa: F821
        """The :class:`~vsdx.parts.vba.VbaProjectPart` or ``None``.

        .. versionadded:: 0.2.0
        """
        document_part = self.main_document_part
        for rel in document_part.rels.values():
            if rel.is_external or rel.reltype != RT_VBA_PROJECT:
                continue
            target = rel.target_part
            if isinstance(target, VbaProjectPart):
                return target
        return None

    # ------------------------------------------------------------------
    # Well-known part accessors
    # ------------------------------------------------------------------

    @property
    def main_document_part(self) -> VisioDocumentPart:  # type: ignore[override]
        """Return the root Visio part for this package.

        Overrides :attr:`OpcPackage.main_document_part` — the shared
        base looks for ``RT.OFFICE_DOCUMENT``, but Visio packages use
        ``RT_VISIO_DOCUMENT`` as the package-root → document relship.
        (Microsoft never adopted the OfficeDocument rel-type for
        Visio; see scoping doc §2.4.)
        """
        return cast(
            VisioDocumentPart, self.part_related_by(RT_VISIO_DOCUMENT)
        )

    @property
    def document_part(self) -> VisioDocumentPart:
        """The :class:`VisioDocumentPart` at ``/visio/document.xml``.

        Convenience alias for :attr:`main_document_part`.
        """
        return self.main_document_part

    @property
    def pages_part(self) -> PagesPart:
        """The :class:`PagesPart` at ``/visio/pages/pages.xml``.

        Raises :class:`KeyError` when the document part has no
        ``RT_VISIO_PAGES`` relationship (an ill-formed package).
        """
        return cast(
            PagesPart, self.document_part.part_related_by(RT_VISIO_PAGES)
        )

    @property
    def masters_part(self) -> MastersPart:
        """The :class:`MastersPart` at ``/visio/masters/masters.xml``.

        Raises :class:`KeyError` when the document part has no
        ``RT_VISIO_MASTERS`` relationship. Per scoping doc §2.2 every
        real Visio drawing carries a masters part even if empty —
        :meth:`new` seeds one on build.
        """
        return cast(
            MastersPart,
            self.document_part.part_related_by(RT_VISIO_MASTERS),
        )

    @property
    def windows_part(self) -> WindowsPart:
        """The :class:`WindowsPart` at ``/visio/windows.xml``.

        Raises :class:`KeyError` when the document part has no
        ``RT_VISIO_WINDOWS`` relationship.
        """
        return cast(
            WindowsPart,
            self.document_part.part_related_by(RT_VISIO_WINDOWS),
        )

    def iter_page_parts(self) -> list[PagePart]:
        """Return every :class:`PagePart` reachable from the index.

        Walks the ``RT_VISIO_PAGE`` rels on the :class:`PagesPart`.
        Order matches relationship-insertion order (which in turn
        matches the order ``<Page>`` entries appear in ``pages.xml``).
        """
        pages = self.pages_part
        result: list[PagePart] = []
        for rel in pages.rels.values():
            if rel.is_external:
                continue
            target = rel.target_part
            if isinstance(target, PagePart):
                result.append(target)
        return result

    def iter_master_parts(self) -> list[MasterPart]:
        """Return every :class:`MasterPart` reachable from the index."""
        masters = self.masters_part
        result: list[MasterPart] = []
        for rel in masters.rels.values():
            if rel.is_external:
                continue
            target = rel.target_part
            if isinstance(target, MasterPart):
                result.append(target)
        return result
