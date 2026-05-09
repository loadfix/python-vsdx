"""Resolver protocol + helpers for translating cell refs into live values.

The formula evaluator doesn't know or care how a ShapeSheet stores its
cells — whether it's an lxml tree backing the oxml layer, an in-memory
dict from a unit test, or a cache the proxy layer maintains. It just
needs a :class:`ShapeSheetContext` that answers "here's a cell reference,
what's its value".

Concrete implementations:

- :class:`MappingShapeSheetContext` — wraps a plain ``dict[str, value]``
  keyed on ``CellRef.qualified()``. Useful for tests and simple cases.
- The ``vsdx.shapes`` track (Track 3) will add a lxml-backed
  ``ShapeSheetContext`` that looks up live cells on a Shape proxy.
"""

from __future__ import annotations

from typing import Mapping, Optional, Protocol, runtime_checkable

from vsdx.formula.errors import FormulaEvaluationError
from vsdx.formula.nodes import CellRef, FormulaValue


@runtime_checkable
class ShapeSheetContext(Protocol):
    """Anything that can resolve a :class:`CellRef` to a value.

    Implementations should return ``None`` for *optionally present* cells
    (e.g. custom-property ``Prompt`` that the user never authored) and
    raise :class:`FormulaEvaluationError` for hard misses (unknown cell
    name entirely). The evaluator treats ``None`` as a zero-default,
    matching Visio desktop's behaviour.
    """

    def resolve(self, ref: CellRef) -> Optional[FormulaValue]:  # pragma: no cover
        ...


class MappingShapeSheetContext:
    """Simple mapping-backed resolver — mostly for tests.

    Accepts a ``dict`` whose keys are the canonical ``CellRef.qualified()``
    strings (``"Width"``, ``"User.Scale"``, ``"Sheet.5!PinX"``) and whose
    values are the raw numeric / boolean / string the cell carries.
    """

    def __init__(
        self,
        cells: Optional[Mapping[str, FormulaValue]] = None,
        *,
        strict: bool = False,
    ):
        self._cells: dict[str, FormulaValue] = dict(cells) if cells else {}
        self._strict = strict

    def set(self, key: str, value: FormulaValue) -> None:
        self._cells[key] = value

    def get(self, key: str) -> Optional[FormulaValue]:
        return self._cells.get(key)

    def resolve(self, ref: CellRef) -> Optional[FormulaValue]:
        key = ref.qualified()
        if key in self._cells:
            return self._cells[key]
        # Also try a bare ``.name`` fallback so callers can register
        # ``Width`` and have ``ThisShape.Width`` still resolve — matches
        # Visio's implicit self-scope.
        if ref.sheet is not None:
            unscoped = CellRef(
                name=ref.name, section=ref.section, row=ref.row
            ).qualified()
            if unscoped in self._cells:
                return self._cells[unscoped]
        if self._strict:
            raise FormulaEvaluationError(f"unresolved cell reference: {key!r}")
        return None


def parse_cell_ref(text: str) -> CellRef:
    """Parse a single cell-ref string into a :class:`CellRef`.

    Convenience for callers (dependency-graph, oxml) that have a bare
    ``@N`` value rather than a full ``@F`` formula. Supports the same
    axes as the parser's ``_finish_cell_ref`` logic: sheet prefix with
    ``!``, dotted section/row/name.
    """
    if not text:
        raise FormulaEvaluationError("empty cell reference")

    sheet: Optional[str] = None
    if "!" in text:
        sheet, text = text.split("!", 1)
    parts = text.split(".")
    if len(parts) == 1:
        return CellRef(name=parts[0], sheet=sheet, source=text)
    if len(parts) == 2:
        return CellRef(
            name=parts[1], section=parts[0], sheet=sheet, source=text
        )
    if len(parts) == 3:
        return CellRef(
            name=parts[2], section=parts[0], row=parts[1], sheet=sheet, source=text
        )
    # Defensive: fold the middle into row.
    return CellRef(
        name=parts[-1],
        section=parts[0],
        row=".".join(parts[1:-1]),
        sheet=sheet,
        source=text,
    )


def cell_ref_to_string(ref: CellRef) -> str:
    """Serialise a :class:`CellRef` back to ``Sheet.N!Section.Row.Name`` form."""
    return ref.qualified()
