"""Dependency graph + topological recalculation over ShapeSheet cells.

Visio's ShapeSheet recalculation is a classic spreadsheet recalc: cells
hold formula expressions, edits to one cell trigger re-evaluation of
every cell that (transitively) depends on it. Our implementation:

1. ``register(cell_id, formula_source)`` parses the AST once and extracts
   every :class:`CellRef` it contains as a dependency edge.
2. ``set_value(cell_id, value)`` manually sets a literal value and marks
   the node stale-free.
3. ``invalidate(cell_id)`` marks the cell (and everything downstream)
   dirty.
4. ``recalc()`` walks the graph in topological order, re-evaluating any
   dirty node against the supplied :class:`ShapeSheetContext`. Returns
   the set of cells whose values actually changed.

The graph detects cycles at recalc time and raises
:class:`FormulaCycleError`, matching Visio's behaviour (it displays a
``#REF!`` indicator rather than entering an infinite loop).

Scope notes for 0.1.0
---------------------

- The graph is shape-local. Cross-shape refs (``Sheet.5!Width``) are
  recognised at parse time but the graph owner is responsible for
  routing those through a higher-level orchestrator that owns multiple
  graphs (one per shape). 0.1.0 ships the single-shape case.
- Recalc is synchronous and single-threaded. Visio's async recalc during
  long drag operations is out of scope.
"""

from __future__ import annotations

from typing import Iterable, Optional

from vsdx.formula.context import MappingShapeSheetContext, ShapeSheetContext
from vsdx.formula.errors import FormulaCycleError, FormulaEvaluationError
from vsdx.formula.evaluator import Evaluator
from vsdx.formula.nodes import (
    BinaryOp,
    CellRef,
    FormulaValue,
    FunctionCall,
    Node,
    UnaryOp,
)
from vsdx.formula.parser import parse


def extract_refs(node: Node) -> list[CellRef]:
    """Walk an AST and collect every :class:`CellRef` it mentions.

    Dependencies are returned in source-order, which makes the
    dependency graph's edge lists reproducible — useful for
    deterministic test assertions.
    """
    refs: list[CellRef] = []

    def walk(n: Node) -> None:
        if isinstance(n, CellRef):
            refs.append(n)
            return
        if isinstance(n, UnaryOp):
            walk(n.operand)
            return
        if isinstance(n, BinaryOp):
            walk(n.left)
            walk(n.right)
            return
        if isinstance(n, FunctionCall):
            for arg in n.args:
                walk(arg)
            return

    walk(node)
    return refs


