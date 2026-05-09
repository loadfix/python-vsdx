"""AST walker that computes formula values against a ShapeSheet context.

The evaluator is stateless — the same :class:`Evaluator` instance can
evaluate many ASTs in sequence. It coerces types using the same implicit
rules as Visio / Excel: numbers and booleans freely interconvert, strings
compare lexicographically, comparison operators always return bool, and
``None`` (unresolved cell) acts as zero in numeric contexts and empty
string in text contexts.
"""

from __future__ import annotations

from typing import Optional, Union

from vsdx.formula.builtins import BUILTINS, _to_bool, _to_number, _to_string
from vsdx.formula.context import ShapeSheetContext
from vsdx.formula.errors import FormulaEvaluationError
from vsdx.formula.nodes import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    FormulaValue,
    FunctionCall,
    Node,
    NumberLiteral,
    StringLiteral,
    UnaryOp,
)
from vsdx.formula.parser import parse


class Evaluator:
    """Evaluates a parsed AST against a :class:`ShapeSheetContext`.

    Callers that need to reuse the same context across many formulas
    should instantiate once and call :meth:`eval_ast` repeatedly. For
    one-shot use see the module-level :func:`evaluate` convenience.
    """

    def __init__(self, context: Optional[ShapeSheetContext] = None):
        self._context = context

    @property
    def context(self) -> Optional[ShapeSheetContext]:
        return self._context

    def eval_ast(self, node: Node) -> FormulaValue:
        """Evaluate a parsed AST node to a concrete value."""
        return self._eval(node)

    def _eval(self, node: Node) -> FormulaValue:
        if isinstance(node, NumberLiteral):
            return node.value
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, BoolLiteral):
            return node.value
        if isinstance(node, CellRef):
            return self._resolve_cell(node)
        if isinstance(node, UnaryOp):
            return self._eval_unary(node)
        if isinstance(node, BinaryOp):
            return self._eval_binary(node)
        if isinstance(node, FunctionCall):
            return self._eval_function(node)
        raise FormulaEvaluationError(f"unknown AST node: {type(node).__name__}")

    def _resolve_cell(self, ref: CellRef) -> FormulaValue:
        if self._context is None:
            raise FormulaEvaluationError(
                f"cannot resolve cell reference {ref.qualified()!r}: no context provided"
            )
        value = self._context.resolve(ref)
        return value if value is not None else 0.0

    def _eval_unary(self, node: UnaryOp) -> FormulaValue:
        operand = self._eval(node.operand)
        if node.op == "-":
            return -_to_number(operand, func="unary '-'")
        if node.op == "+":
            return _to_number(operand, func="unary '+'")
        raise FormulaEvaluationError(f"unknown unary operator {node.op!r}")

    def _eval_binary(self, node: BinaryOp) -> FormulaValue:
        op = node.op
        left = self._eval(node.left)
        right = self._eval(node.right)

        if op in {"+", "-", "*", "/", "^"}:
            lv = _to_number(left, func=f"binary {op!r}", arg_index=0)
            rv = _to_number(right, func=f"binary {op!r}", arg_index=1)
            if op == "+":
                return lv + rv
            if op == "-":
                return lv - rv
            if op == "*":
                return lv * rv
            if op == "/":
                if rv == 0:
                    raise FormulaEvaluationError("division by zero")
                return lv / rv
            if op == "^":
                return lv ** rv

        if op == "&":
            return _to_string(left) + _to_string(right)

        if op in {"=", "<>", "<", "<=", ">", ">="}:
            return self._compare(op, left, right)

        raise FormulaEvaluationError(f"unknown binary operator {op!r}")

    def _compare(
        self, op: str, left: FormulaValue, right: FormulaValue
    ) -> bool:
        # Visio comparisons coerce cross-type: numeric vs numeric works
        # directly; anything with a string compares as strings; booleans
        # are treated as 0/1 numerics.
        if isinstance(left, str) or isinstance(right, str):
            l: Union[str, float] = _to_string(left)
            r: Union[str, float] = _to_string(right)
        else:
            l = _to_number(left, func=f"compare {op!r}", arg_index=0)
            r = _to_number(right, func=f"compare {op!r}", arg_index=1)
        if op == "=":
            return l == r
        if op == "<>":
            return l != r
        if op == "<":
            return l < r
        if op == "<=":
            return l <= r
        if op == ">":
            return l > r
        if op == ">=":
            return l >= r
        raise FormulaEvaluationError(f"unknown comparison operator {op!r}")

    def _eval_function(self, node: FunctionCall) -> FormulaValue:
        fn = BUILTINS.get(node.name)
        if fn is None:
            raise FormulaEvaluationError(
                f"unknown function {node.name!r}"
            )
        evaluated_args = tuple(self._eval(arg) for arg in node.args)
        return fn(*evaluated_args)


def evaluate(
    source_or_ast: Union[str, Node],
    context: Optional[ShapeSheetContext] = None,
) -> FormulaValue:
    """Evaluate a formula string or AST against ``context``.

    String input is parsed first. Callers that evaluate the same formula
    many times should parse once and pass the AST directly.
    """
    ast = parse(source_or_ast) if isinstance(source_or_ast, str) else source_or_ast
    return Evaluator(context).eval_ast(ast)
