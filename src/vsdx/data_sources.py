# Copyright 2026 The python-vsdx Authors
# SPDX-License-Identifier: Apache-2.0
"""Higher-level CSV-backed data-source overlay (issue #118).

Sits above :mod:`vsdx.data_recordsets`. Where ``DataRecordset`` mirrors
Visio desktop's own external-data part, this module provides a
one-call authoring surface that (1) reads a CSV into memory, (2) lets
shapes opt-in by natural key via :meth:`Shape.bind_to_row`, and (3)
supports four overlay graphic kinds (``text-callout`` / ``icon-set`` /
``data-bar`` / ``color-by-value``) evaluated on
:meth:`DataSource.refresh`.

Persistence is vsdx-local: a ``<Section N="DataSources">`` on the
document root captures sources + graphics, and bound shapes carry a
``<Cell N="DataSourceBinding" V="<source-id>!<key>">``. Visio desktop
treats both as opaque round-trip data — desktop-native rendering of
the overlays is a follow-up that maps onto
``<Section N="DataGraphic">``. CSV is the only v1 source format;
Excel and SQL are documented follow-ups.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import csv
import os
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from vsdx.constants import NS_VSDX_CORE

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.page import Page
    from vsdx.shapes.base import Shape


__all__ = [
    "DataGraphicSpec",
    "DataSource",
    "DataSources",
    "GRAPHIC_KIND_COLOR_BY_VALUE",
    "GRAPHIC_KIND_DATA_BAR",
    "GRAPHIC_KIND_ICON_SET",
    "GRAPHIC_KIND_TEXT_CALLOUT",
]


# ---------------------------------------------------------------------------
# Public string-id constants for the four graphic kinds.
# ---------------------------------------------------------------------------

#: Render the field value verbatim as a text decoration on the shape.
GRAPHIC_KIND_TEXT_CALLOUT = "text-callout"
#: Render an icon based on a list of ``when`` rules.
GRAPHIC_KIND_ICON_SET = "icon-set"
#: Render a horizontal bar proportional to a numeric field's value.
GRAPHIC_KIND_DATA_BAR = "data-bar"
#: Recolour the shape's fill based on a list of ``when`` rules.
GRAPHIC_KIND_COLOR_BY_VALUE = "color-by-value"


_VALID_KINDS = (
    GRAPHIC_KIND_TEXT_CALLOUT,
    GRAPHIC_KIND_ICON_SET,
    GRAPHIC_KIND_DATA_BAR,
    GRAPHIC_KIND_COLOR_BY_VALUE,
)

#: Section name carrying the document-root persistence (one section per doc).
_SOURCES_SECTION = "DataSources"

#: Per-source row discriminator (``Row/@T``) inside ``<Section N="DataSources">``.
_ROW_T_SOURCE = "Source"
_ROW_T_GRAPHIC = "Graphic"

#: Cell name carrying a shape's source-binding sentinel.
_BINDING_CELL = "DataSourceBinding"

#: Format ``shape→source`` binding value as ``"<source_id>!<key>"``. The
#: ``!`` separator was chosen because keys are user-facing values
#: (``"ID"`` / ``"SKU-1234"``) and CSVs rarely embed ``!``; a custom
#: separator keeps the parser unambiguous without escaping.
_BINDING_SEP = "!"

#: ``<Cell N="DataSourceCallout">`` — overlay text-callout sentinel set
#: by :func:`_apply_text_callout`.  The cell is overwritten on every
#: :meth:`DataSource.refresh`; absence means "no active text-callout
#: overlay on this shape from any source".
_CALLOUT_CELL = "DataSourceCallout"
#: ``<Cell N="DataSourceIcon">`` — overlay icon sentinel.
_ICON_CELL = "DataSourceIcon"
#: ``<Cell N="DataSourceBar">`` — overlay data-bar sentinel; value is
#: a percentage in ``0.0`` … ``1.0`` formatted as a float.
_BAR_CELL = "DataSourceBar"

#: Standalone ``<Cell N="FillForegnd">`` is what Visio uses for the
#: shape fill colour; ``color-by-value`` writes here so the change
#: is visible to every other consumer of :attr:`Shape.fill_foregnd`.
_FILL_CELL = "FillForegnd"


# ---------------------------------------------------------------------------
# Cell-level helpers — read/write `<Cell N=..>` children of an element.
# ---------------------------------------------------------------------------


def _named_cell(element, name: str):
    """Return ``<Cell N=name>`` on *element*, or ``None``."""
    for cell in element.cell_lst:
        if cell.get("N") == name:
            return cell
    return None


def _named_cell_v(element, name: str) -> Optional[str]:
    cell = _named_cell(element, name)
    if cell is None:
        return None
    return cell.get("V")


def _set_named_cell_v(element, name: str, value: Optional[str]) -> None:
    """Locate-or-create ``<Cell N=name>`` on *element* and set its ``@V``.

    ``value=None`` removes the cell entirely; otherwise the cell is
    materialised on demand and its ``@V`` overwritten.
    """
    existing = _named_cell(element, name)
    if value is None:
        if existing is not None:
            element.remove(existing)
        return
    cell = existing if existing is not None else element._add_cell()
    cell.set("N", name)
    cell.set("V", value)


# ---------------------------------------------------------------------------
# Section-level helpers — locate-or-create ``<Section N="DataSources">``.
# ---------------------------------------------------------------------------


def _sources_section(document_element):
    for section in document_element.section_lst:
        if section.get("N") == _SOURCES_SECTION:
            return section
    return None


def _get_or_add_sources_section(document_element):
    section = _sources_section(document_element)
    if section is not None:
        return section
    section = document_element._add_section()
    section.set("N", _SOURCES_SECTION)
    return section


# ---------------------------------------------------------------------------
# DataGraphicSpec — one declared graphic configuration on a DataSource.
# ---------------------------------------------------------------------------


class DataGraphicSpec:
    """One overlay-graphic declaration on a :class:`DataSource`.

    Wraps a ``<Row T="Graphic">`` row inside the document-root
    ``<Section N="DataSources">``. Construct indirectly via
    :meth:`DataSource.add_data_graphic`.

    .. versionadded:: 0.4.0
    """

    def __init__(self, row, source: "DataSource") -> None:
        self._row = row
        self._source = source

    # -- identity / config ----------------------------------------------

    @property
    def field(self) -> str:
        """The CSV column the graphic reads from (``Row/@N``)."""
        return self._row.get("N") or ""

    @property
    def kind(self) -> str:
        """The graphic kind — one of the ``GRAPHIC_KIND_*`` constants."""
        return _named_cell_v(self._row, "Kind") or GRAPHIC_KIND_TEXT_CALLOUT

    @property
    def position(self) -> Optional[str]:
        """Free-form position hint (``"top"``, ``"bottom-right"``, …)."""
        return _named_cell_v(self._row, "Position")

    @property
    def color(self) -> Optional[str]:
        """Theme / hex colour token used by ``data-bar`` and rule defaults."""
        return _named_cell_v(self._row, "Color")

    @property
    def min_value(self) -> Optional[float]:
        """Lower bound for ``data-bar`` normalisation, or ``None``."""
        raw = _named_cell_v(self._row, "Min")
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @property
    def max_value(self) -> Optional[float]:
        """Upper bound for ``data-bar`` normalisation, or ``None``."""
        raw = _named_cell_v(self._row, "Max")
        if raw is None or raw == "":
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @property
    def rules(self) -> List[Dict[str, str]]:
        """List of ``{'when': str, 'icon'|'color': str}`` rule dicts.

        Stored as ``<Cell N="Rule.<idx>">`` cells with a tiny
        ``key=value|key=value`` mini-encoding (round-trip safe). Empty
        for ``text-callout`` / ``data-bar``.
        """
        out: List[Dict[str, str]] = []
        # Collect (idx, rule_dict) pairs so we keep insertion order
        # even when the row's cells are reshuffled by an external editor.
        pairs: List[Tuple[int, Dict[str, str]]] = []
        for cell in self._row.cell_lst:
            n = cell.get("N") or ""
            if not n.startswith("Rule."):
                continue
            try:
                idx = int(n.split(".", 1)[1])
            except ValueError:
                continue
            raw = cell.get("V") or ""
            pairs.append((idx, _decode_rule(raw)))
        pairs.sort(key=lambda pair: pair[0])
        for _, rule in pairs:
            out.append(rule)
        return out

    @property
    def element(self):
        """The underlying ``<Row>`` element (escape hatch)."""
        return self._row

    def __repr__(self) -> str:
        return (
            f"DataGraphicSpec(field={self.field!r}, kind={self.kind!r}, "
            f"position={self.position!r})"
        )


# ---------------------------------------------------------------------------
# Rule encoding — tiny ``k=v|k=v`` round-trip-safe mini-format.
# ---------------------------------------------------------------------------


def _encode_rule(rule: Mapping[str, Any]) -> str:
    """Encode *rule* as ``k=v|k=v``.

    Skips empty / missing values. Keys with ``|`` or ``=`` in them are
    not supported (would break the encoding); the helper raises
    :class:`ValueError` so the caller catches the bad input early.
    """
    parts: List[str] = []
    for key, value in rule.items():
        if value is None:
            continue
        s_key = str(key)
        s_val = str(value)
        if "|" in s_key or "=" in s_key:
            raise ValueError(
                "rule keys may not contain '|' or '=': %r" % s_key
            )
        # ``|`` in values is escaped as ``\|`` so the round-trip keeps
        # multi-segment text values (e.g. an exception message) intact.
        s_val = s_val.replace("\\", "\\\\").replace("|", "\\|")
        parts.append(f"{s_key}={s_val}")
    return "|".join(parts)


def _decode_rule(raw: str) -> Dict[str, str]:
    """Inverse of :func:`_encode_rule`."""
    out: Dict[str, str] = {}
    if not raw:
        return out
    # Walk the string char-by-char to honour ``\|`` escape sequences.
    segments: List[str] = []
    buf: List[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            buf.append(raw[i + 1])
            i += 2
            continue
        if ch == "|":
            segments.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    for segment in segments:
        if "=" not in segment:
            continue
        key, _, value = segment.partition("=")
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# Rule evaluation — restricted Python expressions over the row dict.
# ---------------------------------------------------------------------------


_ALLOWED_EXPR_BUILTINS = {
    "abs": abs,
    "min": min,
    "max": max,
    "len": len,
    "True": True,
    "False": False,
    "None": None,
}


def _evaluate_when(expression: str, row: Mapping[str, Any]) -> bool:
    """Evaluate a ``when`` rule expression against *row*.

    Uses :func:`eval` with the row's columns exposed as locals and a
    restricted globals dict (no ``__builtins__`` beyond the small
    explicit allowlist). Callers control the expression strings, so
    this is a convenience evaluator, not a security boundary.
    Returns ``False`` on any evaluation error.
    """
    if not expression:
        return False
    try:
        # Restricted globals: no builtins beyond the small explicit set.
        return bool(
            eval(  # noqa: S307 - intentional restricted-eval
                expression,
                {"__builtins__": _ALLOWED_EXPR_BUILTINS},
                dict(row),
            )
        )
    except Exception:  # noqa: BLE001 — defensive: rule errors must not crash refresh
        return False


# ---------------------------------------------------------------------------
# DataSource — one CSV-backed source row collection on a document.
# ---------------------------------------------------------------------------


class DataSource:
    """A CSV-backed external-data source on a Visio document.

    Wraps a ``<Row T="Source">`` row in the document's
    ``<Section N="DataSources">`` plus an in-memory snapshot of the
    parsed CSV. Construct indirectly via
    :meth:`Page.add_data_source`. Excel and SQL sources are explicit
    follow-ups; the v1 surface is CSV-only.

    .. versionadded:: 0.4.0
    """

    def __init__(
        self,
        row,
        document: "VisioDocument",
        collection: "DataSources",
    ) -> None:
        self._row = row
        self._document = document
        self._collection = collection
        # In-memory cache of the parsed CSV. Populated lazily by
        # :meth:`refresh` so construction is cheap even on a missing
        # CSV path; callers see the empty-rowset until the first
        # successful refresh.
        self._rows: List[Dict[str, str]] = []
        self._columns: List[str] = []
        # Per-graphic spec rows live as nested ``<Row T="Graphic">``
        # entries inside the source row's ``<Section N="DataSources">``
        # child — see :attr:`_specs_section`.

    # -- identity --------------------------------------------------------

    @property
    def id(self) -> int:
        """The source's document-scoped id (``Row/@IX``)."""
        raw = self._row.get("IX")
        if raw is None:
            return 0
        try:
            return int(raw)
        except ValueError:
            return 0

    @property
    def name(self) -> Optional[str]:
        """Human-friendly name (``Row/@N``); typically the CSV file basename."""
        return self._row.get("N")

    @property
    def path(self) -> Optional[str]:
        """The on-disk CSV path stored on this source."""
        return _named_cell_v(self._row, "Path")

    @property
    def key_column(self) -> Optional[str]:
        """The default key-column declared on :meth:`Page.add_data_source`.

        ``None`` until the first :meth:`Shape.bind_to_row` call records
        a key column. Used by :meth:`refresh` to look up rows by their
        natural key when callers don't override per binding.
        """
        return _named_cell_v(self._row, "KeyColumn")

    @property
    def columns(self) -> List[str]:
        """Column names from the most recent successful CSV read."""
        return list(self._columns)

    @property
    def rows(self) -> List[Dict[str, str]]:
        """In-memory snapshot of the CSV rows.

        A list of column-name → value dicts in source order. Empty
        until :meth:`refresh` has run successfully.
        """
        return list(self._rows)

    # -- spec listing ----------------------------------------------------

    def _parent_section(self):
        """Return the ``<Section N="DataSources">`` this row lives inside.

        Spec rows live as **sibling** ``<Row T="Graphic">`` entries on
        the same section, linked back to this source via a
        ``<Cell N="Source" V="<source-id>">`` cell. CT_Row carries no
        ``section`` child in the Visio schema, so we deliberately keep
        the spec rows flat — siblings of the source row — rather than
        forcing a schema change to nest them.
        """
        return _sources_section(self._document._element)

    @property
    def graphics(self) -> List[DataGraphicSpec]:
        """Every :class:`DataGraphicSpec` declared on this source, in order."""
        section = self._parent_section()
        if section is None:
            return []
        out: List[DataGraphicSpec] = []
        for row in section.row_lst:
            if row.get("T") != _ROW_T_GRAPHIC:
                continue
            owner = _named_cell_v(row, "Source")
            if owner != str(self.id):
                continue
            out.append(DataGraphicSpec(row, self))
        return out

    def __iter__(self) -> Iterator[DataGraphicSpec]:
        return iter(self.graphics)

    def __len__(self) -> int:
        return len(self.graphics)

    # -- authoring -------------------------------------------------------

    def add_data_graphic(
        self,
        field: str,
        kind: str,
        *,
        rules: Optional[Iterable[Mapping[str, Any]]] = None,
        min: Optional[float] = None,  # noqa: A002 - matches issue snippet
        max: Optional[float] = None,  # noqa: A002 - matches issue snippet
        color: Optional[str] = None,
        position: Optional[str] = None,
    ) -> DataGraphicSpec:
        """Declare a new visual graphic for this source.

        :param field: The CSV column the graphic reads from (e.g.
            ``"Status"`` or ``"CPU"``).
        :param kind: One of ``text-callout`` / ``icon-set`` /
            ``data-bar`` / ``color-by-value`` (also exposed as the
            ``GRAPHIC_KIND_*`` constants on this module).
        :param rules: For ``icon-set`` and ``color-by-value``, an
            iterable of ``{'when': "<expr>", 'icon': "..."}`` /
            ``{'when': "<expr>", 'color': "#hhhhhh"}`` dicts. Rules
            are evaluated in order on each :meth:`refresh`; the first
            match wins. Ignored for ``text-callout`` / ``data-bar``.
        :param min: Lower bound for ``data-bar`` normalisation. Defaults
            to the smallest value seen in *field* across the rowset.
        :param max: Upper bound for ``data-bar`` normalisation. Defaults
            to the largest value seen in *field* across the rowset.
        :param color: Theme / hex colour token used by ``data-bar``
            (the bar's fill) and as the ``color-by-value`` default
            when no rule matches.
        :param position: Free-form position hint surfaced to renderers
            (``"top"`` / ``"bottom-right"`` / …). Stored verbatim.
        :raises ValueError: when *kind* is not one of the supported
            graphic kinds.

        Returns the newly-created :class:`DataGraphicSpec` so callers
        can fluently chain inspection / further refinement.
        """
        if kind not in _VALID_KINDS:
            raise ValueError(
                "data-graphic kind must be one of %s, got %r"
                % (", ".join(_VALID_KINDS), kind)
            )
        section = _get_or_add_sources_section(self._document._element)
        row = section._add_row()
        row.set("N", str(field))
        row.set("T", _ROW_T_GRAPHIC)
        # Allocate a section-scoped ``@IX`` that's globally unique
        # across every row in the section (source + graphic rows
        # combined). Visio uses ``Row/@IX`` as the row's ordinal
        # within its section so even though the @T tells the kinds
        # apart, a unique IX per row is still expected for round-trip
        # safety.
        used = set()
        for r in section.row_lst:
            if r is row:
                continue
            try:
                used.add(int(r.get("IX") or "-1"))
            except ValueError:
                continue
        next_ix = 1
        while next_ix in used:
            next_ix += 1
        row.set("IX", str(next_ix))
        # Link this graphic-spec row back to the owning source row.
        _set_named_cell_v(row, "Source", str(self.id))
        _set_named_cell_v(row, "Kind", kind)
        if position is not None:
            _set_named_cell_v(row, "Position", position)
        if color is not None:
            _set_named_cell_v(row, "Color", color)
        if min is not None:
            _set_named_cell_v(row, "Min", _fmt_num(min))
        if max is not None:
            _set_named_cell_v(row, "Max", _fmt_num(max))
        if rules is not None:
            for idx, rule in enumerate(rules):
                _set_named_cell_v(row, f"Rule.{idx}", _encode_rule(rule))
        return DataGraphicSpec(row, self)

    # -- CSV loading -----------------------------------------------------

    def _read_csv(self) -> Tuple[List[str], List[Dict[str, str]]]:
        """Read the source's CSV and return (columns, rows).

        On a missing file or empty CSV, returns ``([], [])`` rather
        than raising — callers that care about the difference can
        check :attr:`path` and the filesystem before calling.
        """
        path = self.path
        if path is None or not os.path.exists(path):
            return ([], [])
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = list(reader.fieldnames or [])
            rows = [
                {k: (v if v is not None else "") for k, v in row.items()}
                for row in reader
            ]
        return (columns, rows)

    # -- shape lookup ----------------------------------------------------

    def _row_for_key(self, key_column: str, key_value: str) -> Optional[Dict[str, str]]:
        """Return the first row whose *key_column* equals *key_value*."""
        for row in self._rows:
            if row.get(key_column) == key_value:
                return row
        return None

    def _bound_shapes(self) -> List[Tuple["Shape", str]]:
        """Yield every ``(shape, key)`` pair bound to this source.

        Walks every page of the document and returns the shapes whose
        ``<Cell N="DataSourceBinding" V="<id>!<key>">`` cell points at
        this source.
        """
        out: List[Tuple["Shape", str]] = []
        prefix = f"{self.id}{_BINDING_SEP}"
        for page in self._document.pages:
            for shape in page.shapes:
                v = _named_cell_v(shape._element, _BINDING_CELL)
                if v is None or not v.startswith(prefix):
                    continue
                out.append((shape, v[len(prefix):]))
        return out

    # -- refresh ---------------------------------------------------------

    def refresh(self) -> int:
        """Re-read the CSV and update every shape bound to this source.

        Returns the number of shapes that were updated. A shape with a
        binding key that no longer matches a row in the freshly-read
        CSV is left in place (its overlay sentinels are cleared so a
        stale callout doesn't survive the refresh).

        :class:`FileNotFoundError`-style failures are not propagated —
        a missing CSV simply yields zero rows and clears every overlay
        on every bound shape. Callers that need to distinguish "no
        rows" from "no file" should ``os.path.exists(ds.path)`` first.

        .. versionadded:: 0.4.0
        """
        columns, rows = self._read_csv()
        self._columns = columns
        self._rows = rows
        # Build a column → values map once so the data-bar normaliser
        # doesn't re-scan the rowset for every spec / shape pair.
        numeric_cache: Dict[str, Tuple[float, float]] = {}
        specs = self.graphics
        bound = self._bound_shapes()
        updated = 0
        for shape, key in bound:
            key_col = self.key_column
            row = self._row_for_key(key_col, key) if key_col else None
            # Always clear overlay cells before re-applying so a stale
            # callout from a previous refresh doesn't cling to a shape
            # whose key no longer matches a row.
            for cell_name in (_CALLOUT_CELL, _ICON_CELL, _BAR_CELL):
                _set_named_cell_v(shape._element, cell_name, None)
            if row is None:
                continue
            # Mirror the row's columns onto the shape's ShapeData so
            # ``shape.data["CPU"]`` works without an explicit lookup.
            _mirror_row_to_shape_data(shape, row)
            for spec in specs:
                _apply_spec(shape, spec, row, numeric_cache, self._rows)
            updated += 1
        return updated


