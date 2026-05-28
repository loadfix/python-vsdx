# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""Workbook → Visio dispatcher kit — issue #136.

Turn an ``.xlsx`` data table into a Visio diagram in one call::

    from vsdx.kit.from_workbook import diagram_from_xlsx

    # Hierarchy diagram from a parent/child table
    diagram = diagram_from_xlsx(
        "roster.xlsx",
        sheet="employees",
        kind="org-chart",
        name_col="Name",
        title_col="Title",
        manager_col="Manager",
    )

    # ERD from a "tables" sheet listing column metadata
    diagram = diagram_from_xlsx(
        "schema.xlsx",
        sheet="columns",
        kind="erd",
        table_col="Table",
        column_col="Column",
        type_col="Type",
        constraint_col="Constraint",
    )

    # Generic flow diagram from steps + flows sheets
    diagram = diagram_from_xlsx(
        "process.xlsx",
        kind="process-map",
        steps_sheet="Steps",
        flows_sheet="Flows",
    )

This module is **pure composition**. It reads the named worksheet(s)
via the sibling :mod:`xlsx` library, projects the rows into the shape
each underlying kit builder expects, and delegates straight to
:func:`vsdx.kit.org_chart.build_org_chart`,
:func:`vsdx.kit.erd.erd_from_models`,
:func:`vsdx.kit.process.build_process_map`, or
:func:`vsdx.kit.swim_lanes.build_swim_lane_diagram`. **No new diagram
logic lives here** — this is an adapter, not a renderer.

Supported ``kind`` tokens
-------------------------

* :data:`KIND_ORG_CHART` (``"org-chart"``) — one row per employee,
  ``name_col`` / ``title_col`` / ``manager_col`` / ``photo_col`` /
  ``team_col`` pick the columns; blank ``manager`` cells mark roots.
  Delegates to :func:`vsdx.kit.org_chart.build_org_chart`.
* :data:`KIND_ERD` (``"erd"``) — one row per column;
  ``table_col`` / ``column_col`` / ``type_col`` / ``constraint_col``
  carry the schema. Rows with a shared ``table_col`` value are
  collapsed into a single table. Delegates to
  :func:`vsdx.kit.erd.erd_from_models`.
* :data:`KIND_PROCESS_MAP` (``"process-map"``) — two-sheet layout:
  the *steps* sheet lists ``text_col`` / ``kind_col`` / ``on_col``
  per step; the optional *flows* sheet lists ``from_col`` /
  ``to_col`` per directed edge. Single-sheet usage with the default
  ``flows_sheet=None`` falls back to sequential wiring (consecutive
  steps connected in declaration order). Delegates to
  :func:`vsdx.kit.process.build_process_map`.
* :data:`KIND_SWIM_LANE` (``"swim-lane"``) — same shape as
  ``process-map`` but the *steps* sheet additionally carries a
  ``lane_col``; the lanes themselves come either from
  ``lanes_sheet`` (one lane per row, ``lane_col`` carries the name)
  or are auto-derived from the *steps* sheet preserving first-seen
  order. Delegates to
  :func:`vsdx.kit.swim_lanes.build_swim_lane_diagram`.

Cells whose value is ``None`` or whitespace-only are coerced to
"absent" so a manager-column blank cell behaves identically to an
omitted key in the dict-roster equivalents documented on the four
delegate builders.

Robust column lookup
--------------------

Header rows are read from row 1 (Excel one-based). Column lookups
are case-insensitive and tolerate leading / trailing whitespace —
``"Name"``, ``" name"``, and ``"NAME"`` all resolve to the same
header. When a caller-provided ``*_col`` name does not appear in the
header at all, the loader raises :class:`ValueError` with a message
naming both the expected column and the headers it actually found.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import os
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from vsdx.document import VisioDocument
from vsdx.kit.erd import erd_from_models
from vsdx.kit.org_chart import build_org_chart
from vsdx.kit.process import (
    PROCESS_KIND_TASK,
    PROCESS_STEP_KINDS,
    build_process_map,
)
from vsdx.kit.swim_lanes import (
    SWIM_LANE_KIND_DEFAULT,
    SWIM_LANE_STEP_KINDS,
    build_swim_lane_diagram,
)

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    # `xlsx` is a sibling parent library; we only import its types
    # here so static checkers don't choke on a missing runtime install
    # for callers who never use this module.
    from xlsx.workbook.workbook import Workbook  # noqa: F401


# ---------------------------------------------------------------------------
# Public constants — supported kind tokens
# ---------------------------------------------------------------------------

#: ``kind`` token dispatching to :func:`vsdx.kit.org_chart.build_org_chart`.
KIND_ORG_CHART: str = "org-chart"

#: ``kind`` token dispatching to :func:`vsdx.kit.erd.erd_from_models`.
KIND_ERD: str = "erd"

#: ``kind`` token dispatching to :func:`vsdx.kit.process.build_process_map`.
KIND_PROCESS_MAP: str = "process-map"

#: ``kind`` token dispatching to
#: :func:`vsdx.kit.swim_lanes.build_swim_lane_diagram`.
KIND_SWIM_LANE: str = "swim-lane"

