"""``Geometry`` + geometry-row proxies — custom shape paths.

Visio defines a shape's outline via one or more
``<Section N="Geometry" IX="N">`` sections on its ``<Shape>`` element.
Each section is a *path* — a sequence of typed ``<Row T="...">``
elements ("geometry operators" in Microsoft Learn's terminology) that
together trace the path. A single shape may carry several Geometry
sections to encode compound outlines (fill path + stroke cut-path +
alternate shading contour, etc.) — they are discriminated by the
section's ``@IX`` ordinal.

This module implements the 0.3.0 custom-geometry authoring surface
(track R4-12 of the 0.3.0 fan-out):

* :class:`Geometry` — collection wrapper around one
  ``<Section N="Geometry">``. A shape's ``.geometries`` attribute yields
  one per section; ``.geometry`` is a convenience alias for the first.
* :class:`Geometries` — iterable collection of per-shape
  :class:`Geometry` sections, with ``.add()`` to materialise a new one.
* :class:`GeometryRow` — base class for every typed row proxy. Exposes
  ``.row_type`` (the ``@T`` discriminator), ``.ix``, and row-global
  helpers. Subclasses add typed cell accessors.
* :class:`MoveTo`, :class:`LineTo`, :class:`ArcTo`,
  :class:`EllipticalArcTo`, :class:`NURBSTo`, :class:`PolylineTo`,
  :class:`SplineStart`, :class:`SplineKnot`, :class:`InfiniteLine`,
  :class:`Ellipse`, :class:`RelMoveTo`, :class:`RelLineTo`,
  :class:`RelCubBezTo`, :class:`RelQuadBezTo`,
  :class:`RelEllipticalArcTo` — concrete row-type proxies.

Design notes (matches the 0.2.0 layers playbook):

- *Zero new ``CT_*`` classes*. Geometry rides on
  :class:`~vsdx.oxml.section.CT_Section` / :class:`~vsdx.oxml.row.CT_Row`
  / :class:`~vsdx.oxml.cell.CT_Cell`; the discriminator is value-level
  (``section.name_ == "Geometry"`` and ``row.t == "LineTo"``), not
  class-level.
- Builder methods (:meth:`Geometry.move_to`, ``.line_to``, ``.arc_to``,
  …) return the newly minted row proxy so callers can chain through
  formula overrides / cell tweaks:
  ``geo.line_to(1, 0).x_formula = "Width*1"``.
- Row-level ``@IX`` is monotonic starting at 1 — Visio desktop emits
  ``IX="1"`` for the first row (not zero); we match that behaviour.
- :attr:`Geometry.rows` returns typed proxies (a :class:`LineTo` for
  ``T="LineTo"``, etc.) with a generic :class:`UnknownGeometryRow`
  fallback for row types this module hasn't specialised — never
  silently drops rows on parse.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, List, Optional, Type

from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_Row, CT_Section  # TODO(vsdx/track-1)
    from vsdx.shapes.base import Shape


__all__ = [
    "ArcTo",
    "Ellipse",
    "EllipticalArcTo",
    "Geometries",
    "Geometry",
    "GeometryRow",
    "InfiniteLine",
    "LineTo",
    "MoveTo",
    "NURBSTo",
    "PolylineTo",
    "RelCubBezTo",
    "RelEllipticalArcTo",
    "RelLineTo",
    "RelMoveTo",
    "RelQuadBezTo",
    "SplineKnot",
    "SplineStart",
    "UnknownGeometryRow",
]


_GEOMETRY_SECTION_NAME = "Geometry"


# ---------------------------------------------------------------------------
# Cell-level helpers — copied from layers.py so the geometry module stays
# importable without leaning on layers internals.
# ---------------------------------------------------------------------------


def _row_cell(row: "CT_Row", name: str) -> Optional["CT_Cell"]:
    """Return the ``<Cell N=name>`` child on *row*, or ``None``."""
    for cell in row.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _get_or_add_row_cell(row: "CT_Row", name: str) -> "CT_Cell":
    """Return the ``<Cell N=name>`` on *row*, creating it if absent."""
    cell = _row_cell(row, name)
    if cell is not None:
        return cell
    cell = row._add_cell()
    cell.set("N", name)
    return cell


def _cell_float(row: "CT_Row", name: str) -> Optional[float]:
    """Float-cast the ``@V`` of ``<Cell N=name>``, or ``None`` if absent."""
    cell = _row_cell(row, name)
    if cell is None:
        return None
    v = cell.get("V")
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _set_cell_float(
    row: "CT_Row", name: str, value: Optional[float], unit: Optional[str] = None
) -> None:
    """Create-or-update ``<Cell N=name V=value U=unit>`` on *row*.

    Passing *value* as ``None`` clears both ``@V`` and ``@U`` (but leaves
    the cell element in place — Visio tolerates cells with no value and
    round-trip fidelity rewards us for not deleting them).
    """
    cell = _get_or_add_row_cell(row, name)
    if value is None:
        cell.attrib.pop("V", None)
        cell.attrib.pop("U", None)
        return
    cell.set("V", _fmt_num(float(value)))
    if unit is not None:
        cell.set("U", unit)


def _fmt_num(v: float) -> str:
    """Format a float the way Visio emits it — trim trailing zeros."""
    if v == int(v):
        return str(int(v))
    return ("%f" % v).rstrip("0").rstrip(".")


def _cell_bool(shape_or_section: Any, name: str) -> bool:
    """``<Cell V="1">`` child of *shape_or_section* → ``True`` / else ``False``."""
    for cell in shape_or_section.cell_lst:
        if cell.get("N") == name:
            return (cell.get("V") or "") == "1"
    return False


def _set_section_bool_cell(section: "CT_Section", name: str, value: bool) -> None:
    """Create-or-update a boolean flag cell on *section*."""
    for cell in section.cell_lst:
        if cell.get("N") == name:
            cell.set("V", "1" if value else "0")
            return
    cell = section._add_cell()
    cell.set("N", name)
    cell.set("V", "1" if value else "0")


# ---------------------------------------------------------------------------
# Geometry-row proxies
# ---------------------------------------------------------------------------


class GeometryRow:
    """Base class for every geometry-row proxy.

    Subclasses expose typed cell accessors matching the Visio
    ``Row_Type`` documentation (``X`` / ``Y`` / ``A`` / ``B`` / ``C`` /
    ``D`` / ``E``). The ``@T`` discriminator is fixed by each subclass
    via the ``ROW_TYPE`` class attribute.

    Construct indirectly via :class:`Geometry` — callers do not
    instantiate row proxies directly.

    .. versionadded:: 0.3.0
    """

    #: Visio ``Row/@T`` discriminator for this row class. Overridden per
    #: subclass; ``""`` on the base class (used by
    #: :class:`UnknownGeometryRow` which reads the value dynamically).
    ROW_TYPE: str = ""

    def __init__(self, row: "CT_Row", geometry: "Geometry") -> None:
        self._row = row
        self._geometry = geometry

    # -- identity -------------------------------------------------------

    @property
    def row_type(self) -> str:
        """The row's ``@T`` discriminator (``"LineTo"`` / ``"MoveTo"`` / …)."""
        return self._row.get("T") or self.ROW_TYPE

    @property
    def ix(self) -> int:
        """The row's ordinal ``@IX`` (1-based in Visio)."""
        v = self._row.get("IX")
        return int(v) if v is not None else 0

    @property
    def element(self) -> "CT_Row":
        """The underlying ``<Row>`` element (escape hatch)."""
        return self._row

    # -- typed X / Y accessors ------------------------------------------
    # X and Y appear on every geometry row type in the Visio vocabulary.
    # Expose them on the base class so callers can iterate a path
    # uniformly without upcasting.

    @property
    def x(self) -> Optional[float]:
        """The row's ``<Cell N="X">`` value as a float."""
        return _cell_float(self._row, "X")

    @x.setter
    def x(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "X", value, "IN")

    @property
    def y(self) -> Optional[float]:
        """The row's ``<Cell N="Y">`` value as a float."""
        return _cell_float(self._row, "Y")

    @y.setter
    def y(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "Y", value, "IN")

    # -- formula escape hatches -----------------------------------------
    # Real Visio files pepper ``@F`` all over geometry rows (``Width*0``,
    # ``Geometry1.X1``, etc.). Expose getter/setter for formula strings
    # on the common cells without interpreting them.

    def set_formula(self, cell_name: str, formula: Optional[str]) -> None:
        """Write ``<Cell N=cell_name F=formula>`` on this row.

        Pass ``None`` to clear the formula. The numeric ``@V`` is left
        untouched — the caller keeps authority over whether ``V`` or
        ``F`` is the source of truth.
        """
        cell = _get_or_add_row_cell(self._row, cell_name)
        if formula is None:
            cell.attrib.pop("F", None)
        else:
            cell.set("F", str(formula))

    def get_formula(self, cell_name: str) -> Optional[str]:
        """Return the ``@F`` formula on ``<Cell N=cell_name>`` or ``None``."""
        cell = _row_cell(self._row, cell_name)
        if cell is None:
            return None
        return cell.get("F")


