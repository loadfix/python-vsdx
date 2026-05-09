"""``ShapeData`` proxy — per-shape user-defined properties.

Visio exposes "Shape Data" (formerly "Custom Properties") on every
shape via a ``<Section N="Property">`` on the shape's own XML. Each
``<Row>`` inside the section carries one property, with its row name
(``Row/@N``) serving as the property's programmatic name and inner
``<Cell>`` children carrying the property's metadata:

* ``<Cell N="Label" V="…">`` — user-visible label.
* ``<Cell N="Value" V="…">`` — the property's value (Visio-typed).
* ``<Cell N="Format" V="…">`` — format string (``0.##`` / locale-picker / …).
* ``<Cell N="Type" V="0|1|2|3|4|5|6|7">`` — the Shape Data type:

  =====  ==========  =======================================
  ``V``  kind        coerced Python type
  =====  ==========  =======================================
  ``0``  String      ``str``
  ``1``  FixedList   ``str`` (``@V`` is the selected index)
  ``2``  Number      ``float``
  ``3``  Boolean     ``bool``  (``"0"``/``"1"``/``TRUE``/…)
  ``4``  VariableList ``str``
  ``5``  Date        ``str`` (ISO-ish; Visio emits serial)
  ``6``  Duration    ``str`` (``PT1H30M`` style sometimes)
  ``7``  Currency    ``float``
  =====  ==========  =======================================

* ``<Cell N="SortKey" V="…">`` — sort order hint (opaque string).
* ``<Cell N="Prompt" V="…">`` — tooltip / input prompt (optional).
* ``<Cell N="Invisible" V="0|1">`` — hidden-from-UI flag (optional).

Design notes (matches the R4-12 geometry playbook):

- **Zero new ``CT_*`` classes.** ShapeData rides on the existing
  :class:`~vsdx.oxml.section.CT_Section` /
  :class:`~vsdx.oxml.row.CT_Row` / :class:`~vsdx.oxml.cell.CT_Cell`
  trio. Discrimination is value-level (``section.@N == "Property"`` +
  ``row.@N`` for the property name), not class-level.
- Proxy is **dict-like** on the property's ``Row/@N`` name — lookup,
  iteration, and containment tests mirror the stdlib ``Mapping``
  surface so callers can write ``shape.data["Cost"]`` without ceremony.
- Typed coercion happens in :attr:`ShapeDataField.value` — the stored
  ``@V`` stays opaque at the XML layer; the proxy casts on read.
- :meth:`ShapeData.add_field` appends a new ``<Row>`` with the cells
  in the order Visio desktop emits them. Row-level ``@N`` is the
  field's programmatic name (UI "Name" column) — Visio also fills the
  ``Label`` cell with the display name, defaulting to the same string
  when the caller omits it.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, List, Optional, Union

from vsdx.shared import ParentedElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_Row, CT_Section  # TODO(vsdx/track-1)
    from vsdx.shapes.base import Shape


__all__ = [
    "PROPERTY_TYPE_BOOLEAN",
    "PROPERTY_TYPE_CURRENCY",
    "PROPERTY_TYPE_DATE",
    "PROPERTY_TYPE_DURATION",
    "PROPERTY_TYPE_FIXED_LIST",
    "PROPERTY_TYPE_NUMBER",
    "PROPERTY_TYPE_STRING",
    "PROPERTY_TYPE_VARIABLE_LIST",
    "ShapeData",
    "ShapeDataField",
]


# ---------------------------------------------------------------------------
# Shape-data type codes (Visio @Type cell values)
# ---------------------------------------------------------------------------

#: Plain-text property (``@Type`` = 0). Value coerced to :class:`str`.
PROPERTY_TYPE_STRING = 0
#: Fixed-list property (``@Type`` = 1). Value coerced to :class:`str`;
#: the ``@V`` on the Value cell is typically the selected option.
PROPERTY_TYPE_FIXED_LIST = 1
#: Numeric property (``@Type`` = 2). Value coerced to :class:`float`.
PROPERTY_TYPE_NUMBER = 2
#: Boolean property (``@Type`` = 3). Value coerced to :class:`bool`.
PROPERTY_TYPE_BOOLEAN = 3
#: Variable-list property (``@Type`` = 4). Value coerced to :class:`str`.
PROPERTY_TYPE_VARIABLE_LIST = 4
#: Date property (``@Type`` = 5). Value returned verbatim (Visio emits
#: a serial-day number; callers typically parse / format on their side).
PROPERTY_TYPE_DATE = 5
#: Duration property (``@Type`` = 6). Value returned verbatim.
PROPERTY_TYPE_DURATION = 6
#: Currency property (``@Type`` = 7). Value coerced to :class:`float`.
PROPERTY_TYPE_CURRENCY = 7


_SECTION_NAME = "Property"


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


def _cell_v(row: "CT_Row", name: str) -> Optional[str]:
    """Return ``@V`` on ``<Cell N=name>`` of *row*, or ``None`` if absent."""
    cell = _row_cell(row, name)
    if cell is None:
        return None
    return cell.get("V")


def _set_cell_v(row: "CT_Row", name: str, value: Optional[str]) -> None:
    """Create-or-update ``<Cell N=name V=value>`` on *row*.

    Passing ``None`` clears ``@V`` but leaves the cell element in place
    for round-trip fidelity (Visio tolerates present-but-empty cells).
    """
    cell = _get_or_add_row_cell(row, name)
    if value is None:
        cell.attrib.pop("V", None)
        return
    cell.set("V", value)


def _parse_bool(raw: Optional[str]) -> bool:
    """Coerce a Visio boolean ``@V`` to Python ``bool``.

    Visio emits ``"0"``/``"1"`` but also tolerates ``TRUE``/``FALSE``
    in some locales; be forgiving on the read side and strict on write.
    """
    if raw is None:
        return False
    token = raw.strip().lower()
    return token in ("1", "true", "yes", "-1")


def _fmt_number(value: Any) -> str:
    """Format a numeric value the way Visio emits it — integers lose .0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f == int(f):
        return str(int(f))
    return ("%f" % f).rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# ShapeDataField — one <Row> inside <Section N="Property">
