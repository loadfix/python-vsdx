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
"""Entity-relationship diagram template — issue #130.

Build a database-schema ERD from a SQL DDL file or from a
``{table: {columns: [...]}}`` mapping::

    from vsdx.kit.erd import erd_from_sql, erd_from_models

    diagram = erd_from_sql("schema.sql")
    diagram = erd_from_models(tables={
        "users":  {"columns": [("id", "int", "PK"),
                               ("email", "varchar", "UNIQUE")]},
        "orders": {"columns": [("id", "int", "PK"),
                               ("user_id", "int", "FK->users.id")]},
    })
    diagram.save("schema.vsdx")

Each table renders as a rectangle whose body lists the columns
(name + type+constraint, tab-aligned, primary keys floated to the
top). Foreign-key columns emit a right-angle dynamic connector to
the target table; the relationship cardinality (``many:one``) and
the source/target column pair ride along on the connector's
:attr:`~vsdx.shapes.base.Shape.data`.

Auto-layout uses :meth:`Page.layout("hierarchy") <vsdx.page.Page.layout>`
when at least one FK exists and ``"force-directed"`` otherwise;
overridable via the *layout* kwarg.

**Crow's foot vs. simple arrows.** The bundled "Dynamic connector"
master only carries a single arrow head; this kit therefore takes
the simple-arrow path explicitly permitted by the issue's
acceptance criteria. Cardinality metadata stays available on the
connector's shape data so a downstream renderer can swap in
crow's-foot glyphs.

**SQL parser scope.** Regex-based; handles ``CREATE TABLE
[IF NOT EXISTS]`` with inline ``PRIMARY KEY`` / ``UNIQUE`` /
``NOT NULL`` / ``REFERENCES`` and table-level ``PRIMARY KEY``,
``UNIQUE``, ``FOREIGN KEY`` clauses (with optional ``CONSTRAINT``
names). Backtick / double-quote / square-bracket identifier
quoting, schema-prefixed table names, line + block comments, and
trailing engine clauses are tolerated. Anything else is silently
skipped — the goal is to extract enough structure to draw a
diagram, not to be a SQL front-end.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import os
import re
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

#: A single column descriptor — ``(name, type)`` or
#: ``(name, type, constraint)``. Recognised constraint tokens:
#: ``"PK"``, ``"UNIQUE"``, ``"NOT NULL"``, and ``"FK->table.col"``
#: (variants ``"FK -> table.col"`` / ``"FK:table.col"`` /
#: ``"FK table.col"`` are all accepted).
ColumnSpec = Union[
    Tuple[str, str],
    Tuple[str, str, str],
]

#: A table descriptor — ``{"columns": [ColumnSpec, ...]}``.
TableSpec = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Constraint token marking a primary-key column.
ERD_CONSTRAINT_PK: str = "PK"

#: Constraint token marking a unique column.
ERD_CONSTRAINT_UNIQUE: str = "UNIQUE"

#: Constraint token marking a NOT NULL column.
ERD_CONSTRAINT_NOT_NULL: str = "NOT NULL"

#: Prefix introducing a foreign-key target. Followed by an arrow and
#: the target as ``<table>.<column>``.
ERD_CONSTRAINT_FK_PREFIX: str = "FK"


# ---------------------------------------------------------------------------
# Layout constants — kept module-private; tweakable via build kwargs
# ---------------------------------------------------------------------------

# Margins — the page region we author into.
_PAGE_MARGIN_X: float = 0.5  # inches on left + right
_PAGE_MARGIN_Y: float = 0.5  # inches on top + bottom

# Title band — one fat rectangle across the top of the page.
_TITLE_BAND_HEIGHT: float = 0.6

# Per-table box geometry. Wide enough to fit two text columns at
# default font size; height is computed from the column count below.
_BOX_WIDTH: float = 2.4
_BOX_HEADER_HEIGHT: float = 0.4
_BOX_ROW_HEIGHT: float = 0.3
_BOX_MIN_HEIGHT: float = 0.7

# Layout spacing — inches between adjacent boxes on the auto-layout grid.
_LAYOUT_SPACING: float = 2.6

# Default page geometry — landscape suits multi-table schemas.
_DEFAULT_PAGE_WIDTH: float = 14.0
_DEFAULT_PAGE_HEIGHT: float = 10.0

# Default auto-layout kinds — picked on whether the schema has FKs.
_LAYOUT_HIERARCHY: str = "hierarchy"
_LAYOUT_FORCE_DIRECTED: str = "force-directed"

# Allowed *layout* kwarg values. ``None`` means "pick a sensible
# default based on FK presence"; the rest map to vsdx.page.Page.layout
# kinds.
_VALID_LAYOUTS = {
    None,
    "hierarchy",
    "force-directed",
    "grid",
    "radial",
}


# ---------------------------------------------------------------------------
# Constraint parsing — turn a free-text suffix into a structured tuple
# ---------------------------------------------------------------------------


_FK_RE = re.compile(
    r"""^\s*FK             # the FK keyword
        \s*(?:->|:|\s)\s*  # one of "->", ":", or whitespace
        ([A-Za-z_][\w]*)   # target table
        \s*\.\s*           # the column-of separator
        ([A-Za-z_][\w]*)   # target column
        \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _parse_fk(constraint: str) -> Optional[Tuple[str, str]]:
    """Return ``(table, column)`` if *constraint* spells a FK, else None."""
    m = _FK_RE.match(constraint)
    if m is None:
        return None
    return (m.group(1), m.group(2))


