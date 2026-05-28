# Copyright 2026 The python-vsdx Authors
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the issue-#118 ``DataSource`` overlay machinery.

Covers the four graphic kinds (text-callout, icon-set, data-bar,
color-by-value), shape→row binding, save/load round-trip
preservation, and :meth:`DataSource.refresh` re-reading the CSV.

CSV files are written into pytest's :func:`tmp_path` fixture so each
test is hermetic and does not need a corpus fixture.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import io
import textwrap
from pathlib import Path

import pytest

import vsdx
from vsdx.data_sources import (
    GRAPHIC_KIND_COLOR_BY_VALUE,
    GRAPHIC_KIND_DATA_BAR,
    GRAPHIC_KIND_ICON_SET,
    GRAPHIC_KIND_TEXT_CALLOUT,
    DataGraphicSpec,
    DataSource,
    DataSources,
    _decode_rule,
    _encode_rule,
    _evaluate_when,
    _named_cell_v,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_csv(tmp_path: Path, name: str, body: str) -> Path:
    """Drop *body* into *tmp_path/name* and return the path.

    Mirrors the indentation-stripping ``textwrap.dedent`` pattern so
    callers can keep CSV literals readable in tests.
    """
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


def _doc_with_page():
    """Return ``(doc, page, shape)`` for a fresh document with one rectangle."""
    doc = vsdx.Visio()
    page = doc.pages.add_page()
    shape = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
    return doc, page, shape


# ---------------------------------------------------------------------------
# DataSources collection
# ---------------------------------------------------------------------------


class DescribeDataSourcesCollection:
    def it_exposes_an_empty_collection_on_a_fresh_document(self):
        doc = vsdx.Visio()
        assert isinstance(doc.data_sources, DataSources)
        assert list(doc.data_sources) == []
        assert len(doc.data_sources) == 0

    def it_registers_a_source_via_page_add_data_source(self, tmp_path):
        doc, page, _ = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID\n1\n")
        ds = page.add_data_source(str(path))
        assert isinstance(ds, DataSource)
        # The collection re-wraps each iteration so we compare by id —
        # DataSource has no custom ``__eq__`` and per-call instances
        # legitimately differ.
        ids = [s.id for s in doc.data_sources]
        assert ids == [ds.id]
        assert len(doc.data_sources) == 1
        assert doc.data_sources[0].path == str(path)

    def it_defaults_the_source_name_to_the_csv_basename(self, tmp_path):
        _, page, _ = _doc_with_page()
        path = _write_csv(tmp_path, "inventory.csv", "ID\n1\n")
        ds = page.add_data_source(str(path))
        assert ds.name == "inventory.csv"

    def it_accepts_an_explicit_source_name_and_default_key(self, tmp_path):
        _, page, _ = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,V\n1,a\n")
        ds = page.add_data_source(str(path), name="alpha", key="ID")
        assert ds.name == "alpha"
        assert ds.key_column == "ID"

    def it_allocates_distinct_ids_per_source(self, tmp_path):
        _, page, _ = _doc_with_page()
        a = page.add_data_source(str(_write_csv(tmp_path, "a.csv", "ID\n")))
        b = page.add_data_source(str(_write_csv(tmp_path, "b.csv", "ID\n")))
        c = page.add_data_source(str(_write_csv(tmp_path, "c.csv", "ID\n")))
        assert sorted([a.id, b.id, c.id]) == [0, 1, 2]

    def it_looks_up_sources_by_id_and_name(self, tmp_path):
        _, page, _ = _doc_with_page()
        a = page.add_data_source(
            str(_write_csv(tmp_path, "a.csv", "ID\n")), name="alpha"
        )
        b = page.add_data_source(
            str(_write_csv(tmp_path, "b.csv", "ID\n")), name="beta"
        )
        doc = page._parent._parent
        assert doc.data_sources.get(a.id).name == "alpha"
        assert doc.data_sources.get(b.id).name == "beta"
        assert doc.data_sources.get_by_name("beta").id == b.id
        assert doc.data_sources.get_by_name("missing") is None

    def it_rejects_an_unknown_graphic_kind(self, tmp_path):
        _, page, _ = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID\n1\n")), key="ID"
        )
        with pytest.raises(ValueError):
            ds.add_data_graphic("ID", "neon-glow")


# ---------------------------------------------------------------------------
# Shape.bind_to_row
# ---------------------------------------------------------------------------


