"""Exceptions raised by the ShapeSheet formula parser and evaluator."""

from __future__ import annotations


class FormulaError(Exception):
    """Base class for all formula-related errors.

    Concrete subclasses carry richer positional information (the offset into
    the original formula string) so downstream code can highlight the
    offending span when the formula came from user input.
    """

    def __init__(self, message: str, *, source: str | None = None, position: int | None = None):
        super().__init__(message)
        self.message = message
        self.source = source
        self.position = position

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.source is not None and self.position is not None:
            return f"{self.message} (at position {self.position} in {self.source!r})"
        if self.source is not None:
            return f"{self.message} (in {self.source!r})"
        return self.message


class FormulaParseError(FormulaError):
    """Raised when the tokenizer or parser rejects the input string."""


class FormulaEvaluationError(FormulaError):
    """Raised when the evaluator fails at runtime.

    Covers: unknown function, wrong arity, unresolved cell reference, math
    errors (divide by zero, ``ATAN2(0, 0)`` in strict mode, ...).
    """


class FormulaTypeError(FormulaEvaluationError):
    """Raised when a built-in function gets an argument of the wrong kind."""


class FormulaCycleError(FormulaEvaluationError):
    """Raised by :class:`DependencyGraph` when a cell's dependencies form a cycle."""

    def __init__(self, message: str, *, cycle: list[str] | None = None):
        super().__init__(message)
        self.cycle = list(cycle) if cycle else []