class DependencyGraph:
    """Single-shape ShapeSheet recalc graph.

    Cell identifiers are arbitrary strings — typically the canonical
    ``CellRef.qualified()`` form ("Width", "User.Scale", "Geometry1.X1").
    Callers decide the namespace; the graph just indexes by whatever
    string it's handed.
    """

    def __init__(self, context: Optional[ShapeSheetContext] = None):
        # Cell ID -> parsed AST (or None if value-only / literal).
        self._formulas: dict[str, Optional[Node]] = {}
        # Cell ID -> current value. ``None`` means "unevaluated / unknown".
        self._values: dict[str, Optional[FormulaValue]] = {}
        # Out-edges: "this cell references these cells" — cell_id -> set(deps).
        self._depends_on: dict[str, set[str]] = {}
        # In-edges: "these cells reference this cell" — cell_id -> set(rev).
        self._dependents: dict[str, set[str]] = {}
        # Dirty set — cells whose values are stale.
        self._dirty: set[str] = set()
        # Adapter context: every live lookup goes through a context so
        # evaluator code doesn't have to know about the graph directly.
        self._context = context if context is not None else _GraphContext(self)
        self._evaluator = Evaluator(self._context)

    # --------------------------------------------------------------- mutation

    def register(self, cell_id: str, formula: str) -> None:
        """Register or update a cell that carries a formula.

        Re-registering a cell replaces its formula, drops old edges, and
        marks the cell + all downstream dependents dirty.
        """
        ast = parse(formula)
        self._formulas[cell_id] = ast
        self._rewire(cell_id, extract_refs(ast))
        self._mark_dirty(cell_id)

    def set_value(self, cell_id: str, value: FormulaValue) -> None:
        """Assign a literal value to a cell (no formula)."""
        self._formulas[cell_id] = None
        self._rewire(cell_id, [])
        self._values[cell_id] = value
        # Value changed — downstream is dirty, but the cell itself is clean.
        self._dirty.discard(cell_id)
        for downstream in self._dependents.get(cell_id, ()):
            self._mark_dirty(downstream)

    def invalidate(self, cell_id: str) -> None:
        """Mark ``cell_id`` (and transitive dependents) dirty."""
        self._mark_dirty(cell_id)

    def _rewire(self, cell_id: str, refs: Iterable[CellRef]) -> None:
        # Drop old out-edges.
        old = self._depends_on.pop(cell_id, set())
        for dep in old:
            self._dependents.get(dep, set()).discard(cell_id)
        # Install new out-edges.
        new_deps = {ref.qualified() for ref in refs}
        self._depends_on[cell_id] = new_deps
        for dep in new_deps:
            self._dependents.setdefault(dep, set()).add(cell_id)
            # Ensure every dep cell has an entry — even if it was never
            # explicitly registered — so recalc can probe it later.
            self._formulas.setdefault(dep, None)
            self._values.setdefault(dep, None)

    def _mark_dirty(self, cell_id: str) -> None:
        # BFS over dependents so we don't recurse on long chains.
        stack = [cell_id]
        while stack:
            current = stack.pop()
            if current in self._dirty:
                continue
            self._dirty.add(current)
            stack.extend(self._dependents.get(current, ()))

    # --------------------------------------------------------------- queries

    def get(self, cell_id: str) -> Optional[FormulaValue]:
        """Return the last-computed value for ``cell_id`` (may be stale)."""
        return self._values.get(cell_id)

    def depends_on(self, cell_id: str) -> set[str]:
        """Return the set of cells ``cell_id``'s formula references."""
        return set(self._depends_on.get(cell_id, ()))

    def dependents_of(self, cell_id: str) -> set[str]:
        """Return the set of cells whose formulas reference ``cell_id``."""
        return set(self._dependents.get(cell_id, ()))

    def is_dirty(self, cell_id: str) -> bool:
        return cell_id in self._dirty

    # --------------------------------------------------------------- recalc

    def recalc(self, roots: Optional[Iterable[str]] = None) -> set[str]:
        """Re-evaluate every dirty cell (or the transitive closure of ``roots``).

        Returns the set of cells whose value actually changed as a result
        of this pass. Raises :class:`FormulaCycleError` if the graph
        contains a dependency cycle reachable from the work set.
        """
        # Work set: either the dirty set, or the closure of ``roots`` over
        # dependents. Either way we compute a topological order.
        if roots is None:
            work = set(self._dirty)
        else:
            work = set()
            for root in roots:
                self._collect_downstream(root, work)

        if not work:
            return set()

        order = self._topological_order(work)
        changed: set[str] = set()
        for cell_id in order:
            ast = self._formulas.get(cell_id)
            if ast is None:
                # No formula — leave the explicit value alone.
                self._dirty.discard(cell_id)
                continue
            new_value = self._evaluator.eval_ast(ast)
            old_value = self._values.get(cell_id)
            self._values[cell_id] = new_value
            self._dirty.discard(cell_id)
            if new_value != old_value:
                changed.add(cell_id)
        return changed

    def _collect_downstream(self, root: str, out: set[str]) -> None:
        stack = [root]
        while stack:
            current = stack.pop()
            if current in out:
                continue
            out.add(current)
            stack.extend(self._dependents.get(current, ()))

    def _topological_order(self, work: set[str]) -> list[str]:
        """Kahn-style topological sort over the subgraph induced by ``work``.

        A cycle inside ``work`` triggers :class:`FormulaCycleError` with
        the offending cycle in sorted order for stable error messages.
        """
        # Subgraph in-degree, restricted to cells that have formulas.
        in_deg: dict[str, int] = {c: 0 for c in work}
        for cell in work:
            for dep in self._depends_on.get(cell, ()):
                if dep in in_deg:
                    in_deg[cell] += 1
        ready: list[str] = sorted(c for c, d in in_deg.items() if d == 0)
        result: list[str] = []
        while ready:
            # Pop deterministically from the smallest cell-ID to keep
            # recalc outputs reproducible.
            ready.sort()
            current = ready.pop(0)
            result.append(current)
            for downstream in self._dependents.get(current, ()):
                if downstream in in_deg:
                    in_deg[downstream] -= 1
                    if in_deg[downstream] == 0:
                        ready.append(downstream)
        if len(result) != len(in_deg):
            cycle = sorted(c for c, d in in_deg.items() if d > 0 and c not in result)
            raise FormulaCycleError(
                f"cycle detected among cells: {cycle!r}", cycle=cycle
            )
        return result


class _GraphContext:
    """Adapter — resolves cell references against a DependencyGraph's values.

    Used internally when the caller doesn't provide an external context.
    Cross-shape references (``Sheet.N!...``) are not supported via this
    adapter; callers needing them should supply a richer
    :class:`ShapeSheetContext`.
    """

    def __init__(self, graph: "DependencyGraph"):
        self._graph = graph

    def resolve(self, ref: CellRef) -> Optional[FormulaValue]:
        if ref.sheet is not None:
            raise FormulaEvaluationError(
                f"cross-shape references are not supported by the default "
                f"graph context: {ref.qualified()!r}"
            )
        value = self._graph.get(ref.qualified())
        return value


__all__ = ["DependencyGraph", "extract_refs"]
