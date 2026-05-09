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

from typing import TYPE_CHECKING, Optional

from vsdx.parts.theme import ThemePart

if TYPE_CHECKING:
    pass


__all__ = ["ColorScheme", "FontScheme", "Theme"]


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
