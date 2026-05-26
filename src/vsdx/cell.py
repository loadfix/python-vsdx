# Copyright 2026 loadfix contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Proxy wrapper for the universal Visio ``<Cell>`` element.

Visio collapses the ShapeSheet into a single generic ``<Cell>`` element
distinguished by its ``@N`` (name) attribute. Every named property
(``PinX``, ``Width``, ``LineWeight``, ``FillForegnd``, ...) and every
section-row cell (``Geometry1.X1``, ``User.Scale``, ``Prop.Cost``) is an
instance of :class:`~vsdx.oxml.cell.CT_Cell` with different ``@N``
values.

The :class:`Cell` proxy adds:

- :attr:`~Cell.formula` / :attr:`~Cell.value` accessors over the raw
  ``@F`` / ``@V`` attributes.
- :meth:`~Cell.evaluate` — resolve ``@F`` against a
  :class:`~vsdx.formula.ShapeSheetContext`, returning the computed
  Python value without mutating the underlying tree.
- :meth:`~Cell.recompute` — resolve ``@F`` *and* write the stringified
  result back to ``@V`` so the package round-trips with up-to-date
  cached values.

Section-row cells are wrapped by the same proxy class — the ``parent``
slot stores the owning :class:`~vsdx.oxml.row.CT_Row` (for tabular
cells) or :class:`~vsdx.oxml.shape.CT_Shape` (for singletons), letting
:meth:`evaluate` build the section-row qualifier when no explicit
context is supplied.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from vsdx.formula.context import ShapeSheetContext
    from vsdx.formula.nodes import FormulaValue
    from vsdx.oxml._stubs import CT_Cell  # noqa: F401  # TODO(vsdx/track-1)


__all__ = ["Cell"]


def _stringify_value(value: object) -> str:
    """Format a Python value the way Visio writes it back into ``@V``.

    Mirrors :func:`vsdx.shapes.base._fmt_num` for floats and uses Visio's
    ``"TRUE"``/``"FALSE"`` spelling for booleans. Tuples (the result of
    :func:`vsdx.formula.builtins._fn_pnt`) are flattened into the
    ``"PNT(x, y)"`` round-trip spelling Visio uses for point literals.
    """

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e16:
            return str(int(value))
        return ("%f" % value).rstrip("0").rstrip(".")
    if isinstance(value, tuple):
        # PNT-style point literal — keep the round-trip form. We render
        # both components through the same numeric formatter so an
        # integer-valued component reads as ``0`` not ``0.000000``.
        return "PNT(" + ", ".join(_stringify_value(v) for v in value) + ")"
    if value is None:
        return ""
    return str(value)


class Cell:
    """Proxy over a Visio ``<Cell>`` element.

    Wraps the underlying :class:`~vsdx.oxml.cell.CT_Cell` so callers can
    work with typed accessors + a formula-evaluation hook without
    touching the lxml tree directly.

    .. versionadded:: 0.3.0
    """

    def __init__(self, cell_element: "CT_Cell") -> None:
        self._element = cell_element

    # -- identity -------------------------------------------------------

    @property
    def name(self) -> Optional[str]:
        """The cell's ``@N`` (name) attribute, or ``None`` if absent.

        .. versionadded:: 0.3.0
        """

        return self._element.get("N")

    # -- raw attributes -------------------------------------------------

    @property
    def value(self) -> Optional[str]:
        """The cell's ``@V`` (value) string, or ``None`` if unset.

        Returns the raw string Visio emits — callers that need a typed
        result should use :meth:`evaluate` instead.

        .. versionadded:: 0.3.0
        """

        return self._element.get("V")

    @value.setter
    def value(self, new: Optional[str]) -> None:
        if new is None:
            self._element.attrib.pop("V", None)
        else:
            self._element.set("V", new)

    @property
    def formula(self) -> Optional[str]:
        """The cell's ``@F`` (formula) string, or ``None`` if absent.

        .. versionadded:: 0.3.0
        """

        return self._element.get("F")

    @formula.setter
    def formula(self, new: Optional[str]) -> None:
        if new is None:
            self._element.attrib.pop("F", None)
        else:
            self._element.set("F", new)

    @property
    def unit(self) -> Optional[str]:
        """The cell's ``@U`` (display-unit hint), or ``None``.

        .. versionadded:: 0.3.0
        """

        return self._element.get("U")

    # -- evaluation -----------------------------------------------------

    def evaluate(
        self, context: Optional["ShapeSheetContext"] = None
    ) -> "Optional[FormulaValue]":
        """Resolve this cell's formula against *context*.

        Returns the stringified ``@V`` parsed as a number / bool when
        ``@F`` is absent; otherwise parses ``@F`` and evaluates it.
        ``context`` is optional only when the formula is a literal
        (a constant, no cell references) — pass a
        :class:`~vsdx.formula.ShapeSheetContext` (typically built via
        :func:`vsdx.formula.Context.for_shape`) when the formula
        references other cells.

        Raises :class:`~vsdx.formula.FormulaParseError` on malformed
        formulas, :class:`~vsdx.formula.FormulaEvaluationError` on
        unresolved references / unknown functions.

        .. versionadded:: 0.3.0
        """

        from vsdx.formula.evaluator import evaluate as _evaluate

        formula = self.formula
        if formula is None or formula == "":
            return _coerce_v(self.value)
        return _evaluate(formula, context)

    def recompute(self, context: Optional["ShapeSheetContext"] = None) -> bool:
        """Re-evaluate ``@F`` and write the result to ``@V``.

        Returns ``True`` when ``@V`` actually changed; ``False`` when
        the cell has no formula or the recomputed value matches the
        existing ``@V`` (so callers can build a changed-set without
        double-bookkeeping).

        .. versionadded:: 0.3.0
        """

        formula = self.formula
        if formula is None or formula == "":
            return False
        new_value = self.evaluate(context)
        new_text = _stringify_value(new_value)
        if self._element.get("V") == new_text:
            return False
        self._element.set("V", new_text)
        return True


def _coerce_v(raw: Optional[str]) -> "Optional[FormulaValue]":
    """Best-effort coercion of a raw ``@V`` string to a Python value.

    Visio writes ``@V`` as a string at the XML layer regardless of the
    semantic type. We try numeric first (float / int round-trip),
    then the boolean sentinels Visio emits (``TRUE`` / ``FALSE``),
    then fall back to the raw string.
    """

    if raw is None or raw == "":
        return None
    upper = raw.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    try:
        return float(raw)
    except ValueError:
        return raw