# ---------------------------------------------------------------------------


class ShapeDataField:
    """One shape-data property.

    Wraps a single ``<Row>`` inside the shape's
    ``<Section N="Property">``. Callers get these via iteration /
    indexing on :class:`ShapeData`; they don't construct them directly.

    .. versionadded:: 0.3.0
    """

    def __init__(self, row: "CT_Row", shape_data: "ShapeData") -> None:
        self._row = row
        self._shape_data = shape_data

    # -- identity -------------------------------------------------------

    @property
    def name(self) -> str:
        """The property's programmatic name (``Row/@N``)."""
        return self._row.get("N") or ""

    @name.setter
    def name(self, value: str) -> None:
        self._row.set("N", str(value))

    @property
    def element(self) -> "CT_Row":
        """The underlying ``<Row>`` element (escape hatch)."""
        return self._row

    # -- metadata cells -------------------------------------------------

    @property
    def label(self) -> Optional[str]:
        """User-visible label (``<Cell N="Label">`` ``@V``), or ``None``."""
        return _cell_v(self._row, "Label")

    @label.setter
    def label(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "Label", value)

    @property
    def type(self) -> int:
        """The property's Visio type code (``<Cell N="Type">`` ``@V``).

        Defaults to :data:`PROPERTY_TYPE_STRING` (0) when the Type cell
        is absent, matching Visio's implicit-default behaviour.
        """
        raw = _cell_v(self._row, "Type")
        if raw is None or raw == "":
            return PROPERTY_TYPE_STRING
        try:
            return int(raw)
        except ValueError:
            return PROPERTY_TYPE_STRING

    @type.setter
    def type(self, value: int) -> None:
        _set_cell_v(self._row, "Type", str(int(value)))

    @property
    def format(self) -> Optional[str]:
        """Format string (``<Cell N="Format">`` ``@V``), or ``None``."""
        return _cell_v(self._row, "Format")

    @format.setter
    def format(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "Format", value)

    @property
    def sort_key(self) -> Optional[str]:
        """Sort-key hint (``<Cell N="SortKey">`` ``@V``)."""
        return _cell_v(self._row, "SortKey")

    @sort_key.setter
    def sort_key(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "SortKey", value)

    @property
    def prompt(self) -> Optional[str]:
        """Input-prompt tooltip (``<Cell N="Prompt">`` ``@V``)."""
        return _cell_v(self._row, "Prompt")

    @prompt.setter
    def prompt(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "Prompt", value)

    @property
    def invisible(self) -> bool:
        """Whether the property is hidden from Visio's Shape Data pane."""
        return _parse_bool(_cell_v(self._row, "Invisible"))

    @invisible.setter
    def invisible(self, value: bool) -> None:
        _set_cell_v(self._row, "Invisible", "1" if value else "0")

    # -- value (typed) --------------------------------------------------

    @property
    def raw_value(self) -> Optional[str]:
        """The raw ``@V`` string on ``<Cell N="Value">``, uncoerced."""
        return _cell_v(self._row, "Value")

    @raw_value.setter
    def raw_value(self, value: Optional[str]) -> None:
        _set_cell_v(self._row, "Value", value)

    @property
    def value(self) -> Any:
        """The property's value, coerced per :attr:`type`.

        Mapping:

        * ``String`` / ``FixedList`` / ``VariableList`` → :class:`str`
        * ``Number`` / ``Currency`` → :class:`float`
        * ``Boolean`` → :class:`bool`
        * ``Date`` / ``Duration`` → raw :class:`str` (Visio emits a
          serial-day number for Date which callers typically want to
          parse themselves — we pass it through verbatim).

        Returns ``None`` when the ``<Cell N="Value">`` is absent or
        its ``@V`` is empty.
        """
        raw = self.raw_value
        if raw is None or raw == "":
            return None
        t = self.type
        if t in (PROPERTY_TYPE_NUMBER, PROPERTY_TYPE_CURRENCY):
            try:
                return float(raw)
            except ValueError:
                return raw
        if t == PROPERTY_TYPE_BOOLEAN:
            return _parse_bool(raw)
        # String, FixedList, VariableList, Date, Duration — pass through.
        return raw

    @value.setter
    def value(self, value: Any) -> None:
        """Set ``<Cell N="Value">`` ``@V``, formatting per :attr:`type`.

        Numeric types emit integer-trimmed decimal strings; booleans
        emit ``"0"`` / ``"1"``; everything else stringifies via ``str``.
        """
        if value is None:
            _set_cell_v(self._row, "Value", None)
            return
        t = self.type
        if t in (PROPERTY_TYPE_NUMBER, PROPERTY_TYPE_CURRENCY):
            _set_cell_v(self._row, "Value", _fmt_number(value))
            return
        if t == PROPERTY_TYPE_BOOLEAN:
            _set_cell_v(self._row, "Value", "1" if bool(value) else "0")
            return
        _set_cell_v(self._row, "Value", str(value))

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<ShapeDataField name={self.name!r} "
            f"type={self.type} value={self.value!r}>"
        )


