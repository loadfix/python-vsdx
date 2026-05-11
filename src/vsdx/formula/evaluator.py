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
from vsdx.formula.errors import FormulaDepthError, FormulaEvaluationError
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
from vsdx.formula.parser import DEFAULT_MAX_DEPTH, parse

# Functions that need non-standard (lazy / context-aware) evaluation and
# therefore cannot go through the default eager-eval BUILTINS dispatch.
# ``IF`` / ``AND`` / ``OR`` short-circuit on their condition; ``USE``
# tries to resolve a named cell against the current context before
# falling back to the builtin passthrough.
_SPECIAL_FORMS = {"IF", "AND", "OR", "USE"}


class Evaluator:
    """Evaluates a parsed AST against a :class:`ShapeSheetContext`.

    Callers that need to reuse the same context across many formulas
    should instantiate once and call :meth:`eval_ast` repeatedly. For
    one-shot use see the module-level :func:`evaluate` convenience.
    """

    def __init__(
        self,
        context: Optional[ShapeSheetContext] = None,
        *,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ):
        self._context = context
        self._max_depth = max_depth
        self._depth = 0

    @property
    def context(self) -> Optional[ShapeSheetContext]:
        return self._context

    def eval_ast(self, node: Node) -> FormulaValue:
        """Evaluate a parsed AST node to a concrete value."""
        return self._eval(node)

    def _eval(self, node: Node) -> FormulaValue:
        # Single shared recursion counter. Each ``_eval`` descent
        # increments; the guard fires when a crafted AST (deeply nested
        # unary, power chain, or function-call tree that somehow escaped
        # the parser cap) would overflow CPython's ~1000-frame limit.
        self._depth += 1
        if self._depth > self._max_depth:
            self._depth -= 1
            raise FormulaDepthError(
                f"formula AST evaluation exceeds max_depth={self._max_depth}"
            )
        try:
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
        finally:
            self._depth -= 1

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
        upper = node.name.upper()
        if upper in _SPECIAL_FORMS:
            return self._eval_special_form(upper, node)
        fn = BUILTINS.get(node.name)
        if fn is None:
            raise FormulaEvaluationError(
                f"unknown function {node.name!r}"
            )
        evaluated_args = tuple(self._eval(arg) for arg in node.args)
        return fn(*evaluated_args)

    def _eval_special_form(self, name: str, node: FunctionCall) -> FormulaValue:
        """Lazy / context-aware evaluation for :data:`_SPECIAL_FORMS`."""
        if name == "IF":
            # Short-circuit: evaluate only the selected branch. Matches
            # Visio / Excel semantics where the unused branch is never
            # resolved (so IF(0, 1/0, 42) == 42 without division error).
            if not 2 <= len(node.args) <= 3:
                raise FormulaEvaluationError(
                    f"IF expects 2 or 3 argument(s), got {len(node.args)}"
                )
            cond = self._eval(node.args[0])
            if _to_bool(cond):
                return self._eval(node.args[1])
            if len(node.args) == 3:
                return self._eval(node.args[2])
            return False

        if name == "AND":
            if not node.args:
                raise FormulaEvaluationError("AND requires at least one argument")
            for arg in node.args:
                if not _to_bool(self._eval(arg)):
                    return False
            return True

        if name == "OR":
            if not node.args:
                raise FormulaEvaluationError("OR requires at least one argument")
            for arg in node.args:
                if _to_bool(self._eval(arg)):
                    return True
            return False

        if name == "USE":
            # Try to resolve the argument as a named cell against the
            # current context; fall through to the passthrough builtin
            # when the name is unknown or no context is attached. This
            # matches Visio's USE(masterName) which inherits a master's
            # cell value when one is registered in the PageSheet.
            if len(node.args) != 1:
                raise FormulaEvaluationError(
                    f"USE expects exactly 1 argument, got {len(node.args)}"
                )
            target = self._eval(node.args[0])
            if isinstance(target, str) and self._context is not None:
                probe = CellRef(name=target)
                resolved = self._context.resolve(probe)
                if resolved is not None:
                    return resolved
            return target

        raise FormulaEvaluationError(  # pragma: no cover — guarded by caller
            f"unimplemented special form {name!r}"
        )


def evaluate(
    source_or_ast: Union[str, Node],
    context: Optional[ShapeSheetContext] = None,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> FormulaValue:
    """Evaluate a formula string or AST against ``context``.

    String input is parsed first. Callers that evaluate the same formula
    many times should parse once and pass the AST directly.

    ``max_depth`` (default 256) caps both the parser's recursive descent
    and the evaluator's AST walk; crafted inputs that exceed the cap
    raise :class:`~vsdx.formula.errors.FormulaDepthError` rather than
    the thread-poisoning :class:`RecursionError`.
    """
    ast = (
        parse(source_or_ast, max_depth=max_depth)
        if isinstance(source_or_ast, str)
        else source_or_ast
    )
    return Evaluator(context, max_depth=max_depth).eval_ast(ast)