class DescribeShapeBindToRow:
    def it_writes_a_binding_cell_on_the_shape(self, tmp_path):
        _, page, shape = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,V\n1,a\n")), key="ID"
        )
        shape.bind_to_row(ds, key="1")
        assert shape.data_source_binding == (ds.id, "1")

    def it_overwrites_an_existing_binding_idempotently(self, tmp_path):
        _, page, shape = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,V\n1,a\n2,b\n")), key="ID"
        )
        shape.bind_to_row(ds, key="1")
        shape.bind_to_row(ds, key="2")
        assert shape.data_source_binding == (ds.id, "2")

    def it_rejects_non_DataSource_arguments(self, tmp_path):
        _, _, shape = _doc_with_page()
        with pytest.raises(TypeError):
            shape.bind_to_row("not-a-source", key="1")

    def it_records_the_first_binding_key_as_source_default(self, tmp_path):
        _, page, shape = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,V\n1,a\n"))
        )
        # Source has no recorded key column yet.
        assert ds.key_column is None
        shape.bind_to_row(ds, key="ID")
        # First bind promoted ``key`` to the source default.
        assert ds.key_column == "ID"


# ---------------------------------------------------------------------------
# DataSource.add_data_graphic — the four kinds
# ---------------------------------------------------------------------------


class DescribeAddDataGraphic:
    def it_records_a_text_callout_spec(self, tmp_path):
        _, page, _ = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,Owner\n1,Alice\n")), key="ID"
        )
        spec = ds.add_data_graphic(
            field="Owner", kind=GRAPHIC_KIND_TEXT_CALLOUT, position="top"
        )
        assert isinstance(spec, DataGraphicSpec)
        assert spec.field == "Owner"
        assert spec.kind == GRAPHIC_KIND_TEXT_CALLOUT
        assert spec.position == "top"
        assert spec.rules == []

    def it_records_an_icon_set_spec_with_rules(self, tmp_path):
        _, page, _ = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,Status\n1,OK\n")), key="ID"
        )
        spec = ds.add_data_graphic(
            field="Status",
            kind=GRAPHIC_KIND_ICON_SET,
            rules=[
                {"when": 'Status == "OK"', "icon": "green-check"},
                {"when": 'Status == "Warn"', "icon": "yellow-triangle"},
                {"when": 'Status == "Down"', "icon": "red-x"},
            ],
            position="top-right",
        )
        # Rules round-trip in declaration order.
        assert [r["icon"] for r in spec.rules] == [
            "green-check",
            "yellow-triangle",
            "red-x",
        ]
        assert spec.rules[0]["when"] == 'Status == "OK"'

    def it_records_a_data_bar_spec_with_bounds(self, tmp_path):
        _, page, _ = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,CPU\n1,42\n")), key="ID"
        )
        spec = ds.add_data_graphic(
            field="CPU",
            kind=GRAPHIC_KIND_DATA_BAR,
            min=0,
            max=100,
            color="theme.primary",
            position="bottom",
        )
        assert spec.min_value == 0.0
        assert spec.max_value == 100.0
        assert spec.color == "theme.primary"

    def it_records_a_color_by_value_spec(self, tmp_path):
        _, page, _ = _doc_with_page()
        ds = page.add_data_source(
            str(_write_csv(tmp_path, "x.csv", "ID,Status\n1,Down\n")), key="ID"
        )
        spec = ds.add_data_graphic(
            field="Status",
            kind=GRAPHIC_KIND_COLOR_BY_VALUE,
            rules=[
                {"when": 'Status == "Down"', "color": "#ff0000"},
                {"when": 'Status == "OK"', "color": "#00ff00"},
            ],
        )
        assert spec.kind == GRAPHIC_KIND_COLOR_BY_VALUE
        assert spec.rules[0]["color"] == "#ff0000"


# ---------------------------------------------------------------------------
# DataSource.refresh — apply graphics to bound shapes
# ---------------------------------------------------------------------------


