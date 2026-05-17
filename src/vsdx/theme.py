"""``Theme`` proxy — high-level view of the DrawingML theme part.

Wraps a :class:`~vsdx.parts.theme.ThemePart` and surfaces the slice of
the theme the authoring API cares about today:

- theme :attr:`name`;
- colour-scheme lookups (``dk1`` / ``lt1`` / ``dk2`` / ``lt2`` /
  ``accent1``–``accent6`` / ``hlink`` / ``folHlink``);
- font-scheme lookups (``majorFont.latin`` / ``minorFont.latin``).

Round-trip fidelity is the primary constraint — the proxy never
reorders children, never drops sibling nodes it doesn't understand,
and leaves the unchanged sub-tree byte-identical to the load.

Track-2 follow-up will swap the lxml element views beneath this
proxy for ``CT_OfficeStyleSheet`` / ``CT_ColorScheme`` /
``CT_FontScheme`` ``CT_*`` classes once
``python-ooxml-shared-drawingml`` ships them; the proxy API below
stays stable across that migration.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

from vsdx.parts.theme import ThemePart

if TYPE_CHECKING:
    pass


__all__ = [
    "ColorScheme",
    "EffectVariant",
    "FontScheme",
    "FontVariation",
    "ShadowParams",
    "Theme",
]


_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _qn(tag: str) -> str:
    """Return Clark-notation for an ``a:``-prefixed DrawingML tag."""
    if ":" not in tag:
        return f"{{{_NS_A}}}{tag}"
    prefix, local = tag.split(":", 1)
    if prefix != "a":
        raise ValueError(f"unsupported namespace prefix: {prefix!r}")
    return f"{{{_NS_A}}}{local}"


class Theme:
    """High-level proxy for the ``/visio/theme/theme1.xml`` DrawingML theme.

    Obtained via :attr:`vsdx.document.VisioDocument.theme`. Mutations
    on this object propagate into the underlying :class:`ThemePart`
    by updating the theme element in place — the part's blob getter
    re-serialises through shared-drawingml on the next save.

    .. versionadded:: 0.1.0
    """

    # -- canonical colour-scheme slot names in XSD order --
    _SCHEME_SLOTS = (
        "dk1", "lt1", "dk2", "lt2",
        "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
        "hlink", "folHlink",
    )

    def __init__(self, theme_part: ThemePart) -> None:
        self._theme_part = theme_part

    @property
    def part(self) -> ThemePart:
        """The underlying :class:`~vsdx.parts.theme.ThemePart`.

        .. versionadded:: 0.1.0
        """
        return self._theme_part

    # -- theme name ---------------------------------------------------

    @property
    def name(self) -> Optional[str]:
        """The theme's ``@name`` attribute value, or ``None`` if unset.

        .. versionadded:: 0.1.0
        """
        return self._theme_part.name

    @name.setter
    def name(self, value: Optional[str]) -> None:
        self._theme_part.name = value

    # -- colour scheme ------------------------------------------------

    @property
    def color_scheme(self) -> "Optional[ColorScheme]":
        """The :class:`ColorScheme` proxy, or ``None`` when the theme has
        no ``<a:clrScheme>`` child.

        The proxy exposes the twelve canonical DrawingML colour slots
        (``dk1`` / ``lt1`` / ``dk2`` / ``lt2`` / ``accent1``-``accent6``
        / ``hlink`` / ``folHlink``) as dotted-attribute accessors
        returning an RGB-hex string, a system-colour name, or ``None``.

        .. versionadded:: 0.3.0
        """
        clr = self._theme_part.color_scheme()
        if clr is None:
            return None
        return ColorScheme(self._theme_part, clr)

    @property
    def font_scheme(self) -> "Optional[FontScheme]":
        """The :class:`FontScheme` proxy, or ``None`` when the theme has
        no ``<a:fontScheme>`` child.

        .. versionadded:: 0.3.0
        """
        fs = self._theme_part.font_scheme()
        if fs is None:
            return None
        return FontScheme(self._theme_part, fs)

    @property
    def effect_variants(self) -> "List[EffectVariant]":
        """Ordered list of the theme's three effect variants.

        Returns one :class:`EffectVariant` per ``a:effectStyle`` child of
        ``a:themeElements/a:fmtScheme/a:effectStyleLst``, capped at the
        first three entries. The DrawingML spec defines three variants
        (subtle, moderate, intense); Visio ships six in-use style
        elements but the authoring surface only exposes the canonical
        three that :meth:`Page.set_effect_variant` can address.

        Returns ``[]`` when the theme has no ``a:fmtScheme`` /
        ``a:effectStyleLst`` / any ``a:effectStyle`` children — bare
        themes authored from scratch fall into this bucket.

        Variant ``preset_num`` values are the 1-based position of the
        corresponding ``a:effectStyle`` in the list (``1``, ``2``,
        ``3``); :meth:`Page.set_effect_variant` accepts the 0-based
        index into :attr:`effect_variants` directly, so callers rarely
        need to read ``preset_num`` explicitly.

        .. versionadded:: 0.4.0
        """
        fmt_scheme = self._fmt_scheme()
        if fmt_scheme is None:
            return []
        effect_style_lst = fmt_scheme.find(_qn("a:effectStyleLst"))
        if effect_style_lst is None:
            return []
        styles = effect_style_lst.findall(_qn("a:effectStyle"))[:3]
        preset_names = ("subtle", "moderate", "intense")
        return [
            EffectVariant(
                name=preset_names[idx],
                preset_num=idx + 1,
                _element=style,
            )
            for idx, style in enumerate(styles)
        ]

    @property
    def font_variations(self) -> "List[FontVariation]":
        """Ordered list of ``a:fontVariations/a:fontVariation`` entries.

        Some DrawingML themes (notably pandemic-era Office builds and
        Microsoft 365 themes) include an ``a:fontVariations`` child of
        ``a:themeElements`` declaring alternate typeface pairings. Each
        entry is exposed as a :class:`FontVariation` carrying the
        variation's ``@name`` plus its major / minor latin typefaces.

        Returns ``[]`` when the theme has no ``a:fontVariations`` child
        (the common case — Visio's default theme uses a
        ``vt:fontStylesGroup`` extension element instead).

        .. versionadded:: 0.4.0
        """
        theme = self._theme_part.theme_element
        elements = theme.find(_qn("a:themeElements"))
        if elements is None:
            return []
        variations = elements.find(_qn("a:fontVariations"))
        if variations is None:
            return []
        out: "List[FontVariation]" = []
        for fv in variations.findall(_qn("a:fontVariation")):
            major_latin = _find_latin_typeface(fv, "a:majorFont")
            minor_latin = _find_latin_typeface(fv, "a:minorFont")
            name = fv.get("name")
            out.append(
                FontVariation(
                    name=None if name is None else str(name),
                    major_latin_typeface=major_latin,
                    minor_latin_typeface=minor_latin,
                )
            )
        return out

    def _fmt_scheme(self) -> Optional[Any]:
        """Return the ``<a:fmtScheme>`` element, or ``None`` if absent."""
        theme = self._theme_part.theme_element
        elements = theme.find(_qn("a:themeElements"))
        if elements is None:
            return None
        return elements.find(_qn("a:fmtScheme"))

    @property
    def color_scheme_name(self) -> Optional[str]:
        """The ``<a:clrScheme>@name`` attribute, or ``None`` if absent.

        .. versionadded:: 0.1.0
        """
        clr_scheme = self._theme_part.color_scheme()
        if clr_scheme is None:
            return None
        value = clr_scheme.get("name")
        return None if value is None else str(value)

    def color(self, slot: str) -> Optional[str]:
        """Return the hex RGB value of colour-scheme slot `slot`.

        `slot` is one of ``dk1``, ``lt1``, ``dk2``, ``lt2``,
        ``accent1``–``accent6``, ``hlink``, ``folHlink``. The function
        walks to ``a:clrScheme/a:<slot>/a:srgbClr@val`` and returns
        the six-hex-digit string (no ``#`` prefix).

        Returns ``None`` when:

        - the theme has no colour scheme;
        - the slot is missing;
        - the slot wraps an ``a:sysClr`` or ``a:schemeClr`` instead of
          an ``a:srgbClr`` — ``sysClr`` values are theme-dependent at
          display time; use :meth:`color_slot` to inspect the raw
          child when that matters.

        .. versionadded:: 0.1.0
        """
        self._validate_slot(slot)
        clr_scheme = self._theme_part.color_scheme()
        if clr_scheme is None:
            return None
        slot_element = clr_scheme.find(_qn(f"a:{slot}"))
        if slot_element is None:
            return None
        srgb = slot_element.find(_qn("a:srgbClr"))
        if srgb is None:
            return None
        value = srgb.get("val")
        return None if value is None else str(value)

    def set_color(self, slot: str, rgb: str) -> None:
        """Set colour-scheme slot `slot` to the six-hex-digit `rgb` value.

        Replaces any existing ``a:srgbClr`` / ``a:sysClr`` /
        ``a:schemeClr`` child of the slot element with a fresh
        ``<a:srgbClr val="<rgb>"/>``. Raises:

        - :class:`ValueError` if `slot` is not a canonical slot name;
        - :class:`ValueError` if `rgb` isn't a 6-hex-digit string;
        - :class:`ValueError` if the theme has no colour scheme (the
          seed-template always includes one; surfaces bad inputs).

        .. versionadded:: 0.1.0
        """
        self._validate_slot(slot)
        normalised = self._normalise_rgb(rgb)

        clr_scheme = self._theme_part.color_scheme()
        if clr_scheme is None:
            raise ValueError(
                "theme has no <a:clrScheme>; set_color requires a "
                "seeded colour scheme"
            )
        slot_element = clr_scheme.find(_qn(f"a:{slot}"))
        if slot_element is None:
            raise ValueError(
                f"theme's colour scheme has no <a:{slot}> slot"
            )
        for existing in list(slot_element):
            slot_element.remove(existing)
        from lxml import etree

        srgb = etree.SubElement(
            slot_element, _qn("a:srgbClr")
        )
        srgb.set("val", normalised)

    def color_slot(self, slot: str) -> Optional[object]:
        """Return the raw lxml element of colour slot `slot`, or ``None``.

        Escape hatch for callers that need to read or write
        ``a:sysClr`` / ``a:schemeClr`` children directly rather than
        only the ``a:srgbClr`` case :meth:`color` handles.

        .. versionadded:: 0.1.0
        """
        self._validate_slot(slot)
        clr_scheme = self._theme_part.color_scheme()
        if clr_scheme is None:
            return None
        return clr_scheme.find(_qn(f"a:{slot}"))

    # -- font scheme --------------------------------------------------

    @property
    def font_scheme_name(self) -> Optional[str]:
        """The ``<a:fontScheme>@name`` attribute, or ``None`` if absent.

        .. versionadded:: 0.1.0
        """
        font_scheme = self._theme_part.font_scheme()
        if font_scheme is None:
            return None
        value = font_scheme.get("name")
        return None if value is None else str(value)

    @property
    def major_latin_typeface(self) -> Optional[str]:
        """Major (headings) latin typeface from ``a:majorFont/a:latin``.

        Returns the ``@typeface`` attribute, or ``None`` when the theme
        has no font scheme / no major font / no latin child.

        .. versionadded:: 0.1.0
        """
        return self._latin_typeface("a:majorFont")

    @property
    def minor_latin_typeface(self) -> Optional[str]:
        """Minor (body) latin typeface from ``a:minorFont/a:latin``.

        Returns the ``@typeface`` attribute, or ``None`` when the theme
        has no font scheme / no minor font / no latin child.

        .. versionadded:: 0.1.0
        """
        return self._latin_typeface("a:minorFont")

    def set_major_latin_typeface(self, typeface: str) -> None:
        """Replace ``a:majorFont/a:latin@typeface`` with `typeface`.

        Creates the ``<a:latin>`` element if missing. Raises
        :class:`ValueError` when the theme has no font scheme or no
        major-font child.

        .. versionadded:: 0.1.0
        """
        self._set_latin_typeface("a:majorFont", typeface)

    def set_minor_latin_typeface(self, typeface: str) -> None:
        """Replace ``a:minorFont/a:latin@typeface`` with `typeface`.

        Creates the ``<a:latin>`` element if missing. Raises
        :class:`ValueError` when the theme has no font scheme or no
        minor-font child.

        .. versionadded:: 0.1.0
        """
        self._set_latin_typeface("a:minorFont", typeface)

    # -- helpers ------------------------------------------------------

    def _latin_typeface(self, font_nsptag: str) -> Optional[str]:
        font_scheme = self._theme_part.font_scheme()
        if font_scheme is None:
            return None
        font = font_scheme.find(_qn(font_nsptag))
        if font is None:
            return None
        latin = font.find(_qn("a:latin"))
        if latin is None:
            return None
        value = latin.get("typeface")
        return None if value is None else str(value)

    def _set_latin_typeface(self, font_nsptag: str, typeface: str) -> None:
        if not typeface:
            raise ValueError("typeface must be a non-empty string")
        font_scheme = self._theme_part.font_scheme()
        if font_scheme is None:
            raise ValueError(
                "theme has no <a:fontScheme>; set_*_latin_typeface "
                "requires a seeded font scheme"
            )
        font = font_scheme.find(_qn(font_nsptag))
        if font is None:
            raise ValueError(
                f"theme's font scheme has no <{font_nsptag}> child"
            )
        latin = font.find(_qn("a:latin"))
        if latin is None:
            from lxml import etree

            latin = etree.SubElement(font, _qn("a:latin"))
        latin.set("typeface", typeface)

    @classmethod
    def _validate_slot(cls, slot: str) -> None:
        if slot not in cls._SCHEME_SLOTS:
            raise ValueError(
                f"unknown colour-scheme slot {slot!r}; "
                f"expected one of {cls._SCHEME_SLOTS}"
            )

    @staticmethod
    def _normalise_rgb(rgb: str) -> str:
        """Return a canonical 6-hex-digit (uppercase) representation of `rgb`."""
        if not isinstance(rgb, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(f"rgb must be a string, got {type(rgb).__name__}")
        value = rgb.lstrip("#")
        if len(value) != 6:
            raise ValueError(
                f"rgb must be 6 hex digits, got {rgb!r}"
            )
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError(f"rgb must be 6 hex digits, got {rgb!r}") from exc
        return value.upper()


class ColorScheme:
    """Dotted-attribute proxy over an ``<a:clrScheme>`` element.

    Exposes the twelve canonical DrawingML colour slots as properties:
    ``dk1``, ``lt1``, ``dk2``, ``lt2``, ``accent1``-``accent6``,
    ``hlink``, ``folHlink``. Each property returns:

    - the six-hex-digit ``@val`` string (uppercase) when the slot
      wraps an ``<a:srgbClr>``;
    - the raw ``@val`` (e.g. ``"windowText"``) when the slot wraps an
      ``<a:sysClr>`` — Office's Office theme uses this for ``dk1`` /
      ``lt1``;
    - ``None`` when the slot is missing or wraps a ``<a:schemeClr>``
      (self-referential and semantically empty in a theme context).

    :attr:`name` surfaces the ``@name`` attribute of the scheme
    element. Obtained via :attr:`Theme.color_scheme`.

    .. versionadded:: 0.3.0
    """

    def __init__(self, theme_part: ThemePart, element) -> None:  # type: ignore[no-untyped-def]
        self._theme_part = theme_part
        self._element = element

    @property
    def name(self) -> Optional[str]:
        """The ``<a:clrScheme>@name`` attribute, or ``None`` if unset."""
        value = self._element.get("name")
        return None if value is None else str(value)

    def _slot_value(self, slot: str) -> Optional[str]:
        """Return the RGB-hex or sysClr name for slot `slot`, or ``None``."""
        slot_el = self._element.find(_qn(f"a:{slot}"))
        if slot_el is None:
            return None
        srgb = slot_el.find(_qn("a:srgbClr"))
        if srgb is not None:
            val = srgb.get("val")
            return None if val is None else str(val).upper()
        sysclr = slot_el.find(_qn("a:sysClr"))
        if sysclr is not None:
            val = sysclr.get("val")
            return None if val is None else str(val)
        return None

    @property
    def dk1(self) -> Optional[str]:
        return self._slot_value("dk1")

    @property
    def lt1(self) -> Optional[str]:
        return self._slot_value("lt1")

    @property
    def dk2(self) -> Optional[str]:
        return self._slot_value("dk2")

    @property
    def lt2(self) -> Optional[str]:
        return self._slot_value("lt2")

    @property
    def accent1(self) -> Optional[str]:
        return self._slot_value("accent1")

    @property
    def accent2(self) -> Optional[str]:
        return self._slot_value("accent2")

    @property
    def accent3(self) -> Optional[str]:
        return self._slot_value("accent3")

    @property
    def accent4(self) -> Optional[str]:
        return self._slot_value("accent4")

    @property
    def accent5(self) -> Optional[str]:
        return self._slot_value("accent5")

    @property
    def accent6(self) -> Optional[str]:
        return self._slot_value("accent6")

    @property
    def hlink(self) -> Optional[str]:
        return self._slot_value("hlink")

    @property
    def folHlink(self) -> Optional[str]:
        return self._slot_value("folHlink")


class _ThemeFont:
    """Proxy over ``<a:majorFont>`` or ``<a:minorFont>``.

    Exposes :attr:`latin_typeface` over ``a:latin@typeface``.

    .. versionadded:: 0.3.0
    """

    def __init__(self, element) -> None:  # type: ignore[no-untyped-def]
        self._element = element

    @property
    def latin_typeface(self) -> Optional[str]:
        """The ``a:latin@typeface``, or ``None`` when absent."""
        latin = self._element.find(_qn("a:latin"))
        if latin is None:
            return None
        value = latin.get("typeface")
        return None if value is None else str(value)


class FontScheme:
    """Dotted-attribute proxy over an ``<a:fontScheme>`` element.

    Exposes :attr:`major_font` and :attr:`minor_font` as
    :class:`_ThemeFont` proxies with ``.latin_typeface`` access.
    :attr:`name` returns the scheme's ``@name`` attribute.

    .. versionadded:: 0.3.0
    """

    def __init__(self, theme_part: ThemePart, element) -> None:  # type: ignore[no-untyped-def]
        self._theme_part = theme_part
        self._element = element

    @property
    def name(self) -> Optional[str]:
        """The ``<a:fontScheme>@name`` attribute, or ``None`` if unset."""
        value = self._element.get("name")
        return None if value is None else str(value)

    @property
    def major_font(self) -> Optional[_ThemeFont]:
        """The :class:`_ThemeFont` proxy over ``<a:majorFont>``, or ``None``."""
        mf = self._element.find(_qn("a:majorFont"))
        if mf is None:
            return None
        return _ThemeFont(mf)

    @property
    def minor_font(self) -> Optional[_ThemeFont]:
        """The :class:`_ThemeFont` proxy over ``<a:minorFont>``, or ``None``."""
        mf = self._element.find(_qn("a:minorFont"))
        if mf is None:
            return None
        return _ThemeFont(mf)


# -- effect variants + font variations ----------------------------------


@dataclass(frozen=True)
class ShadowParams:
    """Typed view of an ``a:outerShdw`` / ``a:innerShdw`` element.

    Fields mirror the DrawingML attributes:

    - :attr:`blur_rad` — ``@blurRad`` in EMUs (92 900 per inch), or
      ``None`` when the attribute is omitted.
    - :attr:`dist` — ``@dist`` in EMUs.
    - :attr:`direction` — ``@dir`` in sixty-thousandths of a degree
      (``0`` means "rightward"; the DrawingML spec measures clockwise
      from east).
    - :attr:`color` — six-hex-digit RGB string pulled from a nested
      ``a:srgbClr@val``; ``None`` when the shadow wraps an
      ``a:schemeClr`` / ``a:sysClr`` / ``a:prstClr`` that doesn't
      resolve to a literal.

    All fields are optional — DrawingML allows shadow elements to
    inherit attributes from their parent style, so a sparsely-populated
    shadow is schema-valid.

    .. versionadded:: 0.4.0
    """

    blur_rad: Optional[int] = None
    dist: Optional[int] = None
    direction: Optional[int] = None
    color: Optional[str] = None


@dataclass(frozen=True)
class EffectVariant:
    """A single variant in ``a:fmtScheme/a:effectStyleLst``.

    Exposed as read-only dataclass entries (``name``, ``preset_num``,
    plus the underlying element via ``_element``). Typed shadow
    accessors :attr:`shadow_outer_params` / :attr:`shadow_inner_params`
    return :class:`ShadowParams` for the first ``a:outerShdw`` /
    ``a:innerShdw`` descendant, or ``None`` when absent.

    :attr:`name` is the canonical DrawingML preset name — ``"subtle"``,
    ``"moderate"``, or ``"intense"`` — derived from the variant's
    1-based position in the effect-style list.

    .. versionadded:: 0.4.0
    """

    name: str
    preset_num: int
    _element: Any = None

    @property
    def shadow_outer_params(self) -> Optional[ShadowParams]:
        """Typed view of the first ``a:outerShdw`` descendant.

        Walks the variant's ``a:effectLst`` (and any
        ``a:effectDag`` wrappers) to find the first outer shadow
        element and returns a :class:`ShadowParams` snapshot of its
        ``@blurRad`` / ``@dist`` / ``@dir`` / colour children.

        Returns ``None`` when the variant has no outer shadow.
        """
        return _shadow_params(self._element, "a:outerShdw")

    @property
    def shadow_inner_params(self) -> Optional[ShadowParams]:
        """Typed view of the first ``a:innerShdw`` descendant.

        Counterpart to :attr:`shadow_outer_params`; returns ``None``
        when the variant has no inner shadow.
        """
        return _shadow_params(self._element, "a:innerShdw")


@dataclass(frozen=True)
class FontVariation:
    """A single entry in ``a:themeElements/a:fontVariations``.

    :attr:`name` — the variation's ``@name`` attribute, or ``None`` if
    unset.

    :attr:`major_latin_typeface` / :attr:`minor_latin_typeface` — the
    ``@typeface`` of the variation's ``a:majorFont/a:latin`` and
    ``a:minorFont/a:latin`` children; ``None`` when either is missing.

    .. versionadded:: 0.4.0
    """

    name: Optional[str] = None
    major_latin_typeface: Optional[str] = None
    minor_latin_typeface: Optional[str] = None


def _find_latin_typeface(parent: Any, font_nsptag: str) -> Optional[str]:
    """Return ``<parent>/<font_nsptag>/a:latin@typeface`` or ``None``."""
    font = parent.find(_qn(font_nsptag))
    if font is None:
        return None
    latin = font.find(_qn("a:latin"))
    if latin is None:
        return None
    value = latin.get("typeface")
    return None if value is None else str(value)


def _shadow_params(
    effect_style: Any, shadow_nsptag: str
) -> Optional[ShadowParams]:
    """Return :class:`ShadowParams` for the first `shadow_nsptag` descendant."""
    if effect_style is None:
        return None
    shadow = _first_descendant(effect_style, shadow_nsptag)
    if shadow is None:
        return None
    blur = _int_attr(shadow.get("blurRad"))
    dist = _int_attr(shadow.get("dist"))
    direction = _int_attr(shadow.get("dir"))
    color = None
    srgb = shadow.find(_qn("a:srgbClr"))
    if srgb is not None:
        val = srgb.get("val")
        if val is not None:
            color = str(val).upper()
    return ShadowParams(
        blur_rad=blur, dist=dist, direction=direction, color=color
    )


def _first_descendant(node: Any, nsptag: str) -> Optional[Any]:
    """Breadth-first search for a single descendant with tag `nsptag`."""
    qn = _qn(nsptag)
    # iter() includes node itself — skip that case.
    for child in node.iter(qn):
        if child is not node:
            return child
    return None


def _int_attr(value: Optional[str]) -> Optional[int]:
    """Return ``int(value)`` or ``None`` when `value` is ``None``/invalid."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