class _XYOnlyRow(GeometryRow):
    """Shared base for row types whose cells are only X + Y."""

    # No additional cells beyond the inherited X / Y.


class MoveTo(_XYOnlyRow):
    """``T="MoveTo"`` — start a new subpath at (x, y).

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "MoveTo"


class LineTo(_XYOnlyRow):
    """``T="LineTo"`` — straight segment from the current point to (x, y).

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "LineTo"


class RelMoveTo(_XYOnlyRow):
    """``T="RelMoveTo"`` — relative ``MoveTo`` (coords scaled by Width / Height).

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "RelMoveTo"


class RelLineTo(_XYOnlyRow):
    """``T="RelLineTo"`` — relative ``LineTo``.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "RelLineTo"


class _XYARow(GeometryRow):
    """Row with X, Y, and a single extra ``A`` cell.

    ``A`` carries a row-type-specific scalar (bow for ArcTo, control
    parameter for SplineKnot / PolylineTo).
    """

    @property
    def a(self) -> Optional[float]:
        """The row's ``<Cell N="A">`` value as a float."""
        return _cell_float(self._row, "A")

    @a.setter
    def a(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "A", value, "IN")


class ArcTo(_XYARow):
    """``T="ArcTo"`` — circular arc ending at (x, y) with bow height ``a``.

    Visio's circular-arc primitive. The ``a`` cell (traditionally
    named the "bow height") is the perpendicular distance from the
    chord midpoint to the arc — positive bows to the left of the
    travel direction, negative to the right.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "ArcTo"

    @property
    def bow(self) -> Optional[float]:
        """Alias for :attr:`a` — the arc's bow height."""
        return self.a

    @bow.setter
    def bow(self, value: Optional[float]) -> None:
        self.a = value


