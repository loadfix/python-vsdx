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
    FormulaError,
    FormulaEvaluationError,
    FormulaParseError,
    FormulaTypeError,
)
from vsdx.formula.evaluator import Evaluator, evaluate
from vsdx.formula.graph import DependencyGraph
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

__all__ = [
    "BUILTINS",
    "BinaryOp",
    "BoolLiteral",
    "BuiltinFunction",
    "CellRef",
    "DependencyGraph",
    "Evaluator",
    "FUNCTION_NAMES",
    "FormulaCycleError",
    "FormulaError",
    "FormulaEvaluationError",
    "FormulaParseError",
    "FormulaTypeError",
    "FunctionCall",
    "MappingShapeSheetContext",
    "Node",
    "NumberLiteral",
    "Parser",
    "ShapeSheetContext",
    "StringLiteral",
    "Token",
    "TokenKind",
    "UnaryOp",
    "cell_ref_to_string",
    "evaluate",
    "parse",
    "parse_cell_ref",
    "register_function",
    "tokenize",
]
