# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.erd` — issue #130."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

import vsdx
from vsdx.kit import (
    ERD_CONSTRAINT_FK_PREFIX,
    ERD_CONSTRAINT_NOT_NULL,
    ERD_CONSTRAINT_PK,
    ERD_CONSTRAINT_UNIQUE,
    erd_from_models,
    erd_from_sql,
)
from vsdx.kit.erd import parse_sql_ddl
from vsdx.shapes.connector import Connector

# ---------------------------------------------------------------------------
# Canonical fixture — three-table users / orders / order_items schema
# ---------------------------------------------------------------------------


_FIXTURE_TABLES = {
    "users": {
        "columns": [
            ("id", "int", "PK"),
            ("email", "varchar", "UNIQUE"),
            ("name", "varchar"),
        ],
    },
    "orders": {
        "columns": [
            ("id", "int", "PK"),
            ("user_id", "int", "FK->users.id"),
            ("total", "decimal"),
            ("created_at", "timestamp"),
        ],
    },
    "order_items": {
        "columns": [
            ("id", "int", "PK"),
            ("order_id", "int", "FK->orders.id"),
            ("sku", "varchar"),
        ],
    },
}


_FIXTURE_SQL = """
-- a small e-commerce schema
CREATE TABLE users (
    id INT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100)
);

CREATE TABLE orders (
    id INT PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id),
    total DECIMAL(10, 2),
    created_at TIMESTAMP
);

CREATE TABLE order_items (
    id INT PRIMARY KEY,
    order_id INT,
    sku VARCHAR(50),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
"""


# ---------------------------------------------------------------------------
# DescribeErdFromModels — happy-path acceptance for the dict builder
# ---------------------------------------------------------------------------