class PolylineTo(_XYARow):
    """``T="PolylineTo"`` — polyline segment; ``a`` carries the PolyLine formula.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "PolylineTo"


class SplineKnot(_XYARow):
    """``T="SplineKnot"`` — additional knot on an in-progress spline.

    Follows a :class:`SplineStart` row; ``a`` is the knot value.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "SplineKnot"


class _XYABRow(_XYARow):
    """Row with X, Y, A, B cells."""

    @property
    def b(self) -> Optional[float]:
        """The row's ``<Cell N="B">`` value as a float."""
        return _cell_float(self._row, "B")

    @b.setter
    def b(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "B", value, "IN")


class InfiniteLine(_XYABRow):
    """``T="InfiniteLine"`` — an infinite-length line through two points.

    ``(x, y)`` and ``(a, b)`` are the two defining points. Rare; used
    for guide lines.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "InfiniteLine"


class RelQuadBezTo(_XYABRow):
    """``T="RelQuadBezTo"`` — relative quadratic Bezier.

    ``(a, b)`` is the control point; ``(x, y)`` is the endpoint.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "RelQuadBezTo"


class _XYABCDRow(_XYABRow):
    """Row with X, Y, A, B, C, D cells."""

    @property
    def c(self) -> Optional[float]:
        """The row's ``<Cell N="C">`` value as a float."""
        return _cell_float(self._row, "C")

    @c.setter
    def c(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "C", value, "IN")

    @property
    def d(self) -> Optional[float]:
        """The row's ``<Cell N="D">`` value as a float."""
        return _cell_float(self._row, "D")

    @d.setter
    def d(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "D", value, "IN")


class EllipticalArcTo(_XYABCDRow):
    """``T="EllipticalArcTo"`` — elliptical arc ending at (x, y).

    Cells: ``X`` / ``Y`` endpoint, ``A`` / ``B`` are a point on the arc
    (used together with the start point to determine the ellipse),
    ``C`` is the angle of the ellipse's major axis (radians),
    ``D`` is the aspect ratio of the ellipse (major ÷ minor axis).

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "EllipticalArcTo"


class RelEllipticalArcTo(_XYABCDRow):
    """``T="RelEllipticalArcTo"`` — relative-coordinate ``EllipticalArcTo``.

    Same cells as :class:`EllipticalArcTo`, but the X / Y / A / B
    coordinates are scaled by the shape's Width / Height.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "RelEllipticalArcTo"