#: Frozen tuple of every recognised ``kind`` token, in canonical order.
DIAGRAM_KINDS: Tuple[str, ...] = (
    KIND_ORG_CHART,
    KIND_ERD,
    KIND_PROCESS_MAP,
    KIND_SWIM_LANE,
)


# ---------------------------------------------------------------------------
# Default column names per kind
# ---------------------------------------------------------------------------

#: Default org-chart column names — match
#: :data:`vsdx.kit.org_chart.DEFAULT_NAME_COL` & friends but at title-case
#: because xlsx headers are conventionally human-readable.
ORG_CHART_DEFAULT_NAME_COL: str = "Name"
ORG_CHART_DEFAULT_TITLE_COL: str = "Title"
ORG_CHART_DEFAULT_MANAGER_COL: str = "Manager"
ORG_CHART_DEFAULT_PHOTO_COL: str = "Photo"
ORG_CHART_DEFAULT_TEAM_COL: str = "Team"

#: Default ERD column names.
ERD_DEFAULT_TABLE_COL: str = "Table"
ERD_DEFAULT_COLUMN_COL: str = "Column"
ERD_DEFAULT_TYPE_COL: str = "Type"
ERD_DEFAULT_CONSTRAINT_COL: str = "Constraint"

#: Default process-map / swim-lane column names.
PROCESS_DEFAULT_TEXT_COL: str = "Text"
PROCESS_DEFAULT_KIND_COL: str = "Kind"
PROCESS_DEFAULT_ON_COL: str = "On"
PROCESS_DEFAULT_FROM_COL: str = "From"
PROCESS_DEFAULT_TO_COL: str = "To"
PROCESS_DEFAULT_LANE_COL: str = "Lane"

#: Default sheet names for the two-sheet process-map / swim-lane layouts.
DEFAULT_STEPS_SHEET: str = "Steps"
DEFAULT_FLOWS_SHEET: str = "Flows"
DEFAULT_LANES_SHEET: str = "Lanes"


# ---------------------------------------------------------------------------
# Workbook loading helpers
# ---------------------------------------------------------------------------


# A workbook source — a filesystem path, an open file-like, or an
# already-loaded ``xlsx.Workbook``. The dispatcher accepts any of the
# three so callers can reuse a workbook across multiple calls without
# paying the parse cost twice.
WorkbookSource = Union[str, "os.PathLike[str]", "Workbook", Any]


def _load_workbook(source: WorkbookSource) -> Any:
    """Return an ``xlsx.Workbook`` from *source*.

    *source* may be:

    * an :class:`os.PathLike` or ``str`` filesystem path — opened via
      :func:`xlsx.load_workbook` in ``data_only=True`` mode so cached
      formula values come through as plain Python scalars rather than
      formula strings;
    * a binary file-like — passed straight to
      :func:`xlsx.load_workbook`;
    * an already-loaded ``xlsx.Workbook`` — returned as-is.

    The :mod:`xlsx` import is deferred to call time so this module
    stays import-light for callers that never touch the dispatcher.
    """
    # Already a Workbook? (Duck-typed — any object exposing a
    # ``.sheetnames`` list and ``__getitem__`` qualifies.) Avoids a
    # hard isinstance check that would force the xlsx import even when
    # the caller has handed us a pre-loaded workbook.
    if hasattr(source, "sheetnames") and hasattr(source, "__getitem__"):
        return source

    try:
        from xlsx import load_workbook  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — install issue
        raise ImportError(
            "diagram_from_xlsx requires the sibling `xlsx` package "
            "(install it with `pip install python-xlsx`)"
        ) from exc

    return load_workbook(source, read_only=True, data_only=True)


def _resolve_sheet(workbook: Any, sheet: Optional[str]) -> Any:
    """Return the worksheet matching *sheet*, or ``workbook.active``."""
    if sheet is None:
        # workbook.active raises if the workbook has no sheets — let it.
        return workbook.active

    sheetnames: Sequence[str] = getattr(workbook, "sheetnames", []) or []
    if sheet in sheetnames:
        return workbook[sheet]

    # Case-insensitive / whitespace-tolerant fallback so callers don't
    # have to mirror Excel's exact casing.
    sheet_norm = sheet.strip().lower()
    for name in sheetnames:
        if isinstance(name, str) and name.strip().lower() == sheet_norm:
            return workbook[name]

    raise ValueError(
        "workbook has no sheet named %r (available sheets: %r)"
        % (sheet, list(sheetnames))
    )