# ---------------------------------------------------------------------------
# DataSources collection — document-scoped facade.
# ---------------------------------------------------------------------------


class DataSources:
    """Document-scoped collection over every :class:`DataSource`.

    Callers don't normally instantiate :class:`DataSources` directly;
    iterate :attr:`VisioDocument.data_sources` (or
    :attr:`Page.data_sources`, which delegates) instead.

    .. versionadded:: 0.4.0
    """

    def __init__(self, document: "VisioDocument") -> None:
        self._document = document

    def _section(self):
        return _sources_section(self._document._element)

    def _source_rows(self):
        section = self._section()
        if section is None:
            return []
        return [r for r in section.row_lst if r.get("T") == _ROW_T_SOURCE]

    def __iter__(self) -> Iterator[DataSource]:
        for row in self._source_rows():
            yield DataSource(row, self._document, self)

    def __len__(self) -> int:
        return len(self._source_rows())

    def __getitem__(self, idx: int) -> DataSource:
        return list(self)[idx]

    def get(self, source_id: int) -> Optional[DataSource]:
        """Return the source with ``@IX == source_id``, or ``None``."""
        for ds in self:
            if ds.id == source_id:
                return ds
        return None

    def get_by_name(self, name: str) -> Optional[DataSource]:
        """Return the first source whose ``@N`` matches *name*, or ``None``."""
        for ds in self:
            if ds.name == name:
                return ds
        return None

    # -- authoring -------------------------------------------------------

    def add(
        self,
        path: str,
        *,
        name: Optional[str] = None,
        key: Optional[str] = None,
    ) -> DataSource:
        """Create a new :class:`DataSource` rooted on *path*.

        :param path: filesystem path to the CSV. The file is **not**
            read until the first :meth:`DataSource.refresh` — callers
            can declare bindings against a CSV that doesn't exist yet
            (handy for tests that produce the CSV later).
        :param name: human-friendly source name (``Row/@N``). Defaults
            to ``os.path.basename(path)``.
        :param key: default key column for :meth:`Shape.bind_to_row`.
            Stored on the source so individual binding calls don't
            need to repeat it; can be overridden per-binding.

        Source ids are allocated by appending — ids are never reused
        for the lifetime of the document, so a binding stays attached
        to the same source across save / load.
        """
        section = _get_or_add_sources_section(self._document._element)
        row = section._add_row()
        row.set("T", _ROW_T_SOURCE)
        # Allocate the next free source id by scanning existing source
        # rows only — graphic-spec rows share the section but live in a
        # disjoint id space (their @IX is section-scoped, not
        # source-scoped).
        used_source_ids = set()
        used_ix = set()
        for r in section.row_lst:
            if r is row:
                continue
            try:
                used_ix.add(int(r.get("IX") or "-1"))
            except ValueError:
                pass
            if r.get("T") != _ROW_T_SOURCE:
                continue
            try:
                used_source_ids.add(int(r.get("IX") or "-1"))
            except ValueError:
                continue
        # Source IDs are externally visible (they appear in shape
        # binding cells); graphic IXes are not. Pick the first free
        # source id for ``Source/@IX`` *and* ensure it doesn't collide
        # with an existing graphic-row IX in the same section.
        next_id = 0
        while next_id in used_source_ids or next_id in used_ix:
            next_id += 1
        row.set("IX", str(next_id))
        row.set("N", name or os.path.basename(path) or f"source-{next_id}")
        _set_named_cell_v(row, "Path", path)
        if key is not None:
            _set_named_cell_v(row, "KeyColumn", key)
        return DataSource(row, self._document, self)


