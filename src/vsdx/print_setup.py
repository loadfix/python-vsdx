"""``PrintSetup`` proxy — page-scope print settings.

Visio exposes a page's print-time parameters as a family of singleton
cells on that page's ``<PageSheet>``:

* ``<Cell N="PrintPageOrientation" V="0|1|2">`` — same-as-printer /
  portrait / landscape.
* ``<Cell N="PaperKind" V="…">`` — integer paper enum. Values match
  the Windows ``DEVMODE.dmPaperSize`` table (1 = Letter, 9 = A4,
  256 = custom / page-matches-drawing, …).
* ``<Cell N="PageTopMargin" V="…" U="IN">`` — top margin, inches.
* ``<Cell N="PageBottomMargin" V="…" U="IN">`` — bottom margin.
* ``<Cell N="PageLeftMargin" V="…" U="IN">`` — left margin.
* ``<Cell N="PageRightMargin" V="…" U="IN">`` — right margin.
* ``<Cell N="CenterX" V="0|1">`` — whether the drawing is centred
  horizontally on the sheet.
* ``<Cell N="CenterY" V="0|1">`` — whether the drawing is centred
  vertically on the sheet.
* ``<Cell N="ScaleX" V="…">`` / ``<Cell N="ScaleY" V="…">`` — print
  tile-scale multipliers (``1`` = fit-to-one-sheet, ``0.5`` = scale
  the drawing to half, …). Exposed here as a single :attr:`tile_scale`
  accessor because Visio UI surfaces one scalar that updates both.

Design notes (same playbook as R4-12 / R8-3 / R8-4 / R8-17):

- **Zero new ``CT_*`` classes.** The settings ride on the existing
  :class:`~vsdx.oxml.cell.CT_Cell` direct-child slot on
  :class:`~vsdx.oxml.page.CT_PageSheet`. Discrimination is value-level
  (``cell.@N == "PrintPageOrientation"`` / …), not class-level.
- The :class:`PrintSetup` proxy is a thin live view — it does not
  cache. Every accessor walks the current ``<PageSheet>``'s
  ``<Cell>`` children, so concurrent edits via the oxml layer stay
  consistent.
- Cell materialisation is **lazy on write**. Reading an absent cell
  returns ``None`` (or the schema default for booleans); writing
  materialises ``<PageSheet>`` and the specific ``<Cell>`` only then.
  This preserves byte-identity on packages whose print-setup is
  entirely default.
- Unit hints (``U="IN"``) are emitted on margin cells on write so
  Visio desktop rehydrates them in inches regardless of the package
  locale.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_PageSheet  # TODO(vsdx/track-1)
    from vsdx.page import Page


__all__ = [
    "PRINT_ORIENTATION",
    "PrintSetup",
]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PRINT_ORIENTATION(str, Enum):
    """Enumeration of print-orientation codes (``<Cell N="PrintPageOrientation">``).

    Values mirror the ``visPrintOrient`` VBA enum: ``0`` = same as
    printer's current setting, ``1`` = portrait, ``2`` = landscape.
    Carried as a ``str`` subclass so the raw ``@V`` round-trips
    verbatim through the XML attribute and callers can compare
    ``page.print_setup.orientation == "1"`` or
    ``page.print_setup.orientation == PRINT_ORIENTATION.PORTRAIT``.

    .. versionadded:: 0.3.0
    """

    #: Use the printer driver's current orientation setting
    #: (``<Cell N="PrintPageOrientation" V="0">``).
    SAME_AS_PRINTER = "0"
    #: Portrait orientation (``<Cell N="PrintPageOrientation" V="1">``).
    PORTRAIT = "1"
    #: Landscape orientation (``<Cell N="PrintPageOrientation" V="2">``).
    LANDSCAPE = "2"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


# ---------------------------------------------------------------------------
# Cell-level helpers — direct <Cell N=name> children of <PageSheet>
# ---------------------------------------------------------------------------


def _sheet_cell(sheet: "CT_PageSheet", name: str) -> Optional["CT_Cell"]:
    """Return the ``<Cell N=name>`` direct child of *sheet*, or ``None``."""
    if sheet is None:
        return None
    for cell in sheet.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _sheet_cell_v(sheet: "CT_PageSheet", name: str) -> Optional[str]:
    """Return the ``@V`` on the ``<Cell N=name>`` direct child of *sheet*."""
    cell = _sheet_cell(sheet, name)
    if cell is None:
        return None
    return cell.get("V")


def _get_or_add_sheet_cell(
    sheet: "CT_PageSheet", name: str
) -> "CT_Cell":
    """Return the ``<Cell N=name>`` on *sheet*, creating one if absent."""
    cell = _sheet_cell(sheet, name)
    if cell is not None:
        return cell
    cell = sheet._add_cell()
    cell.set("N", name)
    return cell


def _set_sheet_cell_v(
    sheet: "CT_PageSheet",
    name: str,
    value: Optional[str],
    unit: Optional[str] = None,
) -> None:
    """Create-or-update ``<Cell N=name V=value [U=unit]>`` on *sheet*.

    Passing ``None`` for *value* removes the cell entirely — this
    matches the clearing-semantics callers expect from assignment-to-
    ``None`` on the typed wrappers.
    """
    cell = _sheet_cell(sheet, name)
    if value is None:
        if cell is not None:
            sheet.remove(cell)
        return
    if cell is None:
        cell = sheet._add_cell()
        cell.set("N", name)
    cell.set("V", value)
    if unit is not None:
        cell.set("U", unit)


def _parse_bool(raw: Optional[str]) -> bool:
    """Coerce a Visio boolean ``@V`` to Python ``bool``."""
    if raw is None:
        return False
    token = raw.strip().lower()
    return token in ("1", "true", "yes", "-1")


def _fmt_number(value: float) -> str:
    """Format a float the way Visio emits it — integers lose .0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return str(int(f))
    return ("%f" % f).rstrip("0").rstrip(".")


