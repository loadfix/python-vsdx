"""AST node types for ShapeSheet formula expressions.

The AST is intentionally small — Visio formulas are closer to Excel
expressions than to a general-purpose language. We have:

- literals: numbers (``2.5``, ``100%``), strings (``"hello"``), booleans
  (``TRUE``, ``FALSE``);
- cell references (``Width``, ``User.Scale``, ``Geometry1.X1``,
  ``Sheet.5!PinX`` — cross-shape);
- unary prefix operator: ``-`` (negation), ``+`` (identity);
- binary operators: ``+ - * / ^`` (arithmetic), ``= <> < <= > >=``
  (comparison), ``&`` (string concat — rare in Visio but supported);
- function calls: ``NAME(arg1, arg2, ...)``.

There is no assignment, no control flow, and no user-defined functions.
The ``IF(cond, a, b)`` idiom lives in the built-in function library rather
than as its own AST node, matching Excel / ShapeSheet conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

# A FormulaValue is one of the Python types a formula can return. Visio's
# native type system is: numeric, boolean, string. Everything else is
# expressed as a numeric with unit metadata we ignore for 0.1.0.
FormulaValue = Union[float, int, bool, str]


@dataclass(frozen=True)
class Node:
    """Base class for AST nodes.

    All nodes are immutable frozen dataclasses so evaluator / graph passes
    can safely cache them by identity.
    """

    __slots__ = ()


@dataclass(frozen=True)
class NumberLiteral(Node):
    """A numeric literal. ``100%`` is stored pre-scaled (``1.0``)."""

    value: float


@dataclass(frozen=True)
class StringLiteral(Node):
    """A string literal. Double-quoted in source; stored unquoted."""

    value: str


@dataclass(frozen=True)
class BoolLiteral(Node):
    """The ``TRUE`` / ``FALSE`` constants. Case-insensitive in source."""

    value: bool


@dataclass(frozen=True)
class CellRef(Node):
    """A reference to a ShapeSheet cell.

    Visio cell references have three optional axes:

    - *sheet* — the owning shape, either by numeric ID (``Sheet.5``) or by
      shape name (``TheShape``). ``None`` means "this shape".
    - *section* — the tabular section the cell lives in (``User``, ``Prop``,
      ``Scratch``, ``Geometry1``, ``Connections``, ``Actions``, ...) plus
      an optional row qualifier. ``None`` means the shape's singleton cells
      (``PinX``, ``Width``, ``LineWeight``, ...).
    - *row* — the row index or row name within a section. ``None`` means no
      row qualifier (valid for singleton cells; invalid for section cells).
    - *name* — the cell name (``X``, ``Y``, ``Value``, ``Prompt``, ...).

    We store the original source text so the serializer can emit it
    verbatim when round-tripping ``@F`` attributes.
    """

    name: str
    section: Optional[str] = None
    row: Optional[str] = None
    sheet: Optional[str] = None
    source: str = ""

    def qualified(self) -> str:
        """Return the canonical ``Sheet.N!Section.Row!Name`` form."""
        parts: list[str] = []
        if self.section is not None:
            if self.row is not None:
                parts.append(f"{self.section}.{self.row}")
            else:
                parts.append(self.section)
        parts.append(self.name)
        qualified = ".".join(parts)
        if self.sheet is not None:
            qualified = f"{self.sheet}!{qualified}"
        return qualified


@dataclass(frozen=True)
class UnaryOp(Node):
    """Prefix unary operator — ``-`` or ``+``."""

    op: str
    operand: Node


@dataclass(frozen=True)
class BinaryOp(Node):
    """Binary operator — arithmetic, comparison, or string concat."""

    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class FunctionCall(Node):
    """A named function call. Names are case-insensitive in Visio."""

    name: str
    args: tuple[Node, ...] = field(default_factory=tuple)
