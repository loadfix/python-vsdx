"""Visio theme part — a DrawingML theme inside a ``.vsdx`` package.

Corresponds to ``/visio/theme/theme%d.xml``. The theme is a straight
ECMA-376 Part 1 DrawingML theme
(``application/vnd.openxmlformats-officedocument.theme+xml``), not a
Visio-specific schema — Visio embeds the exact same ``<a:theme>``
document docx / pptx / xlsx use.

Content-level hydration into dedicated ``CT_OfficeStyleSheet`` /
``CT_ColorScheme`` / ``CT_FontScheme`` classes is deferred until the
shared ``python-ooxml-shared-drawingml`` package ships the theme
subset; until then (0.1.0) this part still owns the raw blob for
byte-identical round-trip fidelity, but :attr:`ThemePart.theme_element`
and the ``color_scheme`` / ``font_scheme`` helpers parse the blob
through the hardened shared-drawingml parser and return plain lxml
element views so the proxy layer (:mod:`vsdx.theme`) can query and
mutate theme colours + fonts without reaching into the bytes
directly.

Relationship: :class:`~vsdx.parts.document.VisioDocumentPart` →
``RT.THEME`` → :class:`ThemePart`.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, cast

from ooxml_opc import CONTENT_TYPE as CT
from ooxml_opc import Part

# -- opt-in import: the shared package is a hard runtime dep from
# -- 0.1.0 (declared in pyproject.toml), but we gate the import so the
# -- part remains importable from a docs / wheel-inspection context
# -- where the shared package may not yet be installed.
try:
    from ooxml_shared_drawingml import NS_A
    from ooxml_shared_drawingml import parse_xml as _parse_theme_xml

    _SHARED_DRAWINGML_AVAILABLE = True
except ImportError:  # pragma: no cover — defensive fallback
    NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    _parse_theme_xml = None  # pyright: ignore[reportAssignmentType]
    _SHARED_DRAWINGML_AVAILABLE = False

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage
    from ooxml_opc.packuri import PackURI


__all__ = ["ThemePart"]


def _qn(tag: str) -> str:
    """Return Clark-notation ``{ns}local`` for a DrawingML-prefixed tag."""
    if ":" not in tag:
        return f"{{{NS_A}}}{tag}"
    prefix, local = tag.split(":", 1)
    if prefix != "a":
        raise ValueError(f"unsupported namespace prefix: {prefix!r}")
    return f"{{{NS_A}}}{local}"


class ThemePart(Part):
    """The ``/visio/theme/theme%d.xml`` DrawingML theme part.

    Inherits :class:`~ooxml_opc.part.Part` (not :class:`XmlPart`) so
    the on-disk blob is preserved verbatim for round-trip fidelity —
    shared-drawingml does not yet ship dedicated ``CT_*`` classes for
    the theme subtree (``a:themeElements``, ``a:clrScheme``,
    ``a:fontScheme``, ``a:fmtScheme``), so we can't use the xmlchemy
    descriptor layer to own the tree. When those land in
    ``python-ooxml-shared-drawingml`` a follow-up will:

    - switch the base class to :class:`XmlPart`;
    - expose :attr:`theme_element` typed as the new
      ``CT_OfficeStyleSheet``;
    - drop the in-memory lazy-parse cache below.

    Content-type is the shared ``CT.OFC_THEME`` string
    (``application/vnd.openxmlformats-officedocument.theme+xml``).

    .. versionchanged:: 0.1.0
       Added :attr:`theme_element`, :attr:`name`,
       :meth:`color_scheme`, and :meth:`font_scheme` typed accessors
       backed by the shared ``python-ooxml-shared-drawingml`` parser.
    """

    _PARTNAME_TMPL = "/visio/theme/theme%d.xml"

    def __init__(
        self,
        partname: "PackURI",
        content_type: str,
        package: "OpcPackage",
        blob: Optional[bytes] = None,
    ) -> None:
        super().__init__(partname, content_type, package, blob)
        self._theme_element: Optional[Any] = None

    @classmethod
    def new(
        cls,
        package: "OpcPackage",
        blob: bytes,
    ) -> "ThemePart":
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
        partname: "PackURI",
        content_type: str,
        package: "OpcPackage",
        blob: bytes,
    ) -> "ThemePart":
        """Return a :class:`ThemePart` parsed from an existing package.

        Overrides the base ``Part.load`` signature only to narrow the
        return type — the loading mechanics are unchanged.
        """
        return cls(partname, content_type, package, blob)

    # -- blob getter / setter ------------------------------------------
    # -- Once :attr:`theme_element` has been touched the part owns a
    # -- parsed tree that may have been mutated in place; re-serialise
    # -- on demand so the on-disk bytes reflect those mutations. When
    # -- the tree has never been parsed we return the original bytes
    # -- verbatim so unmodified reads round-trip byte-identically.

    @property
    def blob(self) -> bytes:
        """Contents of this part as bytes.

        Returns the on-load bytes verbatim until :attr:`theme_element`
        has been accessed; once accessed (and potentially mutated) the
        bytes are regenerated from the parsed element via lxml's
        serialiser so mutations propagate on save.
        """
        if self._theme_element is not None:
            from lxml import etree

            return cast(
                bytes,
                etree.tostring(
                    self._theme_element,
                    xml_declaration=True,
                    encoding="UTF-8",
                    standalone=True,
                ),
            )
        return self._blob or b""

    @blob.setter
    def blob(self, blob: bytes) -> None:
        self._blob = blob
        self._theme_element = None

    # -- typed access -------------------------------------------------

    @property
    def theme_element(self) -> Any:
        """Return the root ``<a:theme>`` element, lazily parsed.

        Parses :attr:`blob` through the shared ``ooxml_shared_drawingml``
        hardened parser (XXE / billion-laughs guarded). The returned
        value is an lxml element view — sufficient for querying and
        mutating scheme children today, and the type will narrow to
        ``CT_OfficeStyleSheet`` once shared-drawingml ships theme
        ``CT_*`` classes.

        Raises :class:`RuntimeError` when ``python-ooxml-shared-drawingml``
        is not installed — this should not occur in a normal install
        (the package is a declared runtime dep).

        .. versionadded:: 0.1.0
        """
        if self._theme_element is None:
            if not _SHARED_DRAWINGML_AVAILABLE or _parse_theme_xml is None:
                raise RuntimeError(
                    "python-ooxml-shared-drawingml is required for typed "
                    "theme access; install the package and retry."
                )
            blob = self.blob
            if not blob:
                raise ValueError(
                    "theme part has no payload; cannot parse theme_element"
                )
            self._theme_element = _parse_theme_xml(blob)
        return self._theme_element

    @property
    def name(self) -> Optional[str]:
        """Value of ``<a:theme name="...">``, or ``None`` if unset.

        .. versionadded:: 0.1.0
        """
        theme = self.theme_element
        value = theme.get("name")
        return value if value is None else str(value)

    @name.setter
    def name(self, value: Optional[str]) -> None:
        theme = self.theme_element
        if value is None:
            theme.attrib.pop("name", None)
        else:
            theme.set("name", value)

    def color_scheme(self) -> Optional[Any]:
        """Return the ``<a:clrScheme>`` element, or ``None`` if absent.

        Returned as a plain lxml element view. Children (``a:dk1``
        through ``a:folHlink``, each wrapping an ``a:srgbClr`` or
        ``a:sysClr``) are queryable with standard ``find`` / ``xpath``
        calls.

        TODO(shared-drawingml): upgrade the return type to
        ``CT_ColorScheme`` when the shared package ships it.

        .. versionadded:: 0.1.0
        """
        theme = self.theme_element
        elements = theme.find(_qn("a:themeElements"))
        if elements is None:
            return None
        return elements.find(_qn("a:clrScheme"))

    def font_scheme(self) -> Optional[Any]:
        """Return the ``<a:fontScheme>`` element, or ``None`` if absent.

        Returned as a plain lxml element view. Children (``a:majorFont``
        and ``a:minorFont``, each with ``a:latin`` / ``a:ea`` /
        ``a:cs`` typeface children) are queryable with standard
        ``find`` / ``xpath`` calls.

        TODO(shared-drawingml): upgrade the return type to
        ``CT_FontScheme`` when the shared package ships it.

        .. versionadded:: 0.1.0
        """
        theme = self.theme_element
        elements = theme.find(_qn("a:themeElements"))
        if elements is None:
            return None
        return elements.find(_qn("a:fontScheme"))