def _is_pk(constraint: str) -> bool:
    return constraint.strip().upper() == "PK" or "PRIMARY KEY" in constraint.upper()


def _is_unique(constraint: str) -> bool:
    return "UNIQUE" in constraint.upper()


# ---------------------------------------------------------------------------
# Column / table validation
# ---------------------------------------------------------------------------


def _normalise_column(
    raw: Any,
    *,
    table: str,
    ix: int,
) -> Tuple[str, str, str]:
    """Return a ``(name, type, constraint)`` triple from a caller spec."""
    if not isinstance(raw, (tuple, list)):
        raise ValueError(
            "ERD table %r column %d must be a (name, type[, constraint]) "
            "tuple (got %r)" % (table, ix, type(raw).__name__)
        )
    if len(raw) not in (2, 3):
        raise ValueError(
            "ERD table %r column %d must have 2 or 3 fields, got %d"
            % (table, ix, len(raw))
        )
    name = raw[0]
    typ = raw[1]
    constraint = raw[2] if len(raw) == 3 else ""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            "ERD table %r column %d 'name' must be a non-empty str (got %r)"
            % (table, ix, name)
        )
    if not isinstance(typ, str) or not typ.strip():
        raise ValueError(
            "ERD table %r column %d 'type' must be a non-empty str (got %r)"
            % (table, ix, typ)
        )
    if not isinstance(constraint, str):
        raise ValueError(
            "ERD table %r column %d 'constraint' must be a str (got %r)"
            % (table, ix, type(constraint).__name__)
        )
    return (name.strip(), typ.strip(), constraint.strip())


def _validate_tables(
    tables: Mapping[str, TableSpec],
) -> "Dict[str, List[Tuple[str, str, str]]]":
    """Return ``{table_name: [(col_name, col_type, constraint), ...]}``."""
    if not isinstance(tables, Mapping):
        raise ValueError(
            "tables must be a Mapping[str, TableSpec] (got %r)"
            % type(tables).__name__
        )
    if not tables:
        raise ValueError("tables must contain at least one entry")

    parsed: Dict[str, List[Tuple[str, str, str]]] = {}
    for table_name, spec in tables.items():
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError(
                "ERD table name must be a non-empty str (got %r)" % table_name
            )
        if not isinstance(spec, Mapping):
            raise ValueError(
                "ERD table %r spec must be a Mapping (got %r)"
                % (table_name, type(spec).__name__)
            )
        cols_raw = spec.get("columns")
        if not cols_raw:
            raise ValueError(
                "ERD table %r is missing a non-empty 'columns' list"
                % table_name
            )
        if not isinstance(cols_raw, (list, tuple)):
            raise ValueError(
                "ERD table %r 'columns' must be a list (got %r)"
                % (table_name, type(cols_raw).__name__)
            )
        cols: List[Tuple[str, str, str]] = []
        for ix, raw in enumerate(cols_raw):
            cols.append(_normalise_column(raw, table=table_name, ix=ix))
        parsed[table_name.strip()] = cols
    return parsed