def _normalise_cell(value: Any) -> Optional[str]:
    """Return a stripped ``str`` of *value*, or ``None`` for absent.

    Treats ``None`` and whitespace-only strings as absent so blank
    cells in xlsx behave identically to missing keys in the
    dict-roster equivalents accepted by the kit builders.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def _normalise_header(value: Any) -> str:
    """Return a stripped string for a header cell (empty string when blank)."""
    if value is None:
        return ""
    return str(value).strip()


def _read_rows(
    sheet: Any,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Return ``(headers, rows)`` where *rows* is a list of header→value dicts.

    The first non-empty row of the sheet is treated as the header row.
    Subsequent rows are projected into ``{header: value}`` dicts; cells
    whose column has a blank header are dropped. Trailing fully-empty
    rows are skipped so a workbook with stray formatting on row 50 of
    a 20-row table doesn't yield 30 phantom records.
    """
    headers: List[str] = []
    rows: List[Dict[str, Any]] = []

    iterator = sheet.iter_rows(values_only=True) if _supports_values_only(
        sheet
    ) else _values_only(sheet.iter_rows())

    for row in iterator:
        if not headers:
            # First non-empty row → headers.
            if not any(cell is not None and str(cell).strip() for cell in row):
                continue
            headers = [_normalise_header(c) for c in row]
            continue

        if not any(cell is not None and str(cell).strip() for cell in row):
            # Trailing / interior blank row — skip silently.
            continue

        record: Dict[str, Any] = {}
        for ix, cell in enumerate(row):
            if ix >= len(headers):
                break
            header = headers[ix]
            if not header:
                continue
            record[header] = cell
        rows.append(record)

    return headers, rows


def _supports_values_only(sheet: Any) -> bool:
    """True when ``sheet.iter_rows`` accepts the ``values_only`` kwarg."""
    iter_rows = getattr(sheet, "iter_rows", None)
    if iter_rows is None:
        return False
    code = getattr(iter_rows, "__code__", None)
    if code is None:
        return False
    return "values_only" in code.co_varnames


def _values_only(rows: Iterable[Any]) -> Iterable[Tuple[Any, ...]]:
    """Yield value-tuples from a stream of cell-tuples.

    Fallback for sheets whose ``iter_rows`` lacks a ``values_only``
    flag (older xlsx releases / some streaming proxies).
    """
    for row in rows:
        yield tuple(getattr(c, "value", c) for c in row)


def _resolve_column(
    headers: Sequence[str],
    requested: str,
    *,
    role: str,
) -> str:
    """Return the actual header string matching *requested*.

    Case-insensitive / whitespace-tolerant. Raises :class:`ValueError`
    when no header matches; the message names both the requested
    string and the headers we did find so the caller can fix the
    spelling without bouncing back to Excel.
    """
    if requested in headers:
        return requested
    target = requested.strip().lower()
    for h in headers:
        if h.strip().lower() == target:
            return h
    raise ValueError(
        "%s column %r not found in sheet headers %r"
        % (role, requested, list(headers))
    )


def _optional_column(
    headers: Sequence[str],
    requested: Optional[str],
    *,
    role: str,
    is_default: bool = False,
) -> Optional[str]:
    """Like :func:`_resolve_column` but returns ``None`` when *requested* is None.

    When *is_default* is ``True`` the requested name comes from a
    builder default (e.g. ``photo_col=ORG_CHART_DEFAULT_PHOTO_COL``).
    A missing header in that case is silently treated as "no such
    column" — callers who didn't ask for the column shouldn't be
    forced to spell out ``photo_col=None``. When *is_default* is
    ``False`` the caller has explicitly named the column, so a
    missing header raises (typo > silent drop).
    """
    if requested is None:
        return None
    if is_default and requested not in headers:
        target = requested.strip().lower()
        if not any(
            isinstance(h, str) and h.strip().lower() == target for h in headers
        ):
            return None
    return _resolve_column(headers, requested, role=role)


# ---------------------------------------------------------------------------
# Org-chart row → employee dict
# ---------------------------------------------------------------------------


def _rows_to_employees(
    rows: Sequence[Mapping[str, Any]],
    *,
    headers: Sequence[str],
    name_col: str,
    title_col: Optional[str],
    manager_col: Optional[str],
    photo_col: Optional[str],
    team_col: Optional[str],
    defaulted: Iterable[str] = (),
) -> List[Dict[str, str]]:
    """Project sheet rows into the ``employees`` shape build_org_chart expects."""
    defaulted_set = set(defaulted)
    name_h = _resolve_column(headers, name_col, role="org-chart name")
    title_h = _optional_column(
        headers, title_col, role="org-chart title",
        is_default="title_col" in defaulted_set,
    )
    manager_h = _optional_column(
        headers, manager_col, role="org-chart manager",
        is_default="manager_col" in defaulted_set,
    )
    photo_h = _optional_column(
        headers, photo_col, role="org-chart photo",
        is_default="photo_col" in defaulted_set,
    )
    team_h = _optional_column(
        headers, team_col, role="org-chart team",
        is_default="team_col" in defaulted_set,
    )

    employees: List[Dict[str, str]] = []
    for row in rows:
        emp: Dict[str, str] = {}
        for src_h, dst_key in (
            (name_h, "name"),
            (title_h, "title"),
            (manager_h, "manager"),
            (photo_h, "photo"),
            (team_h, "team"),
        ):
            if src_h is None:
                continue
            normed = _normalise_cell(row.get(src_h))
            if normed is not None:
                emp[dst_key] = normed
        if "name" in emp:
            employees.append(emp)
    return employees