def _parse_float(raw: Optional[str]) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        try:
            return int(float(raw))
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# PrintSetup — page-scope print configuration
# ---------------------------------------------------------------------------


class PrintSetup:
    """Page-scope print settings proxy.

    Live view over the print-related cells on a page's
    ``<PageSheet>``. Accessed via :attr:`~vsdx.page.Page.print_setup`.

    All accessors read directly from the underlying
    ``<PageSheet>``; writes materialise the page sheet (if absent)
    and the specific cell (if absent) lazily. Setting any property
    to ``None`` removes the cell, letting Visio fall back to its
    schema default on next open.

    .. versionadded:: 0.3.0
    """

    def __init__(self, page: "Page") -> None:
        self._page = page

    # -- sheet access ---------------------------------------------------

    def _sheet(self) -> Optional["CT_PageSheet"]:
        """Return the page's ``<PageSheet>``, or ``None`` if absent."""
        return self._page._element.pageSheet

    def _get_or_add_sheet(self) -> "CT_PageSheet":
        return self._page._element.get_or_add_pageSheet()

    # -- orientation ----------------------------------------------------

    @property
    def orientation(self) -> Optional[PRINT_ORIENTATION]:
        """The print orientation (``<Cell N="PrintPageOrientation">``).

        Returns a :class:`PRINT_ORIENTATION` member when set, or
        ``None`` when the cell is absent. Unknown raw values
        (outside ``"0"``/``"1"``/``"2"``) also return ``None`` to
        preserve the load-preserve-save invariant — the cell is not
        rewritten on read.
        """
        raw = _sheet_cell_v(self._sheet(), "PrintPageOrientation")
        if raw is None:
            return None
        try:
            return PRINT_ORIENTATION(raw)
        except ValueError:
            return None

    @orientation.setter
    def orientation(self, value: Optional[object]) -> None:
        if value is None:
            sheet = self._sheet()
            if sheet is not None:
                _set_sheet_cell_v(sheet, "PrintPageOrientation", None)
            return
        # Accept enum, raw string, or integer code.
        if isinstance(value, PRINT_ORIENTATION):
            raw = value.value
        elif isinstance(value, int) and not isinstance(value, bool):
            raw = str(value)
            # Validate on authoring — bad codes raise.
            PRINT_ORIENTATION(raw)
        else:
            raw = str(value)
            PRINT_ORIENTATION(raw)
        _set_sheet_cell_v(self._get_or_add_sheet(), "PrintPageOrientation", raw)

    # -- paper ----------------------------------------------------------

    @property
    def paper_size(self) -> Optional[int]:
        """The paper-size enum (``<Cell N="PaperKind">``) as an :class:`int`.

        Values match the Windows ``DEVMODE.dmPaperSize`` table —
        ``1`` = Letter, ``9`` = A4, ``256`` = custom / page-matches-
        drawing, etc. Returns ``None`` when the cell is absent.
        """
        return _parse_int(_sheet_cell_v(self._sheet(), "PaperKind"))

    @paper_size.setter
    def paper_size(self, value: Optional[int]) -> None:
        if value is None:
            sheet = self._sheet()
            if sheet is not None:
                _set_sheet_cell_v(sheet, "PaperKind", None)
            return
        _set_sheet_cell_v(
            self._get_or_add_sheet(), "PaperKind", str(int(value))
        )

    # -- margins --------------------------------------------------------

    def _margin_get(self, cell_name: str) -> Optional[float]:
        return _parse_float(_sheet_cell_v(self._sheet(), cell_name))

    def _margin_set(self, cell_name: str, value: Optional[float]) -> None:
        if value is None:
            sheet = self._sheet()
            if sheet is not None:
                _set_sheet_cell_v(sheet, cell_name, None)
            return
        _set_sheet_cell_v(
            self._get_or_add_sheet(),
            cell_name,
            _fmt_number(float(value)),
            unit="IN",
        )

    @property
    def margin_top(self) -> Optional[float]:
        """Top margin, inches (``<Cell N="PageTopMargin" U="IN">``)."""
        return self._margin_get("PageTopMargin")

    @margin_top.setter
    def margin_top(self, value: Optional[float]) -> None:
        self._margin_set("PageTopMargin", value)

    @property
    def margin_bottom(self) -> Optional[float]:
        """Bottom margin, inches (``<Cell N="PageBottomMargin" U="IN">``)."""
        return self._margin_get("PageBottomMargin")

    @margin_bottom.setter
    def margin_bottom(self, value: Optional[float]) -> None:
        self._margin_set("PageBottomMargin", value)

    @property
    def margin_left(self) -> Optional[float]:
        """Left margin, inches (``<Cell N="PageLeftMargin" U="IN">``)."""
        return self._margin_get("PageLeftMargin")

    @margin_left.setter
    def margin_left(self, value: Optional[float]) -> None:
        self._margin_set("PageLeftMargin", value)

    @property
    def margin_right(self) -> Optional[float]:
        """Right margin, inches (``<Cell N="PageRightMargin" U="IN">``)."""
        return self._margin_get("PageRightMargin")

    @margin_right.setter
    def margin_right(self, value: Optional[float]) -> None:
        self._margin_set("PageRightMargin", value)

    # -- centering ------------------------------------------------------

    @property
    def centered_x(self) -> bool:
        """Whether the drawing prints centred horizontally (``<Cell N="CenterX">``)."""
        return _parse_bool(_sheet_cell_v(self._sheet(), "CenterX"))

    @centered_x.setter
    def centered_x(self, value: bool) -> None:
        _set_sheet_cell_v(
            self._get_or_add_sheet(),
            "CenterX",
            "1" if bool(value) else "0",
        )

    @property
    def centered_y(self) -> bool:
        """Whether the drawing prints centred vertically (``<Cell N="CenterY">``)."""
        return _parse_bool(_sheet_cell_v(self._sheet(), "CenterY"))

    @centered_y.setter
    def centered_y(self, value: bool) -> None:
        _set_sheet_cell_v(
            self._get_or_add_sheet(),
            "CenterY",
            "1" if bool(value) else "0",
        )

    # -- tile scale -----------------------------------------------------

    @property
    def tile_scale(self) -> Optional[float]:
        """Print tile scale — ``1.0`` = fit-to-one-sheet, ``0.5`` = half, etc.

        Reads from ``<Cell N="ScaleX">`` (Visio emits ``ScaleX`` and
        ``ScaleY`` in lockstep; UI exposes one scalar). Returns
        ``None`` when the cell is absent.

        The setter writes **both** ``ScaleX`` and ``ScaleY`` to keep
        the sheet self-consistent with Visio's UI behaviour.
        """
        return _parse_float(_sheet_cell_v(self._sheet(), "ScaleX"))

    @tile_scale.setter
    def tile_scale(self, value: Optional[float]) -> None:
        if value is None:
            sheet = self._sheet()
            if sheet is not None:
                _set_sheet_cell_v(sheet, "ScaleX", None)
                _set_sheet_cell_v(sheet, "ScaleY", None)
            return
        sheet = self._get_or_add_sheet()
        raw = _fmt_number(float(value))
        _set_sheet_cell_v(sheet, "ScaleX", raw)
        _set_sheet_cell_v(sheet, "ScaleY", raw)

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        parts = [
            f"orientation={self.orientation!r}",
            f"paper_size={self.paper_size!r}",
        ]
        return f"<PrintSetup {' '.join(parts)}>"
