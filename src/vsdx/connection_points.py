"""``ConnectionPoints`` proxy — per-shape connection-point coordinates.

Visio exposes connection points on a shape via a
``<Section N="Connection">`` on the shape's own XML. Each ``<Row>``
inside the section is one point — an anchor that Visio uses when a
connector's endpoint is glued to the shape. Cells:

* ``<Cell N="X" V="…" U="IN">`` — local X coordinate (shape frame).
* ``<Cell N="Y" V="…" U="IN">`` — local Y coordinate.
* ``<Cell N="DirX" V="…">`` — "direction" unit-vector X component.
  Zero on static (inward) points; non-zero turns the point into a
  directional point that biases connector routing.
* ``<Cell N="DirY" V="…">`` — direction Y component.
* ``<Cell N="Type" V="0|1|2">`` — connection-point kind:

  =====  ===================  =======================================
  ``V``  kind                 meaning
  =====  ===================  =======================================
  ``0``  Inward               accepts outward connector endpoints
                              (the default for most anchors).
  ``1``  Outward              projects a connector endpoint outward
                              (used for dynamic-glue targets).
  ``2``  InwardOutward        accepts both — usually set on the
                              dynamic-connection-point "plus" anchor.
  =====  ===================  =======================================

* ``<Cell N="AutoGen" V="0|1">`` — whether Visio auto-generated the
  point (e.g. when the user drops a connector and Visio adds a
  matching anchor). Preserved for round-trip fidelity.

Design notes (matches the R4-12 geometry / R8-3 shape-data playbook):

- **Zero new ``CT_*`` classes.** Connection points ride on the
  existing :class:`~vsdx.oxml.section.CT_Section` /
  :class:`~vsdx.oxml.row.CT_Row` / :class:`~vsdx.oxml.cell.CT_Cell`
  trio. Discrimination is value-level (``section.@N == "Connection"``
  + ``row.@IX`` for the point's ordinal), not class-level.
- Proxy is **list-like** keyed by ``@IX`` — lookup, iteration,
  containment tests, indexing, and ``len()`` mirror the stdlib
  ``Sequence`` surface so callers can write
  ``shape.connection_points[0].x`` without ceremony.
- :meth:`ConnectionPoints.add` appends a new ``<Row>`` with the cells
  in the order Visio desktop emits them (X, Y, DirX, DirY, Type,
  AutoGen). Row-level ``@IX`` is monotonic starting at 1 — Visio
  desktop starts Connection-row indices at 1 (not 0) across every
  master we ship, matching the geometry-row convention.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Iterator, List, Optional

from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_Row, CT_Section  # TODO(vsdx/track-1)
    from vsdx.shapes.base import Shape


__all__ = [
    "CONNECTION_TYPE",
    "ConnectionPoint",
    "ConnectionPoints",
]


_SECTION_NAME = "Connection"


class CONNECTION_TYPE(str, Enum):
    """Enumeration of connection-point kinds (``<Cell N="Type">`` ``@V``).

    Carried as a ``str`` subclass so the member's value round-trips
    verbatim through the ``@V`` attribute and callers can compare
    directly against the raw string (``point.type == "0"`` is legal
    alongside ``point.type == CONNECTION_TYPE.INWARD``).

    .. versionadded:: 0.3.0
    """

    #: Accepts outward connector endpoints — the default for most
    #: anchors (``<Cell N="Type" V="0">``).
    INWARD = "0"
    #: Projects a connector endpoint outward — used for dynamic-glue
    #: targets (``<Cell N="Type" V="1">``).
    OUTWARD = "1"
    #: Accepts both inward and outward endpoints — typically the
    #: dynamic-connection-point anchor (``<Cell N="Type" V="2">``).
    INWARD_OUTWARD = "2"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


# ---------------------------------------------------------------------------
# Cell-level helpers — named cells inside a <Row>
# ---------------------------------------------------------------------------


def _row_cell(row: "CT_Row", name: str) -> Optional["CT_Cell"]:
    """Return the ``<Cell N=name>`` child on *row*, or ``None``."""
    for cell in row.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _get_or_add_row_cell(row: "CT_Row", name: str) -> "CT_Cell":
    """Return ``<Cell N=name>`` on *row*, creating it if absent."""
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


def _cell_v(row: "CT_Row", name: str) -> Optional[str]:
    """Return ``@V`` on ``<Cell N=name>`` of *row*, or ``None`` if absent."""
    cell = _row_cell(row, name)
    if cell is None:
        return None
    return cell.get("V")


def _set_cell_float(
    row: "CT_Row", name: str, value: Optional[float], unit: Optional[str] = None
) -> None:
    """Create-or-update ``<Cell N=name V=value U=unit>`` on *row*.

    Passing *value* as ``None`` clears both ``@V`` and ``@U`` but leaves
    the cell element in place for round-trip fidelity.
    """
    cell = _get_or_add_row_cell(row, name)
    if value is None:
        cell.attrib.pop("V", None)
        cell.attrib.pop("U", None)
        return
    cell.set("V", _fmt_num(float(value)))
    if unit is not None:
        cell.set("U", unit)


def _set_cell_v(row: "CT_Row", name: str, value: Optional[str]) -> None:
    """Create-or-update ``<Cell N=name V=value>`` on *row*."""
    cell = _get_or_add_row_cell(row, name)
    if value is None:
        cell.attrib.pop("V", None)
        return
    cell.set("V", value)


def _fmt_num(v: float) -> str:
    """Format a float the way Visio emits it — trim trailing zeros."""
    if v == int(v):
        return str(int(v))
    return ("%f" % v).rstrip("0").rstrip(".")


def _parse_bool(raw: Optional[str]) -> bool:
    """Coerce a Visio boolean ``@V`` to Python ``bool``."""
    if raw is None:
        return False
    token = raw.strip().lower()
    return token in ("1", "true", "yes", "-1")


def _coerce_type(value: object) -> str:
    """Coerce *value* to a :class:`CONNECTION_TYPE`-backed ``@V`` string.

    Accepts a :class:`CONNECTION_TYPE` member, a raw ``"0"``/``"1"``/
    ``"2"`` string, or an integer ``0``/``1``/``2``. Anything else
    raises :class:`ValueError`.
    """
    if isinstance(value, CONNECTION_TYPE):
        return value.value
    if isinstance(value, int) and not isinstance(value, bool):
        token = str(value)
    else:
        token = str(value)
    if token not in ("0", "1", "2"):
        raise ValueError(
            "connection-point type must be CONNECTION_TYPE or 0/1/2, "
            "got %r" % (value,)
        )
    return token


# ---------------------------------------------------------------------------
# ConnectionPoint — one <Row> inside <Section N="Connection">
# ---------------------------------------------------------------------------


class ConnectionPoint:
    """One connection point on a shape.

    Wraps a single ``<Row>`` inside the shape's
    ``<Section N="Connection">``. Callers get these via iteration /
    indexing on :class:`ConnectionPoints`; they do not construct them
    directly.

    .. versionadded:: 0.3.0
    """

    def __init__(
        self, row: "CT_Row", connection_points: "ConnectionPoints"
    ) -> None:
        self._row = row
        self._connection_points = connection_points

    # -- identity -------------------------------------------------------

    @property
    def index(self) -> int:
        """The point's ``@IX`` ordinal (1-based in Visio)."""
        v = self._row.get("IX")
        return int(v) if v is not None else 0

    @property
    def element(self) -> "CT_Row":
        """The underlying ``<Row>`` element (escape hatch)."""
        return self._row

    # -- coordinate cells ----------------------------------------------

    @property
    def x(self) -> Optional[float]:
        """Local X coordinate (``<Cell N="X">`` ``@V``), in inches."""
        return _cell_float(self._row, "X")

    @x.setter
    def x(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "X", value, "IN")

    @property
    def y(self) -> Optional[float]:
        """Local Y coordinate (``<Cell N="Y">`` ``@V``), in inches."""
        return _cell_float(self._row, "Y")

    @y.setter
    def y(self, value: Optional[float]) -> None:
        _set_cell_float(self._row, "Y", value, "IN")

    @property
    def dir_x(self) -> float:
        """Direction unit-vector X (``<Cell N="DirX">`` ``@V``).

        Defaults to ``0.0`` when the DirX cell is absent, matching
        Visio's implicit-default behaviour for static (inward-only)
        connection points.
        """
        return _cell_float(self._row, "DirX") or 0.0

    @dir_x.setter
    def dir_x(self, value: float) -> None:
        _set_cell_float(self._row, "DirX", float(value))

    @property
    def dir_y(self) -> float:
        """Direction unit-vector Y (``<Cell N="DirY">`` ``@V``)."""
        return _cell_float(self._row, "DirY") or 0.0

    @dir_y.setter
    def dir_y(self, value: float) -> None:
        _set_cell_float(self._row, "DirY", float(value))

    # -- type ----------------------------------------------------------

    @property
    def type(self) -> CONNECTION_TYPE:
        """The point's kind (``<Cell N="Type">`` ``@V``).

        Returns a :class:`CONNECTION_TYPE` member. Defaults to
        :attr:`CONNECTION_TYPE.INWARD` when the Type cell is absent,
        matching Visio's implicit-default behaviour.
        """
        raw = _cell_v(self._row, "Type")
        if raw is None or raw == "":
            return CONNECTION_TYPE.INWARD
        try:
            return CONNECTION_TYPE(raw)
        except ValueError:
            # Unknown type code — fall back to inward rather than
            # raising on parse so load-preserve-save never drops rows.
            return CONNECTION_TYPE.INWARD

    @type.setter
    def type(self, value: object) -> None:
        _set_cell_v(self._row, "Type", _coerce_type(value))

    # -- auto-gen flag -------------------------------------------------

    @property
    def auto_gen(self) -> bool:
        """Whether Visio auto-generated this point.

        Returns ``False`` when the ``<Cell N="AutoGen">`` cell is
        absent (the common case for user-authored points).
        """
        return _parse_bool(_cell_v(self._row, "AutoGen"))

    @auto_gen.setter
    def auto_gen(self, value: bool) -> None:
        _set_cell_v(self._row, "AutoGen", "1" if value else "0")

    # -- repr ----------------------------------------------------------

    def __repr__(self) -> str:
        return (
            "<ConnectionPoint index=%d x=%r y=%r type=%s>"
            % (self.index, self.x, self.y, self.type.name)
        )