# ---------------------------------------------------------------------------
# Shape-binding helpers — invoked from Shape.bind_to_row.
# ---------------------------------------------------------------------------


def _bind_shape_to_row(
    shape: "Shape",
    source: DataSource,
    key: str,
    key_column: Optional[str] = None,
) -> None:
    """Attach *shape* to a row in *source* by *key*.

    Writes ``<Cell N="DataSourceBinding" V="<source-id>!<key>">`` on
    the shape and records the key-column on the source if absent.
    Idempotent. *key_column* overrides the source's default key
    column on a per-shape basis (recorded as
    ``<Cell N="DataSourceKeyColumn">``).
    """
    binding = f"{source.id}{_BINDING_SEP}{key}"
    _set_named_cell_v(shape._element, _BINDING_CELL, binding)
    if key_column is not None:
        _set_named_cell_v(
            shape._element, "DataSourceKeyColumn", key_column
        )
        # Promote the column to the source default when the source
        # has none — first-binding-wins, matching the issue snippet's
        # ``shape.bind_to_row(ds, key='ID')`` flow that doesn't
        # re-declare the key column on the source.
        if source.key_column is None:
            _set_named_cell_v(source._row, "KeyColumn", key_column)
    elif source.key_column is None:
        # Default to the column literal itself — the issue snippet's
        # ``key='ID'`` calls bind to the column named ``"ID"`` rather
        # than to a specific row's value-of-ID. Treating *key* as the
        # column name in that case matches the snippet, but a row
        # binding still wins when the source already has a key column.
        _set_named_cell_v(source._row, "KeyColumn", key)
        # In this case, also record the per-shape value as the key
        # column literal — the next refresh will look up the row whose
        # value in *that* column matches the literal we just set.
        _set_named_cell_v(shape._element, "DataSourceKeyColumn", key)