class DescribeErdFromModels:
    def it_returns_a_VisioDocument(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        assert len(diagram.pages) == 1

    def it_defaults_the_page_name_to_ERD_when_no_title(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        assert diagram.pages[0].name == "ERD"

    def it_uses_the_title_as_the_page_name(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES, title="Schema 2026")
        assert diagram.pages[0].name == "Schema 2026"

    def it_honours_an_explicit_page_name_over_the_title(self):
        diagram = erd_from_models(
            tables=_FIXTURE_TABLES, title="Schema", page_name="Schema v2"
        )
        assert diagram.pages[0].name == "Schema v2"

    def it_emits_one_box_per_table(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        # No title band because title was empty.
        assert len(boxes) == len(_FIXTURE_TABLES)

    def it_emits_a_title_band_when_title_is_non_empty(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES, title="Schema 2026")
        non_connector = [
            s for s in diagram.pages[0].shapes if not isinstance(s, Connector)
        ]
        # 1 title + 3 tables
        assert len(non_connector) == 1 + len(_FIXTURE_TABLES)
        title_shape = next(s for s in non_connector if s.text == "Schema 2026")
        assert title_shape is not None

    def it_renders_each_box_with_table_name_on_the_first_line(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        first_lines = {
            s.text.split("\n", 1)[0]
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        }
        assert {"users", "orders", "order_items"} <= first_lines

    def it_lists_columns_in_pk_first_order(self):
        diagram = erd_from_models(
            tables={
                "t": {
                    "columns": [
                        ("a", "varchar"),
                        ("b", "varchar"),
                        ("id", "int", "PK"),
                    ],
                },
            },
        )
        box = next(
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text and s.text.startswith("t")
        )
        # First non-header line is the PK column.
        lines = box.text.split("\n")
        assert lines[0] == "t"
        assert lines[1].startswith("id")

    def it_separates_columns_with_a_tab_and_includes_constraints(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        users_box = next(
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
            and s.text
            and s.text.startswith("users")
        )
        for line in users_box.text.split("\n")[1:]:
            assert "\t" in line
        assert "PK" in users_box.text
        assert "UNIQUE" in users_box.text

    def it_records_the_table_name_on_shape_data(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        users_box = next(
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector)
            and s.text
            and s.text.startswith("users")
        )
        assert users_box.data["TableName"] == "users"


# ---------------------------------------------------------------------------
# DescribeErdConnectors — FK relationship wiring
# ---------------------------------------------------------------------------


class DescribeErdConnectors:
    def it_emits_one_connector_per_fk(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        # orders.user_id -> users.id, order_items.order_id -> orders.id
        assert len(conns) == 2

    def it_emits_no_connector_for_a_fk_targeting_an_unknown_table(self):
        diagram = erd_from_models(
            tables={
                "t": {
                    "columns": [
                        ("id", "int", "PK"),
                        ("ref", "int", "FK->ghost.id"),
                    ],
                },
            },
        )
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        assert conns == []

    def it_emits_no_connector_when_no_fks_exist(self):
        diagram = erd_from_models(
            tables={
                "a": {"columns": [("id", "int", "PK")]},
                "b": {"columns": [("id", "int", "PK")]},
            },
        )
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        assert conns == []

    def it_records_cardinality_metadata_on_each_fk_connector(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        for conn in conns:
            assert conn.data["Cardinality"] == "many:one"

    def it_records_source_and_target_columns_on_each_fk_connector(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        sources = {conn.data["SourceColumn"] for conn in conns}
        targets = {conn.data["TargetColumn"] for conn in conns}
        assert "orders.user_id" in sources
        assert "users.id" in targets
        assert "order_items.order_id" in sources
        assert "orders.id" in targets

    def it_accepts_alternate_fk_separator_syntax(self):
        diagram = erd_from_models(
            tables={
                "users": {"columns": [("id", "int", "PK")]},
                "orders": {
                    "columns": [
                        ("id", "int", "PK"),
                        # space-separated form: "FK users.id"
                        ("user_id", "int", "FK users.id"),
                    ],
                },
            },
        )
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        assert len(conns) == 1


# ---------------------------------------------------------------------------
# DescribeErdLayout — auto-layout selection
# ---------------------------------------------------------------------------


class DescribeErdLayout:
    def it_lays_out_tables_at_distinct_positions_when_fks_exist(self):
        diagram = erd_from_models(tables=_FIXTURE_TABLES)
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        positions = {(float(b.pin_x), float(b.pin_y)) for b in boxes}
        # No two tables stacked exactly on top of each other.
        assert len(positions) == len(boxes)

    def it_lays_out_disjoint_tables_at_distinct_positions(self):
        diagram = erd_from_models(
            tables={
                "a": {"columns": [("id", "int", "PK")]},
                "b": {"columns": [("id", "int", "PK")]},
                "c": {"columns": [("id", "int", "PK")]},
            },
        )
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        positions = {(float(b.pin_x), float(b.pin_y)) for b in boxes}
        # Force-directed layout spreads disjoint nodes apart.
        assert len(positions) == 3

    def it_accepts_an_explicit_layout_kind(self):
        # No FK edges → default would be force-directed; force grid.
        diagram = erd_from_models(
            tables={
                "a": {"columns": [("id", "int", "PK")]},
                "b": {"columns": [("id", "int", "PK")]},
                "c": {"columns": [("id", "int", "PK")]},
                "d": {"columns": [("id", "int", "PK")]},
            },
            layout="grid",
        )
        # Just assert it doesn't blow up and produces 4 boxes at
        # distinct positions.
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        positions = {(float(b.pin_x), float(b.pin_y)) for b in boxes}
        assert len(positions) == 4

    def it_rejects_an_unknown_layout_kind(self):
        with pytest.raises(ValueError, match="layout="):
            erd_from_models(tables=_FIXTURE_TABLES, layout="spiral")


# ---------------------------------------------------------------------------
# DescribeErdValidation — rejection paths
# ---------------------------------------------------------------------------


class DescribeErdValidation:
    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError):
            erd_from_models(tables=_FIXTURE_TABLES, title=123)  # type: ignore[arg-type]

    def it_rejects_an_empty_tables_mapping(self):
        with pytest.raises(ValueError, match="at least one"):
            erd_from_models(tables={})

    def it_rejects_a_non_mapping_tables_argument(self):
        with pytest.raises(ValueError, match="must be a Mapping"):
            erd_from_models(tables=[("users", {})])  # type: ignore[arg-type]

    def it_rejects_a_table_with_no_columns_key(self):
        with pytest.raises(ValueError, match="missing a non-empty 'columns'"):
            erd_from_models(tables={"users": {}})

    def it_rejects_a_table_with_an_empty_columns_list(self):
        with pytest.raises(ValueError, match="missing a non-empty 'columns'"):
            erd_from_models(tables={"users": {"columns": []}})

    def it_rejects_a_non_list_columns_value(self):
        with pytest.raises(ValueError, match="'columns' must be a list"):
            erd_from_models(tables={"users": {"columns": "id int"}})

    def it_rejects_a_non_tuple_column_entry(self):
        with pytest.raises(ValueError, match="must be a"):
            erd_from_models(
                tables={"users": {"columns": ["id"]}},  # type: ignore[list-item]
            )

    def it_rejects_a_column_with_wrong_arity(self):
        with pytest.raises(ValueError, match="2 or 3 fields"):
            erd_from_models(
                tables={"users": {"columns": [("id", "int", "PK", "extra")]}},
            )

    def it_rejects_a_blank_column_name(self):
        with pytest.raises(ValueError, match="'name' must be a non-empty"):
            erd_from_models(
                tables={"users": {"columns": [("", "int")]}},
            )

    def it_rejects_a_blank_column_type(self):
        with pytest.raises(ValueError, match="'type' must be a non-empty"):
            erd_from_models(
                tables={"users": {"columns": [("id", "")]}},
            )

    def it_rejects_a_blank_table_name(self):
        with pytest.raises(ValueError, match="non-empty str"):
            erd_from_models(
                tables={"   ": {"columns": [("id", "int")]}},
            )


# ---------------------------------------------------------------------------
# DescribeParseSqlDdl — direct parser tests
# ---------------------------------------------------------------------------


class DescribeParseSqlDdl:
    def it_parses_a_simple_create_table(self):
        out = parse_sql_ddl("CREATE TABLE t (id INT, name VARCHAR(50));")
        assert "t" in out
        assert out["t"] == [("id", "INT", ""), ("name", "VARCHAR(50)", "")]

    def it_extracts_an_inline_primary_key(self):
        out = parse_sql_ddl("CREATE TABLE t (id INT PRIMARY KEY);")
        assert out["t"] == [("id", "INT", "PK")]

    def it_extracts_inline_unique_and_not_null(self):
        out = parse_sql_ddl(
            "CREATE TABLE t ("
            "id INT, "
            "email VARCHAR(255) UNIQUE, "
            "name VARCHAR(50) NOT NULL"
            ");"
        )
        assert out["t"][1] == ("email", "VARCHAR(255)", "UNIQUE")
        assert out["t"][2] == ("name", "VARCHAR(50)", "NOT NULL")

    def it_extracts_an_inline_references_clause(self):
        out = parse_sql_ddl(
            "CREATE TABLE orders ("
            "id INT PRIMARY KEY, "
            "user_id INT REFERENCES users(id)"
            ");"
        )
        assert out["orders"][1] == ("user_id", "INT", "FK->users.id")

    def it_extracts_a_table_level_primary_key(self):
        out = parse_sql_ddl(
            "CREATE TABLE t (id INT, name VARCHAR(50), PRIMARY KEY (id));"
        )
        assert out["t"][0] == ("id", "INT", "PK")

    def it_extracts_a_table_level_foreign_key(self):
        out = parse_sql_ddl(
            "CREATE TABLE orders ("
            "id INT, "
            "user_id INT, "
            "FOREIGN KEY (user_id) REFERENCES users(id)"
            ");"
        )
        assert out["orders"][1] == ("user_id", "INT", "FK->users.id")

    def it_handles_a_named_constraint_clause(self):
        out = parse_sql_ddl(
            "CREATE TABLE orders ("
            "id INT, "
            "user_id INT, "
            "CONSTRAINT fk_orders_user "
            "FOREIGN KEY (user_id) REFERENCES users(id)"
            ");"
        )
        assert out["orders"][1] == ("user_id", "INT", "FK->users.id")

    def it_strips_line_and_block_comments(self):
        out = parse_sql_ddl(
            "/* doc */ -- intro\n"
            "CREATE TABLE t (\n"
            "    id INT  -- pk\n"
            "    /* inline */\n"
            ");"
        )
        assert out["t"] == [("id", "INT", "")]

    def it_parses_multiple_create_table_statements(self):
        out = parse_sql_ddl(
            "CREATE TABLE a (id INT);"
            "CREATE TABLE b (id INT);"
        )
        assert set(out.keys()) == {"a", "b"}

    def it_handles_if_not_exists(self):
        out = parse_sql_ddl(
            "CREATE TABLE IF NOT EXISTS users (id INT);"
        )
        assert "users" in out

    def it_handles_backtick_quoted_identifiers(self):
        out = parse_sql_ddl(
            "CREATE TABLE `users` (`id` INT, `email` VARCHAR(255));"
        )
        assert "users" in out
        assert out["users"][0][0] == "id"

    def it_handles_a_schema_prefix(self):
        out = parse_sql_ddl("CREATE TABLE app.users (id INT);")
        # We drop the schema and key by the table name itself.
        assert "users" in out

    def it_tolerates_a_missing_terminating_semicolon(self):
        out = parse_sql_ddl("CREATE TABLE t (id INT)")
        assert "t" in out

    def it_handles_decimal_with_inner_comma_in_type(self):
        out = parse_sql_ddl(
            "CREATE TABLE prices (id INT, total DECIMAL(10, 2));"
        )
        assert out["prices"][1] == ("total", "DECIMAL(10, 2)", "")

    def it_skips_unrecognised_statements(self):
        out = parse_sql_ddl(
            "CREATE INDEX ix_users_email ON users(email);\n"
            "CREATE TABLE users (id INT);"
        )
        # CREATE INDEX is silently dropped; CREATE TABLE picked up.
        assert set(out.keys()) == {"users"}

    def it_returns_an_empty_dict_for_empty_input(self):
        assert parse_sql_ddl("") == {}

    def it_rejects_a_non_string_argument(self):
        with pytest.raises(TypeError, match="must be a str"):
            parse_sql_ddl(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DescribeErdFromSql — end-to-end SQL → diagram path
# ---------------------------------------------------------------------------


class DescribeErdFromSql:
    def it_builds_a_diagram_from_a_sql_string(self):
        diagram = erd_from_sql(_FIXTURE_SQL)
        assert isinstance(diagram, vsdx.VisioDocument)
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        # 3 tables — no title band because title was empty.
        assert len(boxes) == 3

    def it_emits_fk_connectors_from_the_parsed_schema(self):
        diagram = erd_from_sql(_FIXTURE_SQL)
        conns = [
            s for s in diagram.pages[0].shapes if isinstance(s, Connector)
        ]
        # orders.user_id -> users.id, order_items.order_id -> orders.id
        assert len(conns) == 2

    def it_reads_sql_from_a_str_path(self, tmp_path):
        path = tmp_path / "schema.sql"
        path.write_text(_FIXTURE_SQL, encoding="utf-8")
        diagram = erd_from_sql(str(path))
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        assert len(boxes) == 3

    def it_reads_sql_from_a_PathLike(self, tmp_path):
        path: Path = tmp_path / "schema.sql"
        path.write_text(_FIXTURE_SQL, encoding="utf-8")
        # pathlib.Path is os.PathLike — should always read from disk.
        diagram = erd_from_sql(path)
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_rejects_an_input_with_no_create_table_statements(self):
        with pytest.raises(ValueError, match="no parseable CREATE TABLE"):
            erd_from_sql("-- just a comment, no schema\n")

    def it_rejects_a_non_string_path_or_string(self):
        with pytest.raises(TypeError, match="must be a str or os.PathLike"):
            erd_from_sql(123)  # type: ignore[arg-type]

    def it_propagates_the_layout_kwarg(self):
        # Without FKs, default would be force-directed; force grid.
        diagram = erd_from_sql(
            "CREATE TABLE a (id INT PRIMARY KEY);\n"
            "CREATE TABLE b (id INT PRIMARY KEY);\n",
            layout="grid",
        )
        boxes = [
            s
            for s in diagram.pages[0].shapes
            if not isinstance(s, Connector) and s.text
        ]
        assert len(boxes) == 2


# ---------------------------------------------------------------------------
# DescribeErdRoundTrip — save / open
# ---------------------------------------------------------------------------


class DescribeErdRoundTrip:
    def it_serialises_and_re_opens_cleanly(self):
        diagram = erd_from_models(
            tables=_FIXTURE_TABLES, title="Schema 2026"
        )
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reloaded = vsdx.VisioPackageOpener.open(buf)
        assert len(reloaded.pages) == 1


# ---------------------------------------------------------------------------
# DescribeKitConstants — re-export sanity
# ---------------------------------------------------------------------------


class DescribeKitConstants:
    def it_exposes_the_constraint_token_constants(self):
        assert ERD_CONSTRAINT_PK == "PK"
        assert ERD_CONSTRAINT_UNIQUE == "UNIQUE"
        assert ERD_CONSTRAINT_NOT_NULL == "NOT NULL"
        assert ERD_CONSTRAINT_FK_PREFIX == "FK"