def _diagram_from_org_chart(
    workbook: Any,
    *,
    sheet: Optional[str],
    name_col: str,
    title_col: Optional[str],
    manager_col: Optional[str],
    photo_col: Optional[str],
    team_col: Optional[str],
    builder_kwargs: Mapping[str, Any],
    defaulted: Iterable[str] = (),
) -> VisioDocument:
    ws = _resolve_sheet(workbook, sheet)
    headers, rows = _read_rows(ws)
    if not rows:
        raise ValueError(
            "org-chart sheet %r contains no data rows under its header"
            % (sheet or getattr(ws, "title", "<active>"))
        )
    employees = _rows_to_employees(
        rows,
        headers=headers,
        name_col=name_col,
        title_col=title_col,
        manager_col=manager_col,
        photo_col=photo_col,
        team_col=team_col,
        defaulted=defaulted,
    )
    if not employees:
        raise ValueError(
            "org-chart sheet has no rows with a non-empty %r cell" % name_col
        )
    return build_org_chart(employees=employees, **builder_kwargs)


# ---------------------------------------------------------------------------
# ERD row → tables mapping
# ---------------------------------------------------------------------------


def _rows_to_tables(
    rows: Sequence[Mapping[str, Any]],
    *,
    headers: Sequence[str],
    table_col: str,
    column_col: str,
    type_col: Optional[str],
    constraint_col: Optional[str],
    defaulted: Iterable[str] = (),
) -> Dict[str, Dict[str, Any]]:
    """Project sheet rows into the ``tables`` shape erd_from_models expects."""
    defaulted_set = set(defaulted)
    table_h = _resolve_column(headers, table_col, role="erd table")
    column_h = _resolve_column(headers, column_col, role="erd column")
    type_h = _optional_column(
        headers, type_col, role="erd type",
        is_default="type_col" in defaulted_set,
    )
    constraint_h = _optional_column(
        headers, constraint_col, role="erd constraint",
        is_default="constraint_col" in defaulted_set,
    )

    tables: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        table_name = _normalise_cell(row.get(table_h))
        col_name = _normalise_cell(row.get(column_h))
        if table_name is None or col_name is None:
            # Rows lacking either of the two required keys aren't
            # actionable — skip rather than crash the whole import.
            continue
        col_type = (
            _normalise_cell(row.get(type_h)) if type_h is not None else None
        ) or "text"
        constraint = (
            _normalise_cell(row.get(constraint_h))
            if constraint_h is not None
            else None
        ) or ""
        spec = tables.setdefault(table_name, {"columns": []})
        spec["columns"].append((col_name, col_type, constraint))
    return tables


def _diagram_from_erd(
    workbook: Any,
    *,
    sheet: Optional[str],
    table_col: str,
    column_col: str,
    type_col: Optional[str],
    constraint_col: Optional[str],
    builder_kwargs: Mapping[str, Any],
    defaulted: Iterable[str] = (),
) -> VisioDocument:
    ws = _resolve_sheet(workbook, sheet)
    headers, rows = _read_rows(ws)
    if not rows:
        raise ValueError(
            "erd sheet %r contains no data rows under its header"
            % (sheet or getattr(ws, "title", "<active>"))
        )
    tables = _rows_to_tables(
        rows,
        headers=headers,
        table_col=table_col,
        column_col=column_col,
        type_col=type_col,
        constraint_col=constraint_col,
        defaulted=defaulted,
    )
    if not tables:
        raise ValueError(
            "erd sheet has no rows with both a %r and %r cell populated"
            % (table_col, column_col)
        )
    return erd_from_models(tables=tables, **builder_kwargs)


# ---------------------------------------------------------------------------
# Process-map row → steps + flows
# ---------------------------------------------------------------------------


def _rows_to_steps(
    rows: Sequence[Mapping[str, Any]],
    *,
    headers: Sequence[str],
    text_col: str,
    kind_col: Optional[str],
    on_col: Optional[str],
    lane_col: Optional[str] = None,
    default_kind: str,
    valid_kinds: Sequence[str],
    defaulted: Iterable[str] = (),
) -> List[Dict[str, str]]:
    """Project sheet rows into the ``steps`` shape build_process_map expects."""
    defaulted_set = set(defaulted)
    text_h = _resolve_column(headers, text_col, role="process-map text")
    kind_h = _optional_column(
        headers, kind_col, role="process-map kind",
        is_default="kind_col" in defaulted_set,
    )
    on_h = _optional_column(
        headers, on_col, role="process-map on",
        is_default="on_col" in defaulted_set,
    )
    lane_h = _optional_column(
        headers, lane_col, role="process-map lane",
        is_default="lane_col" in defaulted_set,
    )

    steps: List[Dict[str, str]] = []
    for row in rows:
        text = _normalise_cell(row.get(text_h))
        if text is None:
            continue
        kind = (
            _normalise_cell(row.get(kind_h)) if kind_h is not None else None
        ) or default_kind
        if kind not in valid_kinds:
            raise ValueError(
                "process-map step %r has unrecognised kind %r — expected one "
                "of %r" % (text, kind, tuple(valid_kinds))
            )
        record: Dict[str, str] = {"text": text, "kind": kind}
        if on_h is not None:
            on = _normalise_cell(row.get(on_h))
            if on is not None:
                record["on"] = on
        if lane_h is not None:
            lane = _normalise_cell(row.get(lane_h))
            if lane is not None:
                record["lane"] = lane
        steps.append(record)
    return steps