class RelCubBezTo(_XYABCDRow):
    """``T="RelCubBezTo"`` — relative cubic Bezier.

    ``(a, b)`` is the first control point, ``(c, d)`` is the second,
    ``(x, y)`` is the endpoint. All coordinates are scaled by
    Width / Height.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "RelCubBezTo"


class Ellipse(_XYABCDRow):
    """``T="Ellipse"`` — full ellipse primitive (used as a standalone path).

    ``(x, y)`` is the centre; ``(a, b)`` is a point on the major axis;
    ``(c, d)`` is a point on the minor axis. An Ellipse row replaces
    the path — it is meaningful only as the sole row in its Geometry
    section.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "Ellipse"


class SplineStart(_XYABCDRow):
    """``T="SplineStart"`` — first row of a non-uniform B-spline.

    Cells: ``X`` / ``Y`` first knot point; ``A`` second knot; ``B``
    first knot weight; ``C`` last knot weight; ``D`` degree.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "SplineStart"


class NURBSTo(_XYABCDRow):
    """``T="NURBSTo"`` — non-uniform rational B-spline segment.

    Cells: ``X`` / ``Y`` endpoint; ``A`` second-to-last weight;
    ``B`` last weight; ``C`` formula for the full NURBS knot vector
    (``NURBS(…)`` call); ``D`` degree. The ``E`` cell occasionally
    appears as a continuation pointer — accessible via :attr:`e`.

    .. versionadded:: 0.3.0
    """

    ROW_TYPE = "NURBSTo"

    @property
    def e(self) -> Optional[float]:
        """The row's ``<Cell N="E">`` value as a float (rare continuation)."""
        return _cell_float(self._row, "E")

    @e.setter
    def e(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "E", value, "IN")


class UnknownGeometryRow(GeometryRow):
    """Fallback for geometry row types this module hasn't specialised.

    Preserves the ``@T`` discriminator verbatim and exposes the
    underlying row via :attr:`element` so callers can reach raw cells
    without losing round-trip fidelity.

    .. versionadded:: 0.3.0
    """

    # ``ROW_TYPE`` is intentionally empty — :attr:`row_type` reads the
    # attribute dynamically for this class.


# ---------------------------------------------------------------------------
# Row-type dispatch table
# ---------------------------------------------------------------------------


_ROW_TYPE_REGISTRY: dict[str, Type[GeometryRow]] = {
    cls.ROW_TYPE: cls
    for cls in (
        MoveTo,
        LineTo,
        ArcTo,
        EllipticalArcTo,
        NURBSTo,
        PolylineTo,
        SplineStart,
        SplineKnot,
        InfiniteLine,
        Ellipse,
        RelMoveTo,
        RelLineTo,
        RelCubBezTo,
        RelQuadBezTo,
        RelEllipticalArcTo,
    )
}


def _proxy_for_row(row: "CT_Row", geometry: "Geometry") -> GeometryRow:
    """Return the concrete :class:`GeometryRow` subclass for *row*.

    Unknown ``@T`` values fall back to :class:`UnknownGeometryRow` so
    load-preserve-save never drops rows.
    """
    t = row.get("T") or ""
    cls = _ROW_TYPE_REGISTRY.get(t, UnknownGeometryRow)
    return cls(row, geometry)


# ---------------------------------------------------------------------------
# Geometry — a single <Section N="Geometry"> on a shape
# ---------------------------------------------------------------------------