def _shape_binding(shape: "Shape") -> Optional[Tuple[int, str]]:
    """Return ``(source_id, key)`` if *shape* is bound, else ``None``."""
    raw = _named_cell_v(shape._element, _BINDING_CELL)
    if raw is None or _BINDING_SEP not in raw:
        return None
    head, _, tail = raw.partition(_BINDING_SEP)
    try:
        return (int(head), tail)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Apply-to-shape — per-kind dispatch.
# ---------------------------------------------------------------------------


def _mirror_row_to_shape_data(shape: "Shape", row: Mapping[str, str]) -> None:
    """Copy *row*'s columns onto the shape's ShapeData ``<Section N="Property">``.

    For each column we either update the existing ShapeData field's
    raw_value or create a new string-typed field. We never delete
    existing fields the row doesn't carry — that would clobber user-
    authored shape data the source doesn't know about.
    """
    data = shape.data
    for column, value in row.items():
        if column in data:
            # ``__setitem__`` retypes per the existing field; for
            # source-mirrored fields that are typically strings this is
            # a no-op but it ensures numeric fields stay numeric.
            try:
                data[column] = value
            except (TypeError, ValueError):
                # Bad coercion (e.g. a string in a numeric field) —
                # fall back to the raw_value so the refresh still wins.
                data.field(column).raw_value = str(value)
        else:
            data.add_field(column, str(value))