# ---------------------------------------------------------------------------
# Box-text rendering — two-column "name | type+constraint" block
# ---------------------------------------------------------------------------


def _box_text(table_name: str, columns: Sequence[Tuple[str, str, str]]) -> str:
    """Compose the multi-line label for a single table rectangle.

    First line is the table name. Each subsequent line is
    ``<col>\\t<type>  <constraint>``. Primary-key columns float to
    the top of the column list.
    """
    pk_cols: List[Tuple[str, str, str]] = []
    other_cols: List[Tuple[str, str, str]] = []
    for col in columns:
        if _is_pk(col[2]):
            pk_cols.append(col)
        else:
            other_cols.append(col)
    ordered = pk_cols + other_cols

    lines: List[str] = [table_name]
    for name, typ, constraint in ordered:
        right = typ
        if constraint:
            right = "%s  %s" % (typ, constraint)
        lines.append("%s\t%s" % (name, right))
    return "\n".join(lines)


def _box_height_for(columns: Sequence[Tuple[str, str, str]]) -> float:
    """Return the rectangle height (inches) for a table with *columns*."""
    h = _BOX_HEADER_HEIGHT + _BOX_ROW_HEIGHT * len(columns)
    return max(_BOX_MIN_HEIGHT, h)


# ---------------------------------------------------------------------------
# FK extraction — pull (source, target) edges from the parsed tables
# ---------------------------------------------------------------------------


def _collect_fk_edges(
    parsed: Mapping[str, Sequence[Tuple[str, str, str]]],
) -> "List[Tuple[str, str, str, str]]":
    """Return ``[(source_table, source_col, target_table, target_col), ...]``.

    Targets not in *parsed* are silently dropped so callers can
    legitimately diagram a sub-schema.
    """
    edges: List[Tuple[str, str, str, str]] = []
    table_set = set(parsed.keys())
    for table_name, cols in parsed.items():
        for col_name, _typ, constraint in cols:
            target = _parse_fk(constraint)
            if target is None:
                continue
            tgt_table, tgt_col = target
            if tgt_table not in table_set:
                continue
            edges.append((table_name, col_name, tgt_table, tgt_col))
    return edges


# ---------------------------------------------------------------------------
# Public builder — programmatic
# ---------------------------------------------------------------------------