# ---------------------------------------------------------------------------
# ConnectionPoints — list-like collection over <Section N="Connection"> rows
# ---------------------------------------------------------------------------


class ConnectionPoints(ParentedElementProxy):
    """Shape-scoped connection-points proxy.

    List-like wrapper over the shape's ``<Section N="Connection">``:
    ``shape.connection_points[0]`` returns the first
    :class:`ConnectionPoint` (in ``@IX`` order). Iteration yields the
    points in ``@IX`` order; missing Connection section behaves as an
    empty sequence — only :meth:`add` materialises the section on
    demand.

    .. versionadded:: 0.3.0
    """

    def __init__(self, shape: "Shape") -> None:
        super().__init__(shape._element, shape)
        self._shape = shape

    # -- section lookup -------------------------------------------------

    def _section(self) -> Optional["CT_Section"]:
        """Return the shape's first ``<Section N="Connection">``, or ``None``."""
        for section in self._shape._element.section_lst:
            if section.get("N") == _SECTION_NAME:
                return section
        return None

    def _get_or_add_section(self) -> "CT_Section":
        """Return the Connection section, creating one if absent."""
        section = self._section()
        if section is not None:
            return section
        section = self._shape._element._add_section()
        section.set("N", _SECTION_NAME)
        return section

    # -- container surface ---------------------------------------------

    def _rows(self) -> "List[CT_Row]":
        """Return the connection-point ``<Row>`` elements in ``@IX`` order."""
        section = self._section()
        if section is None:
            return []
        return sorted(
            section.row_lst,
            key=lambda r: int(r.get("IX") or 0),
        )

    def __len__(self) -> int:
        return len(self._rows())

    def __iter__(self) -> Iterator[ConnectionPoint]:
        for row in self._rows():
            yield ConnectionPoint(row, self)

    def __getitem__(self, idx: int) -> ConnectionPoint:
        rows = self._rows()
        return ConnectionPoint(rows[idx], self)

    def __contains__(self, item: object) -> bool:
        if not isinstance(item, ConnectionPoint):
            return False
        return any(r is item._row for r in self._rows())

    # -- authoring -----------------------------------------------------

    def _next_ix(self) -> int:
        """Return the next monotonic ``@IX`` for a new connection point.

        Visio desktop starts Connection-row indices at 1 (not 0),
        matching the geometry-row convention.
        """
        used: set[int] = set()
        for row in self._rows():
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

    def add(
        self,
        x: float,
        y: float,
        *,
        dir_x: float = 0.0,
        dir_y: float = 0.0,
        type: object = CONNECTION_TYPE.INWARD,
        auto_gen: bool = False,
    ) -> ConnectionPoint:
        """Append a new connection point at *(x, y)* and return its proxy.

        The new ``<Row>`` is emitted into the shape's
        ``<Section N="Connection">`` (materialised on first use).

        :param x: Local X coordinate (in inches).
        :param y: Local Y coordinate (in inches).
        :param dir_x: Direction unit-vector X component. Defaults to
          ``0.0``; leave at zero for static (inward) points.
        :param dir_y: Direction unit-vector Y component. Defaults to
          ``0.0``.
        :param type: One of :class:`CONNECTION_TYPE` / ``"0"`` / ``"1"``
          / ``"2"`` / ``0`` / ``1`` / ``2``. Defaults to
          :attr:`CONNECTION_TYPE.INWARD`.
        :param auto_gen: Whether Visio auto-generated this point.
          Defaults to ``False``.
        :raises ValueError: If *type* is not a recognised kind.

        .. versionadded:: 0.3.0
        """
        type_v = _coerce_type(type)
        section = self._get_or_add_section()
        row = section._add_row()
        row.set("IX", str(self._next_ix()))
        # Cell emission order matches Visio desktop's canonical order:
        # X, Y, DirX, DirY, Type, AutoGen. Keeping the order stable
        # helps byte-identity on round-trips of caller-authored points
        # (it doesn't affect fidelity of parsed points — their cells
        # stay in document order).
        point = ConnectionPoint(row, self)
        point.x = x
        point.y = y
        point.dir_x = dir_x
        point.dir_y = dir_y
        # Write the Type cell unconditionally — Visio's implicit default
        # is inward (0) but fixture byte-identity across the corpus
        # rewards us for always emitting the cell.
        _set_cell_v(row, "Type", type_v)
        if auto_gen:
            point.auto_gen = True
        return point

    def remove(self, index: int) -> None:
        """Remove the connection point at *index* (0-based position).

        Unlike :class:`~vsdx.layers.Layers.remove`, no ``@IX``
        renumbering happens — Visio treats Connection-row indices as
        opaque within a section (ordering is preserved by document
        order plus ``@IX`` sort key), so gaps are tolerated and
        fixture-byte-identity is preserved on rows the caller didn't
        remove.

        :raises IndexError: If *index* is out of range.

        .. versionadded:: 0.3.0
        """
        rows = self._rows()
        row = rows[index]  # raises IndexError if out-of-range
        section = self._section()
        assert section is not None  # row implies section exists
        section.remove(row)

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        return "<ConnectionPoints count=%d>" % len(self)