class DescribeRefresh:
    def it_mirrors_csv_row_values_into_shape_data(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(
            tmp_path, "x.csv", "ID,Owner,CPU\nA,Alice,42\nB,Bob,80\n"
        )
        ds = page.add_data_source(str(path), key="ID")
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert shape.data["Owner"] == "Alice"
        # Numeric mirror happens even when the field type is string —
        # ShapeData fields default to STRING, so coerced retrieval matches
        # the raw CSV value.
        assert shape.data["CPU"] == "42"

    def it_applies_a_text_callout_overlay(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,Owner\nA,Alice\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(field="Owner", kind=GRAPHIC_KIND_TEXT_CALLOUT)
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceCallout") == "Alice"

    def it_applies_an_icon_set_first_match_wins(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(
            tmp_path, "x.csv", "ID,Status\nA,Warn\n"
        )
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(
            field="Status",
            kind=GRAPHIC_KIND_ICON_SET,
            rules=[
                {"when": 'Status == "OK"', "icon": "green"},
                {"when": 'Status == "Warn"', "icon": "yellow"},
                {"when": 'Status == "Down"', "icon": "red"},
            ],
        )
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceIcon") == "yellow"

    def it_applies_a_data_bar_normalised_against_explicit_bounds(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,CPU\nA,75\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(
            field="CPU", kind=GRAPHIC_KIND_DATA_BAR, min=0, max=100
        )
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        # 75 / (100 - 0) = 0.75
        assert _named_cell_v(shape._element, "DataSourceBar") == "0.75"

    def it_clamps_data_bar_fractions_to_0_and_1(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,CPU\nA,250\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(
            field="CPU", kind=GRAPHIC_KIND_DATA_BAR, min=0, max=100
        )
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceBar") == "1"

    def it_auto_normalises_data_bar_when_bounds_are_missing(self, tmp_path):
        _, page, _ = _doc_with_page()
        # Three shapes with values 0, 50, 100 — auto-min/max should
        # spread them across [0, 1].
        page2 = page  # reuse single page
        s_lo = page2.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        s_mid = page2.shapes.add_shape("Rectangle", at=(2, 1), size=(1, 1))
        s_hi = page2.shapes.add_shape("Rectangle", at=(3, 1), size=(1, 1))
        path = _write_csv(
            tmp_path, "x.csv", "ID,V\nlo,0\nmid,50\nhi,100\n"
        )
        ds = page2.add_data_source(str(path), key="ID")
        ds.add_data_graphic(field="V", kind=GRAPHIC_KIND_DATA_BAR)
        s_lo.bind_to_row(ds, key="lo")
        s_mid.bind_to_row(ds, key="mid")
        s_hi.bind_to_row(ds, key="hi")
        ds.refresh()
        assert _named_cell_v(s_lo._element, "DataSourceBar") == "0"
        assert _named_cell_v(s_mid._element, "DataSourceBar") == "0.5"
        assert _named_cell_v(s_hi._element, "DataSourceBar") == "1"

    def it_applies_color_by_value_via_first_matching_rule(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,Status\nA,Down\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(
            field="Status",
            kind=GRAPHIC_KIND_COLOR_BY_VALUE,
            rules=[
                {"when": 'Status == "Down"', "color": "#ff0000"},
                {"when": 'Status == "OK"', "color": "#00ff00"},
            ],
        )
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert shape.fill_foregnd == "#ff0000"

    def it_picks_up_csv_changes_on_a_subsequent_refresh(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,Owner\nA,Alice\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(field="Owner", kind=GRAPHIC_KIND_TEXT_CALLOUT)
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceCallout") == "Alice"
        # Mutate the CSV — bound shape should pick up the change.
        path.write_text("ID,Owner\nA,Bob\n", encoding="utf-8")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceCallout") == "Bob"

    def it_clears_overlay_cells_when_the_key_no_longer_matches(self, tmp_path):
        _, page, shape = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,Owner\nA,Alice\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(field="Owner", kind=GRAPHIC_KIND_TEXT_CALLOUT)
        shape.bind_to_row(ds, key="A")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceCallout") == "Alice"
        # Drop the bound row — the callout cell should be cleared.
        path.write_text("ID,Owner\nB,Bob\n", encoding="utf-8")
        ds.refresh()
        assert _named_cell_v(shape._element, "DataSourceCallout") is None

    def it_returns_the_count_of_updated_shapes(self, tmp_path):
        _, page, _ = _doc_with_page()
        path = _write_csv(tmp_path, "x.csv", "ID,V\nA,1\nB,2\n")
        ds = page.add_data_source(str(path), key="ID")
        ds.add_data_graphic(field="V", kind=GRAPHIC_KIND_TEXT_CALLOUT)
        s_a = page.shapes.add_shape("Rectangle", at=(1, 1), size=(1, 1))
        s_b = page.shapes.add_shape("Rectangle", at=(2, 1), size=(1, 1))
        s_a.bind_to_row(ds, key="A")
        s_b.bind_to_row(ds, key="B")
        # Add a third unbound shape that shouldn't count.
        page.shapes.add_shape("Rectangle", at=(3, 1), size=(1, 1))
        assert ds.refresh() == 2

    def it_tolerates_a_missing_csv_file(self, tmp_path):
        _, page, shape = _doc_with_page()
        ds = page.add_data_source(
            str(tmp_path / "missing.csv"), name="ghost", key="ID"
        )
        ds.add_data_graphic(field="V", kind=GRAPHIC_KIND_TEXT_CALLOUT)
        shape.bind_to_row(ds, key="A")
        # No exception — refresh just clears overlays.
        assert ds.refresh() == 0


# ---------------------------------------------------------------------------
# Round-trip safety — sources + graphics + bindings survive save / open.
# ---------------------------------------------------------------------------


class DescribeRoundTrip:
    def it_preserves_sources_graphics_and_bindings_through_save_open(
        self, tmp_path
    ):
        path = _write_csv(
            tmp_path, "x.csv", "ID,Owner,CPU,Status\nA,Alice,75,OK\n"
        )
        doc, page, shape = _doc_with_page()
        ds = page.add_data_source(str(path), name="inventory", key="ID")
        ds.add_data_graphic(field="Owner", kind=GRAPHIC_KIND_TEXT_CALLOUT)
        ds.add_data_graphic(
            field="CPU", kind=GRAPHIC_KIND_DATA_BAR, min=0, max=100
        )
        ds.add_data_graphic(
            field="Status",
            kind=GRAPHIC_KIND_ICON_SET,
            rules=[
                {"when": 'Status == "OK"', "icon": "green-check"},
            ],
        )
        ds.add_data_graphic(
            field="Status",
            kind=GRAPHIC_KIND_COLOR_BY_VALUE,
            rules=[{"when": 'Status == "OK"', "color": "#00ff00"}],
        )
        shape.bind_to_row(ds, key="A")
        # Save + reopen.
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        doc2 = vsdx.Visio(buf)
        sources = list(doc2.data_sources)
        assert len(sources) == 1
        ds2 = sources[0]
        assert ds2.name == "inventory"
        assert ds2.path == str(path)
        assert ds2.key_column == "ID"
        kinds = [s.kind for s in ds2.graphics]
        assert kinds == [
            GRAPHIC_KIND_TEXT_CALLOUT,
            GRAPHIC_KIND_DATA_BAR,
            GRAPHIC_KIND_ICON_SET,
            GRAPHIC_KIND_COLOR_BY_VALUE,
        ]
        # Locate the same shape on the reopened document and check the binding.
        reopened_shape = list(doc2.pages[0].shapes)[0]
        assert reopened_shape.data_source_binding == (ds2.id, "A")
        # And refresh on the reopened document still applies overlays.
        ds2.refresh()
        assert _named_cell_v(reopened_shape._element, "DataSourceCallout") == "Alice"


# ---------------------------------------------------------------------------
# Internal helpers — rule encoding / restricted eval.
# ---------------------------------------------------------------------------


class DescribeRuleEncoding:
    def it_round_trips_rule_dicts(self):
        rule = {"when": 'Status == "OK"', "icon": "green-check"}
        assert _decode_rule(_encode_rule(rule)) == {
            "when": 'Status == "OK"',
            "icon": "green-check",
        }

    def it_escapes_pipe_characters_in_values(self):
        rule = {"when": "a|b == c"}
        encoded = _encode_rule(rule)
        # The literal pipe in the value must survive the split.
        assert _decode_rule(encoded)["when"] == "a|b == c"

    def it_rejects_pipe_or_equals_in_keys(self):
        with pytest.raises(ValueError):
            _encode_rule({"a|b": "c"})


class DescribeWhenEvaluation:
    def it_evaluates_a_truthy_when_against_a_row(self):
        assert _evaluate_when('Status == "OK"', {"Status": "OK"}) is True

    def it_returns_false_for_non_matching_rules(self):
        assert _evaluate_when('Status == "OK"', {"Status": "Down"}) is False

    def it_swallows_evaluation_errors(self):
        # Reference to a missing column doesn't blow up the refresh.
        assert _evaluate_when("missing == 1", {}) is False
        # Syntax errors fall back to ``False`` too.
        assert _evaluate_when("???", {}) is False
