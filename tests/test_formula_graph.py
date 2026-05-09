"""Tests for :mod:`vsdx.formula.graph`."""

from __future__ import annotations

import pytest

from vsdx.formula.context import MappingShapeSheetContext
from vsdx.formula.errors import FormulaCycleError
from vsdx.formula.graph import DependencyGraph, extract_refs
from vsdx.formula.parser import parse


class DescribeExtractRefs:
    def it_collects_cell_refs_from_an_ast(self):
        ast = parse("Width * Height + User.Scale")
        refs = extract_refs(ast)
        assert [r.qualified() for r in refs] == ["Width", "Height", "User.Scale"]

    def it_walks_function_calls(self):
        ast = parse("IF(Width > 0, User.A, Prop.B)")
        refs = extract_refs(ast)
        names = {r.qualified() for r in refs}
        assert names == {"Width", "User.A", "Prop.B"}


class DescribeDependencyGraphWiring:
    def it_records_out_and_in_edges(self):
        g = DependencyGraph()
        g.register("Area", "Width * Height")
        assert g.depends_on("Area") == {"Width", "Height"}
        assert g.dependents_of("Width") == {"Area"}
        assert g.dependents_of("Height") == {"Area"}

    def it_reroutes_edges_on_re_register(self):
        g = DependencyGraph()
        g.register("Out", "A + B")
        g.register("Out", "C + D")
        assert g.depends_on("Out") == {"C", "D"}
        assert g.dependents_of("A") == set()
        assert g.dependents_of("C") == {"Out"}


class DescribeRecalc:
    def it_evaluates_in_dependency_order(self):
        g = DependencyGraph()
        g.set_value("Width", 3.0)
        g.set_value("Height", 4.0)
        g.register("Perimeter", "2 * (Width + Height)")
        g.register("Area", "Width * Height")
        g.register("Ratio", "Area / Perimeter")

        changed = g.recalc()
        assert changed == {"Perimeter", "Area", "Ratio"}
        assert g.get("Perimeter") == 14.0
        assert g.get("Area") == 12.0
        assert g.get("Ratio") == pytest.approx(12.0 / 14.0)

    def it_only_recomputes_downstream_cells_after_value_change(self):
        g = DependencyGraph()
        g.set_value("Width", 3.0)
        g.set_value("Height", 4.0)
        g.register("Area", "Width * Height")
        g.recalc()

        g.set_value("Width", 10.0)
        changed = g.recalc()
        assert changed == {"Area"}
        assert g.get("Area") == 40.0

    def it_reports_no_change_when_values_are_identical(self):
        g = DependencyGraph()
        g.set_value("Width", 5.0)
        g.register("Doubled", "Width * 2")
        g.recalc()

        # Re-setting same value shouldn't cause Doubled's value to flip.
        g.set_value("Width", 5.0)
        changed = g.recalc()
        assert "Doubled" not in changed

    def it_detects_cycles(self):
        g = DependencyGraph()
        g.register("A", "B + 1")
        g.register("B", "A + 1")
        with pytest.raises(FormulaCycleError) as excinfo:
            g.recalc()
        assert set(excinfo.value.cycle) == {"A", "B"}

    def it_recalc_roots_computes_transitive_closure(self):
        g = DependencyGraph()
        g.set_value("Width", 2.0)
        g.register("Area", "Width * 5")
        g.register("Pressure", "Area / 10")
        # Force recalc even though nothing is dirty.
        changed = g.recalc(roots=["Width"])
        # Width has no formula, so it's computed-clean but Area / Pressure evaluate.
        assert "Area" in changed
        assert "Pressure" in changed


class DescribeGraphWithExternalContext:
    def it_delegates_resolution_to_an_external_context(self):
        ctx = MappingShapeSheetContext({"External": 100.0})
        g = DependencyGraph(context=ctx)
        g.register("Ten", "External / 10")
        g.recalc()
        assert g.get("Ten") == 10.0