def _rows_to_flows(
    rows: Sequence[Mapping[str, Any]],
    *,
    headers: Sequence[str],
    from_col: str,
    to_col: str,
) -> List[Tuple[str, str]]:
    """Project sheet rows into the ``flows`` shape the kit builders expect."""
    from_h = _resolve_column(headers, from_col, role="flows from")
    to_h = _resolve_column(headers, to_col, role="flows to")

    flows: List[Tuple[str, str]] = []
    for row in rows:
        a = _normalise_cell(row.get(from_h))
        b = _normalise_cell(row.get(to_h))
        if a is None or b is None:
            continue
        flows.append((a, b))
    return flows


def _diagram_from_process_map(
    workbook: Any,
    *,
    steps_sheet: Optional[str],
    flows_sheet: Optional[str],
    text_col: str,
    kind_col: Optional[str],
    on_col: Optional[str],
    from_col: str,
    to_col: str,
    builder_kwargs: Mapping[str, Any],
    defaulted: Iterable[str] = (),
) -> VisioDocument:
    ws = _resolve_sheet(workbook, steps_sheet)
    headers, rows = _read_rows(ws)
    if not rows:
        raise ValueError(
            "process-map steps sheet %r contains no data rows under its "
            "header" % (steps_sheet or getattr(ws, "title", "<active>"))
        )
    steps = _rows_to_steps(
        rows,
        headers=headers,
        text_col=text_col,
        kind_col=kind_col,
        on_col=on_col,
        default_kind=PROCESS_KIND_TASK,
        valid_kinds=PROCESS_STEP_KINDS,
        defaulted=defaulted,
    )
    if not steps:
        raise ValueError(
            "process-map steps sheet has no rows with a non-empty %r cell"
            % text_col
        )

    flows: Optional[List[Tuple[str, str]]] = None
    if flows_sheet is not None:
        flows_ws = _resolve_sheet(workbook, flows_sheet)
        flows_headers, flow_rows = _read_rows(flows_ws)
        if flow_rows:
            flows = _rows_to_flows(
                flow_rows,
                headers=flows_headers,
                from_col=from_col,
                to_col=to_col,
            )

    title = builder_kwargs.get("title", "")
    if not isinstance(title, str):
        raise TypeError(
            "title must be a str (got %r)" % type(title).__name__
        )

    return build_process_map(
        title=title,
        steps=steps,
        flows=flows,
        **{k: v for k, v in builder_kwargs.items() if k != "title"},
    )


def _diagram_from_swim_lane(
    workbook: Any,
    *,
    steps_sheet: Optional[str],
    flows_sheet: Optional[str],
    lanes_sheet: Optional[str],
    text_col: str,
    kind_col: Optional[str],
    lane_col: str,
    from_col: str,
    to_col: str,
    builder_kwargs: Mapping[str, Any],
    defaulted: Iterable[str] = (),
) -> VisioDocument:
    ws = _resolve_sheet(workbook, steps_sheet)
    headers, rows = _read_rows(ws)
    if not rows:
        raise ValueError(
            "swim-lane steps sheet %r contains no data rows under its header"
            % (steps_sheet or getattr(ws, "title", "<active>"))
        )
    steps = _rows_to_steps(
        rows,
        headers=headers,
        text_col=text_col,
        kind_col=kind_col,
        on_col=None,
        lane_col=lane_col,
        default_kind=SWIM_LANE_KIND_DEFAULT,
        valid_kinds=SWIM_LANE_STEP_KINDS,
        defaulted=defaulted,
    )
    if not steps:
        raise ValueError(
            "swim-lane steps sheet has no rows with a non-empty %r cell"
            % text_col
        )

    # Lane discovery: explicit sheet wins over auto-derive from steps.
    lanes: List[str] = []
    if lanes_sheet is not None:
        lanes_ws = _resolve_sheet(workbook, lanes_sheet)
        lanes_headers, lane_rows = _read_rows(lanes_ws)
        lane_h = _resolve_column(lanes_headers, lane_col, role="swim-lane name")
        for row in lane_rows:
            name = _normalise_cell(row.get(lane_h))
            if name is not None and name not in lanes:
                lanes.append(name)
    if not lanes:
        for step in steps:
            if "lane" not in step:
                raise ValueError(
                    "swim-lane step %r has no %r cell — every step must "
                    "carry a lane label when no lanes_sheet is provided"
                    % (step["text"], lane_col)
                )
            if step["lane"] not in lanes:
                lanes.append(step["lane"])

    flows: List[Tuple[str, str]] = []
    if flows_sheet is not None:
        flows_ws = _resolve_sheet(workbook, flows_sheet)
        flows_headers, flow_rows = _read_rows(flows_ws)
        if flow_rows:
            flows = _rows_to_flows(
                flow_rows,
                headers=flows_headers,
                from_col=from_col,
                to_col=to_col,
            )

    title = builder_kwargs.get("title", "")
    if not isinstance(title, str):
        raise TypeError(
            "title must be a str (got %r)" % type(title).__name__
        )

    return build_swim_lane_diagram(
        title=title,
        lanes=lanes,
        steps=steps,
        flows=flows,
        **{k: v for k, v in builder_kwargs.items() if k != "title"},
    )


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


