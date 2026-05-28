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
"""Org-chart diagram template — issue #122.

Build a Visio organisational chart from a plain-Python roster or a CSV
file::

    from vsdx.kit.org_chart import build_org_chart, build_org_chart_from_csv

    # Programmatic — list of employee dicts
    diagram = build_org_chart(
        employees=[
            {"name": "Alice",  "title": "Chief Exec",      "manager": None},
            {"name": "Bob",    "title": "Chief Tech",      "manager": "Alice"},
            {"name": "Carol",  "title": "Chief Fin",       "manager": "Alice"},
            {"name": "Dan",    "title": "VP Engineering",  "manager": "Bob"},
        ],
    )
    diagram.save("org-chart.vsdx")

    # From a CSV file with `name,title,manager,photo,team` columns
    diagram = build_org_chart_from_csv("roster.csv")
    diagram.save("from-csv.vsdx")

Layout
------

Every employee renders as a rectangle whose label is the two-line
"name + title" string. Reporting lines run from each manager to its
direct reports as right-angle dynamic connectors (issue #53). After
the boxes + connectors are emitted, the page is laid out via
:meth:`vsdx.page.Page.layout` with ``kind="hierarchy"`` (issue #50)
which positions every box on a Reingold-Tilford-style tidy tree:
roots (employees without a manager) sit at the top, direct reports
fan out underneath, and disjoint trees are stacked side-by-side.

Optional fields
---------------

The ``photo`` field — a URL or local path — is recorded on the
employee's box as a shape-data property named ``"Photo"``. python-vsdx
does not yet expose a high-level image-embed primitive, so the photo
is preserved as a string property rather than rendered as a bitmap.
Downstream consumers (data graphics, custom export tools, the Visio
desktop client's "Pictures" data-graphic widget) can pick it up from
shape data via :attr:`vsdx.shapes.base.Shape.data`.

The ``team`` field is recorded the same way under the ``"Team"``
property name; it is otherwise unused by the layout.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import csv
import os
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.routing import ROUTING_RIGHT_ANGLE
from vsdx.shapes.base import Shape

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

#: An employee record — ``Mapping[str, Any]``. Keys read by the builder:
#:
#: * ``"name"`` (required) — unique identifier and the first text line on
#:   the rendered box.
#: * ``"title"`` (optional) — second text line on the box.
#: * ``"manager"`` (optional) — the *name* of another employee in the
#:   same roster, or ``None`` / omitted for a root (CEO-style) entry.
#: * ``"photo"`` (optional) — URL or local path. Stored on the box's
#:   shape data as the ``"Photo"`` property.
#: * ``"team"`` (optional) — free-text team / department label. Stored
#:   on the box's shape data as the ``"Team"`` property.
EmployeeLike = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Layout constants — kept module-private; tweakable via build kwargs
# ---------------------------------------------------------------------------

# Margins — the page region we author into.
_PAGE_MARGIN_X: float = 0.5  # inches on left + right
_PAGE_MARGIN_Y: float = 0.5  # inches on top + bottom

# Title band — one fat rectangle across the top of the page.
_TITLE_BAND_HEIGHT: float = 0.6

# Per-employee box geometry. Wide-enough rectangles to fit "Name" plus a
# longer title line at default font size.
_BOX_WIDTH: float = 1.8
_BOX_HEIGHT: float = 0.9

# Layout spacing — inches between adjacent siblings on a tidy tree.
_LAYOUT_SPACING: float = 2.4

# Default page geometry — landscape suits multi-branch org charts.
_DEFAULT_PAGE_WIDTH: float = 14.0
_DEFAULT_PAGE_HEIGHT: float = 10.0


# ---------------------------------------------------------------------------
# CSV column-name defaults
# ---------------------------------------------------------------------------

#: Default CSV column for an employee's unique name / identifier.
DEFAULT_NAME_COL: str = "name"

#: Default CSV column for an employee's job title.
DEFAULT_TITLE_COL: str = "title"

#: Default CSV column for an employee's reporting line.
DEFAULT_MANAGER_COL: str = "manager"

#: Default CSV column for an employee's photo URL or local path.
DEFAULT_PHOTO_COL: str = "photo"

#: Default CSV column for an employee's team / department label.
DEFAULT_TEAM_COL: str = "team"


# ---------------------------------------------------------------------------
# Employee-dict accessors and validation
# ---------------------------------------------------------------------------


def _employee_name(emp: EmployeeLike, *, ix: int) -> str:
    """Return the ``name`` of *emp*; raise on absent / non-string."""
    if "name" not in emp:
        raise ValueError(
            "org-chart employee %d is missing a required 'name' key" % ix
        )
    name = emp["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            "org-chart employee %d 'name' must be a non-empty str (got %r)"
            % (ix, name)
        )
    return name


def _employee_string_field(
    emp: EmployeeLike,
    key: str,
    *,
    ix: int,
) -> Optional[str]:
    """Return ``emp[key]`` as a string or ``None`` if missing / blank.

    Empty strings collapse to ``None`` so a CSV with a blank ``manager``
    column is treated identically to omitting the key in a dict roster.
    """
    if key not in emp:
        return None
    raw = emp[key]
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(
            "org-chart employee %d %r must be a str or None (got %r)"
            % (ix, key, raw)
        )
    if not raw.strip():
        return None
    return raw


def _box_text(name: str, title: Optional[str]) -> str:
    """Compose the on-shape label from *name* + optional *title*.

    Two lines separated by ``\n`` so Visio renders the title beneath
    the name; falls back to just the name when *title* is absent.
    """
    if title is None:
        return name
    return "%s\n%s" % (name, title)


# ---------------------------------------------------------------------------
# Roster validation — uniqueness + manager resolution
# ---------------------------------------------------------------------------


def _validate_roster(
    employees: Sequence[EmployeeLike],
) -> List[Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]]:
    """Return a parallel list of ``(name, title, manager, photo, team)``.

    Validates:

    * non-empty roster
    * every record has a non-empty ``name``
    * names are unique (case-sensitive)
    * every non-``None`` ``manager`` matches another employee's ``name``
    * the manager graph contains no cycles (so the hierarchy layout
      can succeed without bailing on a non-tree input)
    """
    if not employees:
        raise ValueError("employees must contain at least one record")

    parsed: List[
        Tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]
    ] = []
    seen: Dict[str, int] = {}
    for ix, emp in enumerate(employees):
        if not isinstance(emp, Mapping):
            raise ValueError(
                "org-chart employee %d must be a Mapping (got %r)"
                % (ix, type(emp).__name__)
            )
        name = _employee_name(emp, ix=ix)
        if name in seen:
            raise ValueError(
                "org-chart employee name %r duplicated (entries %d and %d) "
                "— names must be unique because manager links resolve by "
                "name" % (name, seen[name], ix)
            )
        seen[name] = ix
        title = _employee_string_field(emp, "title", ix=ix)
        manager = _employee_string_field(emp, "manager", ix=ix)
        photo = _employee_string_field(emp, "photo", ix=ix)
        team = _employee_string_field(emp, "team", ix=ix)
        parsed.append((name, title, manager, photo, team))

    # Manager resolution + cycle detection.
    name_set = set(seen)
    parents: Dict[str, Optional[str]] = {}
    for name, _title, manager, _photo, _team in parsed:
        if manager is not None and manager not in name_set:
            raise ValueError(
                "org-chart employee %r reports to %r which is not in the "
                "roster" % (name, manager)
            )
        if manager == name:
            raise ValueError(
                "org-chart employee %r is listed as their own manager" % name
            )
        parents[name] = manager

    # Walk parents to root for every node — any cycle returns to a node
    # already on the current chain.
    for start in parents:
        chain: List[str] = []
        cursor: Optional[str] = start
        while cursor is not None:
            if cursor in chain:
                cycle = chain[chain.index(cursor):] + [cursor]
                raise ValueError(
                    "org-chart manager graph contains a cycle: %s"
                    % " -> ".join(cycle)
                )
            chain.append(cursor)
            cursor = parents[cursor]

    return parsed


# ---------------------------------------------------------------------------
# Public builder — programmatic
# ---------------------------------------------------------------------------


def build_org_chart(
    *,
    employees: Sequence[EmployeeLike],
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
) -> VisioDocument:
    """Author an org-chart diagram and return the document.

    :param employees: ordered iterable of employee descriptors. Each
        entry is a ``Mapping[str, Any]`` with the keys documented on
        :data:`EmployeeLike`. ``manager`` strings are resolved against
        each other employee's ``name``; ``None`` / omission marks a
        root (top-of-chart) entry.
    :param title: optional caption rendered in the page's title band.
        Defaults to an empty string — pass ``""`` to suppress the
        band entirely.
    :param page_width: page width in inches. Default: ``14.0``
        (landscape).
    :param page_height: page height in inches. Default: ``10.0``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title* (whitespace-trimmed); falls back to ``"Org chart"``
        when *title* is empty.
    :param routing: connector routing mode forwarded to
        :func:`vsdx.routing.route_connector`. Default:
        :data:`vsdx.routing.ROUTING_RIGHT_ANGLE` — the conventional
        right-angle "elbow" routing used by every org-chart template
        Microsoft ships.
    :param spacing: per-level gap (inches) passed to
        :meth:`vsdx.page.Page.layout`. Default: ``2.4``.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *title* is not a ``str``.
    :raises ValueError: when *employees* is empty, when a record
        lacks a ``name``, when ``name`` values collide, when a
        ``manager`` string references an unknown employee, when an
        employee is its own manager, or when the ``manager`` graph
        contains a cycle.

    .. versionadded:: 0.4.0
    """
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)

    parsed = _validate_roster(list(employees))

    # -- Document + page -------------------------------------------------
    doc = Visio()
    name = (page_name or title.strip() or "Org chart")
    page = doc.pages.add_page(
        name=name, width=page_width, height=page_height
    )

    # -- Title band ------------------------------------------------------
    inner_w = page_width - 2 * _PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _PAGE_MARGIN_X)
        )
    if title:
        title_pin_x = _PAGE_MARGIN_X + inner_w / 2
        title_pin_y = (
            page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT / 2
        )
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(inner_w, _TITLE_BAND_HEIGHT),
            text=title,
        )

    # -- Employee boxes --------------------------------------------------
    proxies: Dict[str, Shape] = {}
    # Initial drop point — the top-left inside the body. The hierarchy
    # layout call below will reposition every box. Placing them in a
    # column for now keeps the pre-layout state inspectable for tests.
    drop_x = _PAGE_MARGIN_X + _BOX_WIDTH / 2
    drop_y_start = (
        page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT - _BOX_HEIGHT / 2
    )
    for ix, (emp_name, emp_title, _mgr, photo, team) in enumerate(parsed):
        pin_y = drop_y_start - ix * (_BOX_HEIGHT + 0.2)
        box = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(drop_x, pin_y),
            size=(_BOX_WIDTH, _BOX_HEIGHT),
            text=_box_text(emp_name, emp_title),
        )
        # Record optional metadata on shape data so a downstream
        # data-graphics pass / Visio's Pictures widget can pick them up.
        if photo is not None:
            box.data.add_field("Photo", photo, label="Photo")
        if team is not None:
            box.data.add_field("Team", team, label="Team")
        proxies[emp_name] = box

    # -- Reporting-line connectors ---------------------------------------
    for emp_name, _title, manager, _photo, _team in parsed:
        if manager is None:
            continue
        page.add_connector(
            proxies[manager],
            proxies[emp_name],
            routing=routing,
        )

    # -- Auto-layout via the hierarchy placer (#50) ----------------------
    # Origin sits one body-margin in from the top-left inner corner so
    # the laid-out tree reads top-down with the roots at the top of the
    # body region.
    origin_x = _PAGE_MARGIN_X + _BOX_WIDTH / 2
    origin_y = (
        page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT - _BOX_HEIGHT / 2
    )
    page.layout(
        "hierarchy",
        direction="top-to-bottom",
        spacing=spacing,
        origin=(origin_x, origin_y),
    )
    # The hierarchy layout places nodes at descending Y values (depth
    # axis). Pages with `top-to-bottom` direction in this codebase add
    # `depth * spacing` to the origin Y, which actually walks *up* in
    # Visio's bottom-anchored coordinate system. Flip the per-node Y
    # around the origin so children fall *below* their parent on the
    # rendered page — this matches the visual convention every Microsoft
    # org-chart template ships.
    for box in proxies.values():
        box.pin_y = 2 * origin_y - float(box.pin_y)

    return doc


# ---------------------------------------------------------------------------
# Public builder — CSV
# ---------------------------------------------------------------------------


def build_org_chart_from_csv(
    path: Union[str, "os.PathLike[str]"],
    *,
    name_col: str = DEFAULT_NAME_COL,
    title_col: str = DEFAULT_TITLE_COL,
    manager_col: str = DEFAULT_MANAGER_COL,
    photo_col: str = DEFAULT_PHOTO_COL,
    team_col: str = DEFAULT_TEAM_COL,
    encoding: str = "utf-8",
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
) -> VisioDocument:
    """Read a CSV roster and author an org-chart diagram.

    The CSV is parsed with :class:`csv.DictReader`. The default column
    names (``name`` / ``title`` / ``manager`` / ``photo`` / ``team``)
    can be overridden via the ``*_col`` kwargs to match an existing
    HR-export schema. Only ``name_col`` is required to be present in
    the file's header — the four optional columns are read when
    present and skipped otherwise (so a two-column ``name,manager``
    file works without further configuration).

    :param path: filesystem path to the CSV file, as ``str`` or
        :class:`os.PathLike`.
    :param name_col: header name of the column carrying the employee's
        unique name. Default: ``"name"``.
    :param title_col: header name of the column carrying the employee's
        job title. Default: ``"title"``.
    :param manager_col: header name of the column carrying each
        employee's manager (also a value from *name_col*). Default:
        ``"manager"``. Blank cells mark a root.
    :param photo_col: header name of the optional photo URL / path
        column. Default: ``"photo"``.
    :param team_col: header name of the optional team-label column.
        Default: ``"team"``.
    :param encoding: file encoding passed to :func:`open`. Default:
        ``"utf-8"``.

    Every other keyword argument is forwarded to :func:`build_org_chart`
    — see that function's docstring for the page-layout knobs.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises FileNotFoundError: when *path* does not exist.
    :raises ValueError: when the CSV lacks the *name_col* column, or
        when any roster validation fires (see :func:`build_org_chart`).

    .. versionadded:: 0.4.0
    """
    employees = _read_csv_roster(
        path,
        name_col=name_col,
        title_col=title_col,
        manager_col=manager_col,
        photo_col=photo_col,
        team_col=team_col,
        encoding=encoding,
    )
    return build_org_chart(
        employees=employees,
        title=title,
        page_width=page_width,
        page_height=page_height,
        page_name=page_name,
        routing=routing,
        spacing=spacing,
    )


def _read_csv_roster(
    path: Union[str, "os.PathLike[str]"],
    *,
    name_col: str,
    title_col: str,
    manager_col: str,
    photo_col: str,
    team_col: str,
    encoding: str,
) -> List[Dict[str, str]]:
    """Read *path* and return a list of canonical employee dicts.

    Optional columns absent from the header are silently skipped on a
    per-row basis; cells whose value is blank or whitespace-only are
    coerced to absent so :func:`_employee_string_field` consistently
    treats them as ``None`` downstream.
    """
    with open(path, "r", encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or name_col not in reader.fieldnames:
            raise ValueError(
                "CSV at %s is missing the required %r header column "
                "(found: %r)" % (path, name_col, reader.fieldnames)
            )
        rows: List[Dict[str, str]] = []
        for raw_row in reader:
            emp: Dict[str, str] = {}
            for src_col, dst_key in (
                (name_col, "name"),
                (title_col, "title"),
                (manager_col, "manager"),
                (photo_col, "photo"),
                (team_col, "team"),
            ):
                if src_col in raw_row:
                    raw_val = raw_row[src_col]
                    if raw_val is not None and str(raw_val).strip():
                        emp[dst_key] = str(raw_val).strip()
            if "name" in emp:
                rows.append(emp)
    return rows


__all__ = [
    "DEFAULT_MANAGER_COL",
    "DEFAULT_NAME_COL",
    "DEFAULT_PHOTO_COL",
    "DEFAULT_TEAM_COL",
    "DEFAULT_TITLE_COL",
    "EmployeeLike",
    "build_org_chart",
    "build_org_chart_from_csv",
]