def _apply_text_callout(
    shape: "Shape",
    spec: DataGraphicSpec,
    row: Mapping[str, str],
    *_: Any,
) -> None:
    """Render a text-callout overlay by writing the field value to a sentinel cell."""
    value = row.get(spec.field)
    if value is None:
        return
    _set_named_cell_v(shape._element, _CALLOUT_CELL, str(value))


def _apply_icon_set(
    shape: "Shape",
    spec: DataGraphicSpec,
    row: Mapping[str, str],
    *_: Any,
) -> None:
    """Pick an icon by walking the spec's rules and writing the first match."""
    for rule in spec.rules:
        when = rule.get("when", "")
        if _evaluate_when(when, row):
            icon = rule.get("icon")
            if icon:
                _set_named_cell_v(shape._element, _ICON_CELL, icon)
                return
    # No rule matched — leave the icon cell cleared (set to None).
    _set_named_cell_v(shape._element, _ICON_CELL, None)


def _apply_data_bar(
    shape: "Shape",
    spec: DataGraphicSpec,
    row: Mapping[str, str],
    numeric_cache: Dict[str, Tuple[float, float]],
    all_rows: List[Dict[str, str]],
) -> None:
    """Normalise the field's value into a 0..1 fraction and stash it."""
    raw = row.get(spec.field)
    if raw is None or raw == "":
        return
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return
    lo = spec.min_value
    hi = spec.max_value
    if lo is None or hi is None:
        if spec.field not in numeric_cache:
            values: List[float] = []
            for r in all_rows:
                v = r.get(spec.field)
                if v is None or v == "":
                    continue
                try:
                    values.append(float(v))
                except ValueError:
                    continue
            if values:
                numeric_cache[spec.field] = (min(values), max(values))
            else:
                numeric_cache[spec.field] = (0.0, 1.0)
        cached_lo, cached_hi = numeric_cache[spec.field]
        if lo is None:
            lo = cached_lo
        if hi is None:
            hi = cached_hi
    if hi <= lo:
        # Degenerate range — clamp to zero so we don't divide by zero
        # and don't surface a misleading bar at 100%.
        fraction = 0.0
    else:
        fraction = (value - lo) / (hi - lo)
        fraction = max(0.0, min(1.0, fraction))
    _set_named_cell_v(shape._element, _BAR_CELL, _fmt_num(fraction))