class Geometry(ParentedElementProxy):
    """One ``<Section N="Geometry">`` path on a :class:`~vsdx.shapes.base.Shape`.

    Construct indirectly via :attr:`Shape.geometry` (the first path) or
    :attr:`Shape.geometries` (the full collection); callers do not
    instantiate this class directly.

    Authoring surface — builder methods return the newly appended row
    proxy so callers can chain formula overrides::

        geo = shape.add_geometry()
        geo.move_to(0, 0)
        geo.line_to(1, 0)
        geo.line_to(1, 1)
        geo.line_to(0, 1)
        geo.line_to(0, 0)      # close the square

    .. versionadded:: 0.3.0
    """

    def __init__(self, section: "CT_Section", shape: "Shape") -> None:
        super().__init__(section, shape)
        self._section = section
        self._shape = shape

    # -- identity -------------------------------------------------------

    @property
    def index(self) -> int:
        """The section's ``@IX`` ordinal (0-based for the first path)."""
        v = self._section.get("IX")
        return int(v) if v is not None else 0

    @property
    def section(self) -> "CT_Section":
        """The underlying ``<Section>`` element (escape hatch)."""
        return self._section

    # -- section-level flag cells --------------------------------------
    # Every Geometry section carries a small number of boolean flag
    # cells (NoFill / NoLine / NoShow / NoSnap / NoQuickDrag) as
    # direct <Cell> children, not inside <Row>s. These determine
    # whether Visio paints the path as fill, stroke, both, or hides
    # it entirely.

    @property
    def no_fill(self) -> bool:
        """Whether the path is excluded from the shape's fill region."""
        return _cell_bool(self._section, "NoFill")

    @no_fill.setter
    def no_fill(self, value: bool) -> None:
        _set_section_bool_cell(self._section, "NoFill", bool(value))

    @property
    def no_line(self) -> bool:
        """Whether the path is excluded from the shape's line region."""
        return _cell_bool(self._section, "NoLine")

    @no_line.setter
    def no_line(self, value: bool) -> None:
        _set_section_bool_cell(self._section, "NoLine", bool(value))

    @property
    def no_show(self) -> bool:
        """Whether the path is hidden entirely (exists for selection only)."""
        return _cell_bool(self._section, "NoShow")

    @no_show.setter
    def no_show(self, value: bool) -> None:
        _set_section_bool_cell(self._section, "NoShow", bool(value))

    @property
    def no_snap(self) -> bool:
        """Whether the path participates in Visio's snap targets."""
        return _cell_bool(self._section, "NoSnap")

    @no_snap.setter
    def no_snap(self, value: bool) -> None:
        _set_section_bool_cell(self._section, "NoSnap", bool(value))

    @property
    def no_quick_drag(self) -> bool:
        """Whether quick-drag is disabled for this path."""
        return _cell_bool(self._section, "NoQuickDrag")

    @no_quick_drag.setter
    def no_quick_drag(self, value: bool) -> None:
        _set_section_bool_cell(self._section, "NoQuickDrag", bool(value))

    # -- row iteration -------------------------------------------------

    @property
    def rows(self) -> List[GeometryRow]:
        """The typed :class:`GeometryRow` proxies in ``@IX`` order.

        Returns a list so callers can index / len it directly; Visio
        geometry paths are always small (<100 rows) so materialising
        the list per access is cheap and keeps the API ergonomic.
        """
        ordered = sorted(
            self._section.row_lst,
            key=lambda r: int(r.get("IX") or 0),
        )
        return [_proxy_for_row(r, self) for r in ordered]

    def __iter__(self) -> Iterator[GeometryRow]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self._section.row_lst)

    def __getitem__(self, idx: int) -> GeometryRow:
        return self.rows[idx]

    # -- row-builder primitives ----------------------------------------

    def _next_ix(self) -> int:
        """Return the next monotonic ``@IX`` for a new row.

        Visio desktop starts Geometry-row indices at 1 (not 0) — the
        fixture corpus confirms this across every master we ship. We
        match that convention.
        """
        used: set[int] = set()
        for row in self._section.row_lst:
            ix = row.get("IX")
            if ix is not None:
                try:
                    used.add(int(ix))
                except ValueError:
                    pass
        candidate = 1
        while candidate in used:
            candidate += 1
        return candidate

    def _append_row(
        self, row_type: str, cells: "list[tuple[str, Optional[float]]]"
    ) -> "CT_Row":
        """Append a ``<Row T=row_type IX=…>`` with *cells* and return it.

        ``cells`` is an ordered list of (name, value) pairs. Cells with
        ``value=None`` are skipped entirely (useful for row types where
        some cells are optional and Visio would rather see them absent
        than present-but-empty).
        """
        row = self._section._add_row()
        row.set("T", row_type)
        row.set("IX", str(self._next_ix()))
        for name, value in cells:
            if value is None:
                continue
            cell = row._add_cell()
            cell.set("N", name)
            cell.set("V", _fmt_num(float(value)))
            # X/Y cells conventionally carry the IN unit; the other
            # letters (A..E) are often angles / ratios / unitless
            # coefficients, so we only emit U="IN" on explicit coord
            # cells to avoid garnishing non-coordinate values.
            if name in ("X", "Y"):
                cell.set("U", "IN")
        return row

    # -- typed builder methods -----------------------------------------

    def move_to(self, x: float, y: float) -> MoveTo:
        """Append a ``MoveTo`` row at *(x, y)* and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row("MoveTo", [("X", x), ("Y", y)])
        return MoveTo(row, self)

    def line_to(self, x: float, y: float) -> LineTo:
        """Append a ``LineTo`` row at *(x, y)* and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row("LineTo", [("X", x), ("Y", y)])
        return LineTo(row, self)

    def arc_to(self, x: float, y: float, bow: float) -> ArcTo:
        """Append an ``ArcTo`` row and return the row proxy.

        *bow* is the perpendicular distance from the chord midpoint to
        the arc (positive bows left of the travel direction).

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "ArcTo", [("X", x), ("Y", y), ("A", bow)]
        )
        return ArcTo(row, self)

    def elliptical_arc_to(
        self,
        x: float,
        y: float,
        a: float,
        b: float,
        c: float,
        d: float,
    ) -> EllipticalArcTo:
        """Append an ``EllipticalArcTo`` row and return the row proxy.

        ``(x, y)`` endpoint; ``(a, b)`` a point on the arc; ``c`` is
        the major-axis angle in radians; ``d`` is the aspect ratio.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "EllipticalArcTo",
            [("X", x), ("Y", y), ("A", a), ("B", b), ("C", c), ("D", d)],
        )
        return EllipticalArcTo(row, self)

    def polyline_to(self, x: float, y: float, a: float = 0.0) -> PolylineTo:
        """Append a ``PolylineTo`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "PolylineTo", [("X", x), ("Y", y), ("A", a)]
        )
        return PolylineTo(row, self)

    def spline_start(
        self,
        x: float,
        y: float,
        a: float,
        b: float,
        c: float,
        d: float,
    ) -> SplineStart:
        """Append a ``SplineStart`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "SplineStart",
            [("X", x), ("Y", y), ("A", a), ("B", b), ("C", c), ("D", d)],
        )
        return SplineStart(row, self)

    def spline_knot(self, x: float, y: float, a: float) -> SplineKnot:
        """Append a ``SplineKnot`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "SplineKnot", [("X", x), ("Y", y), ("A", a)]
        )
        return SplineKnot(row, self)

    def nurbs_to(
        self,
        x: float,
        y: float,
        a: float,
        b: float,
        c: float,
        d: float,
        e: Optional[float] = None,
    ) -> NURBSTo:
        """Append a ``NURBSTo`` row and return the row proxy.

        ``a``/``b`` are weights, ``c`` is the NURBS knot-vector
        formula / value, ``d`` is the degree, ``e`` is an optional
        continuation cell that is omitted when ``None``.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "NURBSTo",
            [
                ("X", x),
                ("Y", y),
                ("A", a),
                ("B", b),
                ("C", c),
                ("D", d),
                ("E", e),
            ],
        )
        return NURBSTo(row, self)

    def infinite_line(
        self, x: float, y: float, a: float, b: float
    ) -> InfiniteLine:
        """Append an ``InfiniteLine`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "InfiniteLine",
            [("X", x), ("Y", y), ("A", a), ("B", b)],
        )
        return InfiniteLine(row, self)

    def ellipse(
        self,
        x: float,
        y: float,
        a: float,
        b: float,
        c: float,
        d: float,
    ) -> Ellipse:
        """Append an ``Ellipse`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "Ellipse",
            [("X", x), ("Y", y), ("A", a), ("B", b), ("C", c), ("D", d)],
        )
        return Ellipse(row, self)

    # -- relative variants ---------------------------------------------

    def rel_move_to(self, x: float, y: float) -> RelMoveTo:
        """Append a ``RelMoveTo`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row("RelMoveTo", [("X", x), ("Y", y)])
        return RelMoveTo(row, self)

    def rel_line_to(self, x: float, y: float) -> RelLineTo:
        """Append a ``RelLineTo`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row("RelLineTo", [("X", x), ("Y", y)])
        return RelLineTo(row, self)

    def rel_cub_bez_to(
        self,
        x: float,
        y: float,
        a: float,
        b: float,
        c: float,
        d: float,
    ) -> RelCubBezTo:
        """Append a ``RelCubBezTo`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "RelCubBezTo",
            [("X", x), ("Y", y), ("A", a), ("B", b), ("C", c), ("D", d)],
        )
        return RelCubBezTo(row, self)

    def rel_quad_bez_to(
        self, x: float, y: float, a: float, b: float
    ) -> RelQuadBezTo:
        """Append a ``RelQuadBezTo`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "RelQuadBezTo",
            [("X", x), ("Y", y), ("A", a), ("B", b)],
        )
        return RelQuadBezTo(row, self)

    def rel_elliptical_arc_to(
        self,
        x: float,
        y: float,
        a: float,
        b: float,
        c: float,
        d: float,
    ) -> RelEllipticalArcTo:
        """Append a ``RelEllipticalArcTo`` row and return the row proxy.

        .. versionadded:: 0.3.0
        """
        row = self._append_row(
            "RelEllipticalArcTo",
            [("X", x), ("Y", y), ("A", a), ("B", b), ("C", c), ("D", d)],
        )
        return RelEllipticalArcTo(row, self)

    # -- row removal ---------------------------------------------------

    def remove_row(self, row: GeometryRow) -> None:
        """Remove *row* from this geometry path.

        Unlike :class:`Layers.remove`, no ``@IX`` renumbering happens —
        Visio treats geometry-row indices as opaque within a section
        (ordering is preserved by document order, not by index), so
        gaps are tolerated and fixture-byte-identity is preserved on
        rows the caller didn't remove.

        .. versionadded:: 0.3.0
        """
        self._section.remove(row._row)


# ---------------------------------------------------------------------------
# Geometries — the shape-scoped collection of Geometry sections
# ---------------------------------------------------------------------------


class Geometries(ParentedElementProxy):
    """Collection of :class:`Geometry` sections on a :class:`Shape`.

    A Visio shape may carry multiple Geometry sections (distinguished
    by ``@IX``) to encode compound paths — e.g. an outer outline plus
    an inner cut-out plus a stroke-only trim path.

    Callers reach an instance via :attr:`Shape.geometries`. Iteration
    yields :class:`Geometry` proxies in ``@IX`` order; :meth:`add`
    appends a fresh path and returns it.

    .. versionadded:: 0.3.0
    """

    def __init__(self, shape: "Shape") -> None:
        super().__init__(shape._element, shape)
        self._shape = shape

    # -- container ------------------------------------------------------

    def _sections(self) -> "list[CT_Section]":
        """Return the shape's Geometry sections in ``@IX`` order."""
        out = []
        for section in self._shape._element.section_lst:
            if section.get("N") == _GEOMETRY_SECTION_NAME:
                out.append(section)
        out.sort(key=lambda s: int(s.get("IX") or 0))
        return out

    def __iter__(self) -> Iterator[Geometry]:
        return iter(Geometry(s, self._shape) for s in self._sections())

    def __len__(self) -> int:
        return len(self._sections())

    def __getitem__(self, idx: int) -> Geometry:
        return list(iter(self))[idx]

    # -- authoring ------------------------------------------------------

    def add(
        self,
        *,
        no_fill: bool = False,
        no_line: bool = False,
        no_show: bool = False,
    ) -> Geometry:
        """Append a new ``<Section N="Geometry">`` and return its proxy.

        The new section's ``@IX`` is the next unused integer (starting
        at 0). Flag cells are emitted only when their argument is
        non-default truth — Visio tolerates their absence.

        .. versionadded:: 0.3.0
        """
        used: set[int] = set()
        for section in self._sections():
            ix = section.get("IX")
            if ix is not None:
                try:
                    used.add(int(ix))
                except ValueError:
                    pass
        next_ix = 0
        while next_ix in used:
            next_ix += 1
        section = self._shape._element._add_section()
        section.set("N", _GEOMETRY_SECTION_NAME)
        section.set("IX", str(next_ix))
        geometry = Geometry(section, self._shape)
        # Emit the default NoFill/NoLine/NoShow cells in the order Visio
        # desktop uses — matches the fixture corpus and keeps round-trip
        # byte-identity reachable when callers pass the defaults.
        geometry.no_fill = no_fill
        geometry.no_line = no_line
        geometry.no_show = no_show
        return geometry

    def remove(self, geometry: Geometry) -> None:
        """Remove *geometry* from the shape.

        No ``@IX`` renumbering — see :meth:`Geometry.remove_row` for
        the same rationale.

        .. versionadded:: 0.3.0
        """
        self._shape._element.remove(geometry._section)