def erd_from_models(
    *,
    tables: Mapping[str, TableSpec],
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
    layout: Optional[str] = None,
) -> VisioDocument:
    """Author an entity-relationship diagram and return the document.

    *tables* maps table name → ``{"columns": [ColumnSpec, ...]}``.
    *title* renders into a page-top band when non-empty; the default
    ``""`` suppresses it. *page_name* defaults to *title* (or
    ``"ERD"``). *routing* / *spacing* tune the connector + layout
    pass. *layout* defaults to ``"hierarchy"`` when FKs exist and
    ``"force-directed"`` otherwise; ``"grid"`` and ``"radial"`` are
    also accepted.

    :raises TypeError: when *title* is not a ``str``.
    :raises ValueError: when *tables* is empty / not a mapping, when
        a table lacks a non-empty ``"columns"`` list, when a column
        tuple is malformed, or when *layout* is unrecognised.

    .. versionadded:: 0.4.0
    """
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)
    if layout not in _VALID_LAYOUTS:
        raise ValueError(
            "layout=%r must be one of %r"
            % (layout, sorted(k for k in _VALID_LAYOUTS if k is not None))
        )

    parsed = _validate_tables(tables)
    edges = _collect_fk_edges(parsed)

    # -- Document + page -------------------------------------------------
    doc = Visio()
    name = (page_name or title.strip() or "ERD")
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

    # -- Table boxes -----------------------------------------------------
    proxies: Dict[str, Shape] = {}
    drop_x = _PAGE_MARGIN_X + _BOX_WIDTH / 2
    drop_y_start = (
        page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT - _BOX_MIN_HEIGHT / 2
    )
    cumulative_y = drop_y_start
    for table_name, cols in parsed.items():
        h = _box_height_for(cols)
        pin_y = cumulative_y - h / 2
        cumulative_y -= h + 0.2
        box = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(drop_x, pin_y),
            size=(_BOX_WIDTH, h),
            text=_box_text(table_name, cols),
        )
        box.data.add_field("TableName", table_name, label="Table")
        proxies[table_name] = box

    # -- FK connectors ---------------------------------------------------
    for source, source_col, target, target_col in edges:
        # FK columns reference the target's PK/UNIQUE — many:one.
        conn = page.add_connector(
            proxies[source],
            proxies[target],
            routing=routing,
        )
        # Cardinality + endpoint columns ride on shape data so a
        # downstream pass can swap simple arrows for crow's foot.
        conn.data.add_field(
            "Cardinality", "many:one", label="Cardinality"
        )
        conn.data.add_field(
            "SourceColumn", "%s.%s" % (source, source_col),
            label="Source column",
        )
        conn.data.add_field(
            "TargetColumn", "%s.%s" % (target, target_col),
            label="Target column",
        )

    # -- Auto-layout ------------------------------------------------------
    chosen_layout = layout
    if chosen_layout is None:
        chosen_layout = (
            _LAYOUT_HIERARCHY if edges else _LAYOUT_FORCE_DIRECTED
        )

    origin_x = _PAGE_MARGIN_X + _BOX_WIDTH / 2
    origin_y = (
        page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT - _BOX_MIN_HEIGHT / 2
    )
    if chosen_layout == _LAYOUT_HIERARCHY:
        page.layout(
            "hierarchy",
            direction="top-to-bottom",
            spacing=spacing,
            origin=(origin_x, origin_y),
        )
        # See vsdx.kit.org_chart — flip Y around the origin so
        # children render *below* their parents in Visio coords.
        for box in proxies.values():
            box.pin_y = 2 * origin_y - float(box.pin_y)
    else:
        page.layout(
            chosen_layout,
            spacing=spacing,
            origin=(origin_x, origin_y),
        )

    return doc


# ---------------------------------------------------------------------------
# SQL DDL parser — minimal regex-based scanner
# ---------------------------------------------------------------------------


# Strip block comments (/* ... */) and line comments (-- ... \n).
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*", re.MULTILINE)


def _strip_sql_comments(sql: str) -> str:
    sql = _BLOCK_COMMENT_RE.sub(" ", sql)
    sql = _LINE_COMMENT_RE.sub(" ", sql)
    return sql