# ---------------------------------------------------------------------------
# ShapeData — dict-like collection over <Section N="Property"> rows
# ---------------------------------------------------------------------------


class ShapeData(ParentedElementProxy):
    """Shape-scoped user-defined-properties proxy.

    Dict-like wrapper over the shape's ``<Section N="Property">``:
    ``shape.data["Cost"]`` returns the *value* (typed per the
    property's ``Type`` cell); ``shape.data.field("Cost")`` returns
    the underlying :class:`ShapeDataField` for metadata access.

    Iteration yields the property names (``Row/@N``) in document
    order. Missing Property section behaves as an empty mapping —
    only :meth:`add_field` materialises the section on demand.

    .. versionadded:: 0.3.0
    """

    def __init__(self, shape: "Shape") -> None:
        super().__init__(shape._element, shape)
        self._shape = shape

    # -- section lookup -------------------------------------------------

    def _section(self) -> Optional["CT_Section"]:
        """Return the shape's first ``<Section N="Property">``, or ``None``."""
        for section in self._shape._element.section_lst:
            if section.get("N") == _SECTION_NAME:
                return section
        return None

    def _get_or_add_section(self) -> "CT_Section":
        """Return the Property section, creating one if absent."""
        section = self._section()
        if section is not None:
            return section
        section = self._shape._element._add_section()
        section.set("N", _SECTION_NAME)
        return section

    # -- Mapping surface ------------------------------------------------

    def _rows(self) -> "List[CT_Row]":
        section = self._section()
        if section is None:
            return []
        return list(section.row_lst)

    def _row_by_name(self, name: str) -> Optional["CT_Row"]:
        for row in self._rows():
            if row.get("N") == name:
                return row
        return None

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return self._row_by_name(name) is not None

    def __len__(self) -> int:
        return len(self._rows())

    def __iter__(self) -> Iterator[str]:
        for row in self._rows():
            n = row.get("N")
            if n is not None:
                yield n

    def __getitem__(self, name: str) -> Any:
        row = self._row_by_name(name)
        if row is None:
            raise KeyError(name)
        return ShapeDataField(row, self).value

    def __setitem__(self, name: str, value: Any) -> None:
        """Set the value of an existing field; raise KeyError if missing.

        Use :meth:`add_field` to create a new property — assignment-
        only-create would swallow the type / label metadata the caller
        usually wants to set explicitly.
        """
        row = self._row_by_name(name)
        if row is None:
            raise KeyError(name)
        ShapeDataField(row, self).value = value

    def __delitem__(self, name: str) -> None:
        self.remove_field(name)

    # -- typed accessors ------------------------------------------------

    def field(self, name: str) -> ShapeDataField:
        """Return the :class:`ShapeDataField` proxy for *name*.

        Raises :class:`KeyError` when the property is absent. Use
        :meth:`get_field` for the get-or-``None`` variant.
        """
        row = self._row_by_name(name)
        if row is None:
            raise KeyError(name)
        return ShapeDataField(row, self)

    def get_field(self, name: str) -> Optional[ShapeDataField]:
        """Return the field proxy for *name*, or ``None`` if missing."""
        row = self._row_by_name(name)
        if row is None:
            return None
        return ShapeDataField(row, self)

    def get(self, name: str, default: Any = None) -> Any:
        """Return the value of property *name*, or *default* if missing.

        Typed coercion matches :meth:`__getitem__`.
        """
        row = self._row_by_name(name)
        if row is None:
            return default
        return ShapeDataField(row, self).value

    def fields(self) -> List[ShapeDataField]:
        """Return all fields as :class:`ShapeDataField` proxies."""
        return [ShapeDataField(r, self) for r in self._rows()]

    def names(self) -> List[str]:
        """Return all property names (``Row/@N``) in document order."""
        return list(iter(self))

    # -- mutation -------------------------------------------------------

    def add_field(
        self,
        name: str,
        value: Any = None,
        *,
        label: Optional[str] = None,
        type: int = PROPERTY_TYPE_STRING,
        format: Optional[str] = None,
        prompt: Optional[str] = None,
        sort_key: Optional[str] = None,
        invisible: bool = False,
    ) -> ShapeDataField:
        """Append a new property *name* with *value* and return its proxy.

        The new ``<Row>`` is emitted into the shape's
        ``<Section N="Property">`` (materialised on first use).

        :param name: Programmatic property name (``Row/@N``). Also used
          as the default ``Label`` when *label* is ``None``.
        :param value: Initial value. Formatted per *type* — numeric
          types emit integer-trimmed decimals, booleans emit ``"0"``/
          ``"1"``, everything else stringifies.
        :param label: User-visible label. Defaults to *name*.
        :param type: Visio type code (:data:`PROPERTY_TYPE_STRING` …
          :data:`PROPERTY_TYPE_CURRENCY`). Defaults to ``String``.
        :param format: Optional format string.
        :param prompt: Optional tooltip / input prompt.
        :param sort_key: Optional sort-key hint.
        :param invisible: Whether to hide from the Shape Data pane.
        :raises ValueError: If *name* is empty or a property with that
          name already exists.

        .. versionadded:: 0.3.0
        """
        if not name:
            raise ValueError("Shape-data field name must be non-empty")
        if self._row_by_name(name) is not None:
            raise ValueError(
                f"Shape already has a data field named {name!r}; "
                "remove it first or use shape.data.field(name).value = …"
            )
        section = self._get_or_add_section()
        row = section._add_row()
        row.set("N", name)
        # Cell emission order matches Visio desktop's canonical order:
        # Value, Prompt, Label, Format, SortKey, Type, Invisible.
        # Keeping the order stable helps byte-identity on round-trips of
        # caller-authored fields (it doesn't affect fidelity of parsed
        # fields — their cells stay in document order).
        field = ShapeDataField(row, self)
        field.type = int(type)
        # Set value AFTER type so the value-setter's formatter dispatches
        # on the correct type code.
        field.value = value
        field.label = name if label is None else label
        if format is not None:
            field.format = format
        if prompt is not None:
            field.prompt = prompt
        if sort_key is not None:
            field.sort_key = sort_key
        if invisible:
            field.invisible = True
        return field

    def remove_field(self, name: str) -> None:
        """Remove the property *name* from this shape.

        :raises KeyError: If no property with that name exists.

        Leaves the ``<Section N="Property">`` in place even when the
        last row is removed — Visio tolerates empty sections and
        preserving the element keeps byte-identity on round-trips that
        touch a property the caller then adds back.

        .. versionadded:: 0.3.0
        """
        row = self._row_by_name(name)
        if row is None:
            raise KeyError(name)
        section = self._section()
        assert section is not None  # row_by_name implies section exists
        section.remove(row)

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        names = ", ".join(repr(n) for n in self.names())
        return f"<ShapeData fields=[{names}]>"