# Recognised builder-kwargs across all kinds — anything else passed via
# **kwargs is treated as a column-name override and routed to the
# matching projector. Keeping this set explicit (rather than inferring
# from the kit builder signatures) lets us preserve the dispatcher's
# kwargs surface across kit-builder churn.
_ORG_CHART_BUILDER_KWARGS = {
    "title",
    "page_width",
    "page_height",
    "page_name",
    "routing",
    "spacing",
}
_ERD_BUILDER_KWARGS = {
    "title",
    "page_width",
    "page_height",
    "page_name",
    "routing",
    "spacing",
    "layout",
}
_PROCESS_BUILDER_KWARGS = {
    "title",
    "page_width",
    "page_height",
    "page_name",
    "routing",
}


# Sentinel used to distinguish "caller passed nothing" from "caller
# explicitly named the default column". When a caller uses the
# defaulted name and the workbook's header doesn't include it, we
# silently skip the column rather than raising — but when the caller
# typed the column name in their call, a missing header IS an error.
_USE_DEFAULT = object()


def diagram_from_xlsx(
    workbook: WorkbookSource,
    *,
    sheet: Optional[str] = None,
    kind: str,
    # Org-chart column overrides
    name_col: Any = _USE_DEFAULT,
    title_col: Any = _USE_DEFAULT,
    manager_col: Any = _USE_DEFAULT,
    photo_col: Any = _USE_DEFAULT,
    team_col: Any = _USE_DEFAULT,
    # ERD column overrides
    table_col: Any = _USE_DEFAULT,
    column_col: Any = _USE_DEFAULT,
    type_col: Any = _USE_DEFAULT,
    constraint_col: Any = _USE_DEFAULT,
    # Process-map / swim-lane column + sheet overrides
    steps_sheet: Optional[str] = None,
    flows_sheet: Optional[str] = None,
    lanes_sheet: Optional[str] = None,
    text_col: Any = _USE_DEFAULT,
    kind_col: Any = _USE_DEFAULT,
    on_col: Any = _USE_DEFAULT,
    from_col: Any = _USE_DEFAULT,
    to_col: Any = _USE_DEFAULT,
    lane_col: Any = _USE_DEFAULT,
    # Builder-pass-through (title, page sizing, routing, etc.)
    **builder_kwargs: Any,
) -> VisioDocument:
    """Read an xlsx workbook and author the matching Visio diagram.

    :param workbook: filesystem path / file-like / pre-loaded
        ``xlsx.Workbook``. Opened in ``read_only=True, data_only=True``
        mode when a path is given.
    :param sheet: name of the worksheet to read for the *single-sheet*
        kinds (``org-chart`` / ``erd``). Defaults to the workbook's
        active sheet.
    :param kind: one of :data:`DIAGRAM_KINDS` —
        :data:`KIND_ORG_CHART`, :data:`KIND_ERD`,
        :data:`KIND_PROCESS_MAP`, :data:`KIND_SWIM_LANE`. Selects the
        downstream builder.

    Org-chart parameters (used when ``kind="org-chart"``):

    :param name_col: header of the employee-name column. Default:
        ``"Name"``.
    :param title_col: header of the job-title column. Pass ``None`` to
        skip. Default: ``"Title"``.
    :param manager_col: header of the manager-name column. Pass
        ``None`` to skip (every employee renders as a root). Default:
        ``"Manager"``.
    :param photo_col: header of the photo-URL column. Default:
        ``"Photo"``. Cells are recorded on each box's shape data.
    :param team_col: header of the team-label column. Default:
        ``"Team"``.

    ERD parameters (used when ``kind="erd"``):

    :param table_col: header of the table-name column. Default:
        ``"Table"``. Rows with the same value collapse into one table.
    :param column_col: header of the column-name column. Default:
        ``"Column"``.
    :param type_col: header of the column-type column. Default:
        ``"Type"``. Rows missing a type fall back to ``"text"``.
    :param constraint_col: header of the constraint-suffix column.
        Default: ``"Constraint"``. Empty cells emit no constraint;
        ``"PK"`` / ``"UNIQUE"`` / ``"NOT NULL"`` / ``"FK->table.col"``
        are the recognised tokens (see :mod:`vsdx.kit.erd`).

    Process-map / swim-lane parameters (used when
    ``kind="process-map"`` or ``kind="swim-lane"``):

    :param steps_sheet: name of the steps worksheet. Defaults to
        ``sheet`` (when given) or the workbook's active sheet.
    :param flows_sheet: name of the optional flows worksheet. When
        ``None`` (the default), the process-map kit's auto-sequential
        wiring picks up — consecutive steps are connected in
        declaration order.
    :param lanes_sheet: name of the optional lanes worksheet
        (swim-lane only). When ``None``, lanes are auto-derived from
        the steps sheet preserving first-seen order.
    :param text_col: header of the step-label column. Default:
        ``"Text"``.
    :param kind_col: header of the per-step ``kind`` column. Default:
        ``"Kind"``. Rows missing a kind fall back to ``"task"``
        (process-map) / ``"step"`` (swim-lane).
    :param on_col: header of the optional ``"on"`` decision-branch
        column (process-map only). Default: ``"On"``.
    :param from_col: header of the source-step column on the flows
        sheet. Default: ``"From"``.
    :param to_col: header of the target-step column on the flows
        sheet. Default: ``"To"``.
    :param lane_col: header of the lane-name column (swim-lane only).
        Default: ``"Lane"``.

    Any remaining keyword arguments — ``title`` / ``page_width`` /
    ``page_height`` / ``page_name`` / ``routing`` / ``spacing`` /
    ``layout`` — are forwarded verbatim to the underlying builder.
    See the four delegate builders for the per-kind kwargs they
    accept.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises ImportError: when the sibling ``xlsx`` package is not
        installed and *workbook* is a path.
    :raises ValueError: when *kind* is unrecognised, when a named
        sheet is missing, when a named column is missing, when the
        chosen sheet has no data rows, or when an underlying kit
        builder rejects the projected input (see each delegate's
        ``raises`` for the full list).
    :raises TypeError: when *kind* is not a ``str`` or *workbook* is
        not a path / file-like / Workbook.

    .. versionadded:: 0.4.0
    """
    if not isinstance(kind, str):
        raise TypeError(
            "kind must be a str (got %r)" % type(kind).__name__
        )
    if kind not in DIAGRAM_KINDS:
        raise ValueError(
            "kind=%r must be one of %r" % (kind, DIAGRAM_KINDS)
        )

    wb = _load_workbook(workbook)

    # Resolve every column-kwarg sentinel into a concrete value plus a
    # parallel set naming the kwargs that came from the default. The
    # projector layer uses that set to decide whether a missing header
    # is "silently skip" or "raise".
    def _resolve(value: Any, default: Optional[str], key: str) -> Tuple[Optional[str], bool]:
        if value is _USE_DEFAULT:
            return default, True
        return value, False

    name_col_v, name_def = _resolve(
        name_col, ORG_CHART_DEFAULT_NAME_COL, "name_col"
    )
    title_col_v, title_def = _resolve(
        title_col, ORG_CHART_DEFAULT_TITLE_COL, "title_col"
    )
    manager_col_v, manager_def = _resolve(
        manager_col, ORG_CHART_DEFAULT_MANAGER_COL, "manager_col"
    )
    photo_col_v, photo_def = _resolve(
        photo_col, ORG_CHART_DEFAULT_PHOTO_COL, "photo_col"
    )
    team_col_v, team_def = _resolve(
        team_col, ORG_CHART_DEFAULT_TEAM_COL, "team_col"
    )
    table_col_v, _ = _resolve(table_col, ERD_DEFAULT_TABLE_COL, "table_col")
    column_col_v, _ = _resolve(column_col, ERD_DEFAULT_COLUMN_COL, "column_col")
    type_col_v, type_def = _resolve(
        type_col, ERD_DEFAULT_TYPE_COL, "type_col"
    )
    constraint_col_v, constraint_def = _resolve(
        constraint_col, ERD_DEFAULT_CONSTRAINT_COL, "constraint_col"
    )
    text_col_v, _ = _resolve(text_col, PROCESS_DEFAULT_TEXT_COL, "text_col")
    kind_col_v, kind_def = _resolve(
        kind_col, PROCESS_DEFAULT_KIND_COL, "kind_col"
    )
    on_col_v, on_def = _resolve(on_col, PROCESS_DEFAULT_ON_COL, "on_col")
    from_col_v, _ = _resolve(from_col, PROCESS_DEFAULT_FROM_COL, "from_col")
    to_col_v, _ = _resolve(to_col, PROCESS_DEFAULT_TO_COL, "to_col")
    lane_col_v, lane_def = _resolve(
        lane_col, PROCESS_DEFAULT_LANE_COL, "lane_col"
    )

    if kind == KIND_ORG_CHART:
        forwarded = _filter_kwargs(
            builder_kwargs, allowed=_ORG_CHART_BUILDER_KWARGS, kind=kind
        )
        defaulted: List[str] = []
        if title_def:
            defaulted.append("title_col")
        if manager_def:
            defaulted.append("manager_col")
        if photo_def:
            defaulted.append("photo_col")
        if team_def:
            defaulted.append("team_col")
        if name_col_v is None:
            raise ValueError("name_col must not be None for kind='org-chart'")
        return _diagram_from_org_chart(
            wb,
            sheet=sheet,
            name_col=name_col_v,
            title_col=title_col_v,
            manager_col=manager_col_v,
            photo_col=photo_col_v,
            team_col=team_col_v,
            builder_kwargs=forwarded,
            defaulted=defaulted,
        )

    if kind == KIND_ERD:
        forwarded = _filter_kwargs(
            builder_kwargs, allowed=_ERD_BUILDER_KWARGS, kind=kind
        )
        defaulted = []
        if type_def:
            defaulted.append("type_col")
        if constraint_def:
            defaulted.append("constraint_col")
        if table_col_v is None or column_col_v is None:
            raise ValueError(
                "table_col and column_col must not be None for kind='erd'"
            )
        return _diagram_from_erd(
            wb,
            sheet=sheet,
            table_col=table_col_v,
            column_col=column_col_v,
            type_col=type_col_v,
            constraint_col=constraint_col_v,
            builder_kwargs=forwarded,
            defaulted=defaulted,
        )

    if kind == KIND_PROCESS_MAP:
        forwarded = _filter_kwargs(
            builder_kwargs, allowed=_PROCESS_BUILDER_KWARGS, kind=kind
        )
        defaulted = []
        if kind_def:
            defaulted.append("kind_col")
        if on_def:
            defaulted.append("on_col")
        if text_col_v is None:
            raise ValueError("text_col must not be None for kind='process-map'")
        return _diagram_from_process_map(
            wb,
            steps_sheet=steps_sheet if steps_sheet is not None else sheet,
            flows_sheet=flows_sheet,
            text_col=text_col_v,
            kind_col=kind_col_v,
            on_col=on_col_v,
            from_col=from_col_v if from_col_v is not None
            else PROCESS_DEFAULT_FROM_COL,
            to_col=to_col_v if to_col_v is not None else PROCESS_DEFAULT_TO_COL,
            builder_kwargs=forwarded,
            defaulted=defaulted,
        )

    # kind == KIND_SWIM_LANE
    forwarded = _filter_kwargs(
        builder_kwargs, allowed=_PROCESS_BUILDER_KWARGS, kind=kind
    )
    defaulted = []
    if kind_def:
        defaulted.append("kind_col")
    if lane_def:
        defaulted.append("lane_col")
    if text_col_v is None:
        raise ValueError("text_col must not be None for kind='swim-lane'")
    if lane_col_v is None:
        raise ValueError("lane_col must not be None for kind='swim-lane'")
    return _diagram_from_swim_lane(
        wb,
        steps_sheet=steps_sheet if steps_sheet is not None else sheet,
        flows_sheet=flows_sheet,
        lanes_sheet=lanes_sheet,
        text_col=text_col_v,
        kind_col=kind_col_v,
        lane_col=lane_col_v,
        from_col=from_col_v if from_col_v is not None
        else PROCESS_DEFAULT_FROM_COL,
        to_col=to_col_v if to_col_v is not None else PROCESS_DEFAULT_TO_COL,
        builder_kwargs=forwarded,
        defaulted=defaulted,
    )