# Match `CREATE TABLE [IF NOT EXISTS] [schema.]name ( ... )`. We pull
# the table name (last identifier) and the parenthesised body.
_CREATE_TABLE_RE = re.compile(
    r"""CREATE\s+TABLE
        (?:\s+IF\s+NOT\s+EXISTS)?
        \s+
        (?:[`"\[]?(?P<schema>[A-Za-z_][\w]*)[`"\]]?\s*\.\s*)?
        [`"\[]?(?P<name>[A-Za-z_][\w]*)[`"\]]?
        \s*\(
        (?P<body>.*?)
        \)\s*
        (?:[A-Z][A-Z_ =\d]*?)?  # trailing engine / charset clauses
        \s*;
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def _split_top_level(body: str) -> List[str]:
    """Split *body* on commas that aren't inside parentheses."""
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


# Identifier without schema prefix — matches `name`, "name", [name], or
# bare name.
_IDENT_RE = re.compile(
    r"""[`"\[]?([A-Za-z_][\w]*)[`"\]]?""",
    re.VERBOSE,
)


# Column definition: `<name> <type> [more...]`. Type may include a
# parenthesised size like VARCHAR(255) or DECIMAL(10,2) — we capture
# everything up to the first stand-alone keyword that introduces a
# constraint clause (PRIMARY, REFERENCES, NOT, UNIQUE, DEFAULT, CHECK,
# COLLATE, NULL, AUTO_INCREMENT, GENERATED). Anything past that point
# is the constraint tail.
_COL_DEF_RE = re.compile(
    r"""^\s*
        [`"\[]?(?P<name>[A-Za-z_][\w]*)[`"\]]?
        \s+
        (?P<type>
            [A-Za-z_][\w]*               # base type
            (?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?  # optional (n) or (n,m)
        )
        (?P<rest>.*)$
    """,
    re.VERBOSE | re.DOTALL,
)


# Inline REFERENCES clause within a column def.
_INLINE_REF_RE = re.compile(
    r"""REFERENCES \s+
        (?:[`"\[]?[A-Za-z_][\w]*[`"\]]?\s*\.\s*)?  # optional schema
        [`"\[]?(?P<table>[A-Za-z_][\w]*)[`"\]]?
        \s*\(\s*[`"\[]?(?P<col>[A-Za-z_][\w]*)[`"\]]?\s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Table-level FOREIGN KEY clause.
_TABLE_FK_RE = re.compile(
    r"""(?:CONSTRAINT\s+[`"\[]?[A-Za-z_][\w]*[`"\]]?\s+)?
        FOREIGN\s+KEY\s*\(\s*
        [`"\[]?(?P<col>[A-Za-z_][\w]*)[`"\]]?
        \s*\)\s*
        REFERENCES\s+
        (?:[`"\[]?[A-Za-z_][\w]*[`"\]]?\s*\.\s*)?
        [`"\[]?(?P<rtable>[A-Za-z_][\w]*)[`"\]]?
        \s*\(\s*[`"\[]?(?P<rcol>[A-Za-z_][\w]*)[`"\]]?\s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Table-level PRIMARY KEY clause.
_TABLE_PK_RE = re.compile(
    r"""(?:CONSTRAINT\s+[`"\[]?[A-Za-z_][\w]*[`"\]]?\s+)?
        PRIMARY\s+KEY\s*\(\s*
        [`"\[]?(?P<col>[A-Za-z_][\w]*)[`"\]]?
        \s*(?:,\s*[`"\[]?[A-Za-z_][\w]*[`"\]]?\s*)*
        \)
    """,
    re.IGNORECASE | re.VERBOSE,
)


# Table-level UNIQUE clause.
_TABLE_UNIQUE_RE = re.compile(
    r"""(?:CONSTRAINT\s+[`"\[]?[A-Za-z_][\w]*[`"\]]?\s+)?
        UNIQUE\s*(?:KEY\s*)?\(\s*
        [`"\[]?(?P<col>[A-Za-z_][\w]*)[`"\]]?
        \s*\)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _column_constraint_label(rest: str, inline_ref: Optional[Tuple[str, str]]) -> str:
    """Pick a single label: FK > PK > UNIQUE > NOT NULL. ``""`` when none."""
    if inline_ref is not None:
        return "FK->%s.%s" % inline_ref
    upper = rest.upper()
    if "PRIMARY KEY" in upper:
        return "PK"
    if "UNIQUE" in upper:
        return "UNIQUE"
    if "NOT NULL" in upper:
        return "NOT NULL"
    return ""


def parse_sql_ddl(sql: str) -> "Dict[str, List[Tuple[str, str, str]]]":
    """Parse *sql* and return ``{table_name: [(col_name, type, constraint), ...]}``.

    See the module docstring for the supported subset. A missing
    trailing semicolon is tolerated.

    .. versionadded:: 0.4.0
    """
    if not isinstance(sql, str):
        raise TypeError("sql must be a str (got %r)" % type(sql).__name__)

    cleaned = _strip_sql_comments(sql)
    if not cleaned.rstrip().endswith(";"):
        cleaned = cleaned + ";"

    tables: Dict[str, List[Tuple[str, str, str]]] = {}
    for m in _CREATE_TABLE_RE.finditer(cleaned):
        table_name = m.group("name")
        body = m.group("body")
        cols: List[Tuple[str, str, str]] = []
        # First pass: separate column defs from table-level constraints.
        table_pks: List[str] = []
        table_uniques: List[str] = []
        table_fks: Dict[str, Tuple[str, str]] = {}
        col_defs: List[str] = []
        for piece in _split_top_level(body):
            stripped = piece.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if upper.startswith("CONSTRAINT") or upper.startswith(
                ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "INDEX", "KEY")
            ):
                pk_m = _TABLE_PK_RE.match(stripped)
                if pk_m is not None:
                    table_pks.append(pk_m.group("col"))
                    continue
                fk_m = _TABLE_FK_RE.match(stripped)
                if fk_m is not None:
                    table_fks[fk_m.group("col")] = (
                        fk_m.group("rtable"),
                        fk_m.group("rcol"),
                    )
                    continue
                uq_m = _TABLE_UNIQUE_RE.match(stripped)
                if uq_m is not None:
                    table_uniques.append(uq_m.group("col"))
                    continue
                # Unrecognised table-level constraint — skip.
                continue
            col_defs.append(stripped)

        # Second pass — flesh each column out.
        for piece in col_defs:
            cm = _COL_DEF_RE.match(piece)
            if cm is None:
                continue
            col_name = cm.group("name")
            col_type = cm.group("type").strip()
            rest = cm.group("rest") or ""
            inline_ref_m = _INLINE_REF_RE.search(rest)
            inline_ref: Optional[Tuple[str, str]] = None
            if inline_ref_m is not None:
                inline_ref = (
                    inline_ref_m.group("table"),
                    inline_ref_m.group("col"),
                )
            constraint = _column_constraint_label(rest, inline_ref)
            # Table-level constraints win over inline detection.
            if col_name in table_fks:
                tgt = table_fks[col_name]
                constraint = "FK->%s.%s" % tgt
            elif col_name in table_pks:
                constraint = "PK"
            elif col_name in table_uniques and not constraint:
                constraint = "UNIQUE"
            cols.append((col_name, col_type, constraint))
        tables[table_name] = cols
    return tables


def _looks_like_path(path_or_string: str) -> bool:
    """True when *path_or_string* should be read from disk vs. parsed inline."""
    if "\n" in path_or_string:
        return False
    if "CREATE" in path_or_string.upper():
        return False
    return os.path.isfile(path_or_string)


# ---------------------------------------------------------------------------
# Public builder — SQL DDL
# ---------------------------------------------------------------------------


def erd_from_sql(
    path_or_string: Union[str, "os.PathLike[str]"],
    *,
    encoding: str = "utf-8",
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
    layout: Optional[str] = None,
) -> VisioDocument:
    """Parse a SQL DDL file (or string) and author an ERD diagram.

    *path_or_string* reads from disk when it is an :class:`os.PathLike`
    or when it is a ``str`` that points at an existing file and
    carries no SQL keyword; otherwise it is interpreted as raw DDL.
    Every other keyword is forwarded to :func:`erd_from_models`.

    :raises FileNotFoundError: when a path-shaped input doesn't exist.
    :raises TypeError: when *path_or_string* isn't a ``str`` or
        :class:`os.PathLike`.
    :raises ValueError: when no ``CREATE TABLE`` statements parse
        cleanly, or when :func:`erd_from_models` rejects the result.

    .. versionadded:: 0.4.0
    """
    if isinstance(path_or_string, os.PathLike):
        with open(path_or_string, "r", encoding=encoding) as fh:
            sql_text = fh.read()
    elif isinstance(path_or_string, str):
        if _looks_like_path(path_or_string):
            with open(path_or_string, "r", encoding=encoding) as fh:
                sql_text = fh.read()
        else:
            sql_text = path_or_string
    else:
        raise TypeError(
            "path_or_string must be a str or os.PathLike (got %r)"
            % type(path_or_string).__name__
        )

    parsed = parse_sql_ddl(sql_text)
    if not parsed:
        raise ValueError(
            "SQL input contains no parseable CREATE TABLE statements"
        )

    # Convert the parsed tuples into the erd_from_models tables shape.
    tables: Dict[str, Dict[str, Any]] = {
        name: {"columns": list(cols)} for name, cols in parsed.items()
    }
    return erd_from_models(
        tables=tables,
        title=title,
        page_width=page_width,
        page_height=page_height,
        page_name=page_name,
        routing=routing,
        spacing=spacing,
        layout=layout,
    )


__all__ = [
    "ColumnSpec",
    "ERD_CONSTRAINT_FK_PREFIX",
    "ERD_CONSTRAINT_NOT_NULL",
    "ERD_CONSTRAINT_PK",
    "ERD_CONSTRAINT_UNIQUE",
    "TableSpec",
    "erd_from_models",
    "erd_from_sql",
    "parse_sql_ddl",
]