def _apply_color_by_value(
    shape: "Shape",
    spec: DataGraphicSpec,
    row: Mapping[str, str],
    *_: Any,
) -> None:
    """Update ``<Cell N="FillForegnd">`` based on the first matching rule."""
    for rule in spec.rules:
        when = rule.get("when", "")
        if _evaluate_when(when, row):
            colour = rule.get("color") or rule.get("fill")
            if colour:
                _set_named_cell_v(shape._element, _FILL_CELL, colour)
                return
    # No rule matched — fall back to the spec's default colour, if any.
    if spec.color:
        _set_named_cell_v(shape._element, _FILL_CELL, spec.color)


_GRAPHIC_KINDS: Dict[str, Callable[..., None]] = {
    GRAPHIC_KIND_TEXT_CALLOUT: _apply_text_callout,
    GRAPHIC_KIND_ICON_SET: _apply_icon_set,
    GRAPHIC_KIND_DATA_BAR: _apply_data_bar,
    GRAPHIC_KIND_COLOR_BY_VALUE: _apply_color_by_value,
}


def _apply_spec(
    shape: "Shape",
    spec: DataGraphicSpec,
    row: Mapping[str, str],
    numeric_cache: Dict[str, Tuple[float, float]],
    all_rows: List[Dict[str, str]],
) -> None:
    """Dispatch *spec* to the right ``_apply_*`` handler.

    Unknown kinds are silently skipped — they round-trip through the
    section but don't render. This keeps a forward-compatible writer
    from breaking on a kind a future version added.
    """
    handler = _GRAPHIC_KINDS.get(spec.kind)
    if handler is None:
        return
    handler(shape, spec, row, numeric_cache, all_rows)


# ---------------------------------------------------------------------------
# Number formatting — keep the on-disk values short but stable.
# ---------------------------------------------------------------------------


def _fmt_num(value: Union[int, float]) -> str:
    """Return a compact, locale-invariant string for *value*.

    Mirrors the formatting used by :mod:`vsdx.page._fmt` so DataSource
    state stays visually close to Visio-authored numerics on disk.
    """
    if isinstance(value, bool):  # pragma: no cover - bool is int subclass
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if value == int(value):
        return str(int(value))
    return ("%f" % value).rstrip("0").rstrip(".")
