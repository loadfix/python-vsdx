"""Visio ShapeSheet formula language — parser, evaluator, and dependency graph.

The ShapeSheet is Visio's spreadsheet-like model for shape geometry, style,
custom properties, and connector routing. A cell (``<Cell N="..." V="..."
F="..."/>``) can carry a literal value (``@V``) and/or a formula expression
(``@F``). Visio desktop recalculates ``@F`` at open time; this module lets us
do the same from pure Python so authoring libraries can produce correct
``@V`` values ahead of time and keep them live when dependent cells change.

Public entry points
-------------------

- :func:`parse` — parse a formula string into an AST node.
- :func:`evaluate` — evaluate an AST (or a string) against a
  :class:`ShapeSheetContext`.
- :class:`ShapeSheetContext` — the resolver protocol — anything that can
  look up a named cell by reference string.
- :class:`DependencyGraph` — tracks cell-to-cell dependencies and performs
  topologically-ordered recalculation on cell edits.
- :class:`FormulaError` — base class for all parser / evaluator errors.

The package is deliberately self-contained: it has no runtime dependency on
``lxml`` or on the wider vsdx proxy layer. It operates purely on formula
strings and a ``Mapping``-like resolver, which makes it straightforward to
unit-test and reuse from the ``oxml``/``shapes`` tracks without circular
imports.

See the Microsoft Visio ShapeSheet reference for the canonical function
catalogue:

- https://learn.microsoft.com/en-us/office/client-developer/visio/visio-file-format-reference
- https://learn.microsoft.com/en-us/office/client-developer/visio/functions-reference
"""

from __future__ import annotations

from vsdx.formula.builtins import (
    BUILTINS,
    FUNCTION_NAMES,
    BuiltinFunction,
    register_function,
)
from vsdx.formula.context import (
    MappingShapeSheetContext,
    ShapeSheetContext,
    cell_ref_to_string,
    parse_cell_ref,
)
from vsdx.formula.errors import (
    FormulaCycleError,
    FormulaDepthError,
    FormulaError,
    FormulaEvaluationError,
    FormulaParseError,
    FormulaTypeError,
)
from vsdx.formula.evaluator import Evaluator, evaluate
from vsdx.formula.graph import DependencyGraph
from vsdx.formula.integration import ShapeContext, for_shape
from vsdx.formula.nodes import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    FunctionCall,
    Node,
    NumberLiteral,
    StringLiteral,
    UnaryOp,
)
from vsdx.formula.parser import Parser, parse
from vsdx.formula.tokenizer import Token, TokenKind, tokenize

class Context:
    """Namespace facade over the resolver constructors.

    Exposed for the documented ``Context.for_shape(shape)`` /
    ``Context.for_mapping(...)`` entry points used in user-facing
    examples. The class deliberately has no instance state — it just
    bundles factory classmethods so callers can write
    ``vsdx.formula.Context.for_shape(s)`` instead of importing the
    underlying functions.

    .. versionadded:: 0.3.0
    """

    @staticmethod
    def for_shape(
        shape_or_element: object, *, strict: bool = False
    ) -> ShapeContext:
        """Build a live :class:`ShapeContext` for *shape_or_element*.

        Equivalent to :func:`vsdx.formula.for_shape`. Accepts either a
        :class:`~vsdx.shapes.base.Shape` proxy or a bare
        ``CT_Shape`` oxml element.
        """

        return for_shape(shape_or_element, strict=strict)

    @staticmethod
    def for_mapping(
        cells=None, *, strict: bool = False
    ) -> MappingShapeSheetContext:
        """Build a :class:`MappingShapeSheetContext` over an explicit dict.

        Convenience for unit tests and tooling that wants to evaluate
        formulas without a live shape — pass a dict whose keys are
        canonical ``CellRef.qualified()`` strings.
        """

        return MappingShapeSheetContext(cells, strict=strict)


__all__ = [
    "BUILTINS",
    "BinaryOp",
    "BoolLiteral",
    "BuiltinFunction",
    "CellRef",
    "Context",
    "DependencyGraph",
    "Evaluator",
    "FUNCTION_NAMES",
    "FormulaCycleError",
    "FormulaDepthError",
    "FormulaError",
    "FormulaEvaluationError",
    "FormulaParseError",
    "FormulaTypeError",
    "FunctionCall",
    "MappingShapeSheetContext",
    "Node",
    "NumberLiteral",
    "Parser",
    "ShapeContext",
    "ShapeSheetContext",
    "StringLiteral",
    "Token",
    "TokenKind",
    "UnaryOp",
    "cell_ref_to_string",
    "evaluate",
    "for_shape",
    "parse",
    "parse_cell_ref",
    "register_function",
    "tokenize",
]