def _filter_kwargs(
    kwargs: Mapping[str, Any],
    *,
    allowed: Iterable[str],
    kind: str,
) -> Dict[str, Any]:
    """Return *kwargs* filtered to *allowed*; raise on unknown keys.

    Catches caller typos at the dispatcher boundary rather than
    letting them surface as a ``TypeError`` from the kit builder
    several stack frames deeper.
    """
    allowed_set = set(allowed)
    out: Dict[str, Any] = {}
    for k, v in kwargs.items():
        if k not in allowed_set:
            raise TypeError(
                "diagram_from_xlsx(kind=%r) does not accept keyword %r "
                "(allowed builder kwargs: %r)"
                % (kind, k, sorted(allowed_set))
            )
        out[k] = v
    return out


__all__ = [
    "DEFAULT_FLOWS_SHEET",
    "DEFAULT_LANES_SHEET",
    "DEFAULT_STEPS_SHEET",
    "DIAGRAM_KINDS",
    "ERD_DEFAULT_COLUMN_COL",
    "ERD_DEFAULT_CONSTRAINT_COL",
    "ERD_DEFAULT_TABLE_COL",
    "ERD_DEFAULT_TYPE_COL",
    "KIND_ERD",
    "KIND_ORG_CHART",
    "KIND_PROCESS_MAP",
    "KIND_SWIM_LANE",
    "ORG_CHART_DEFAULT_MANAGER_COL",
    "ORG_CHART_DEFAULT_NAME_COL",
    "ORG_CHART_DEFAULT_PHOTO_COL",
    "ORG_CHART_DEFAULT_TEAM_COL",
    "ORG_CHART_DEFAULT_TITLE_COL",
    "PROCESS_DEFAULT_FROM_COL",
    "PROCESS_DEFAULT_KIND_COL",
    "PROCESS_DEFAULT_LANE_COL",
    "PROCESS_DEFAULT_ON_COL",
    "PROCESS_DEFAULT_TEXT_COL",
    "PROCESS_DEFAULT_TO_COL",
    "WorkbookSource",
    "diagram_from_xlsx",
]
