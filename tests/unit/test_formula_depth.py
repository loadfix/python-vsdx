"""Depth-cap canaries for the ShapeSheet formula parser and evaluator.

Crafted Visio ``@F`` strings can chain unary ``-`` or right-associative
``^`` arbitrarily; without an explicit depth cap, the parser's recursive
descent trips CPython's ~1000-frame limit and raises
:class:`RecursionError`, poisoning the surrounding thread and leaking no
structured error to the caller. The fix adds ``max_depth`` (default 256)
to both the parser and evaluator; this file asserts the guard fires
before CPython's limit does, on both attack shapes.

These canaries stay narrow on purpose — they assert the DoS guard fires,
not any particular error message. The wider parser/evaluator test suites
under ``tests/test_formula_*.py`` cover happy-path grammar.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import pytest

from vsdx.formula import FormulaDepthError, evaluate, parse


class DescribeFormulaDepthGuard:
    """The parser / evaluator raise :class:`FormulaDepthError` on DoS inputs."""

    def it_rejects_a_10000_deep_unary_chain(self):
        # `------...1` — ten thousand unary minuses followed by a
        # literal. Without the cap this parses into 10 000 nested
        # UnaryOp nodes and raises RecursionError.
        source = ("-" * 10000) + "1"
        with pytest.raises(FormulaDepthError):
            parse(source)

    def it_rejects_a_10000_deep_paren_unary_chain(self):
        # Alternating `-(` wrapper that also exercises the paren→expr
        # recursion path — each pair adds ``_parse_expr`` +
        # ``_parse_pow`` + ``_parse_unary`` frames.
        source = "-(" * 5000 + "1" + ")" * 5000
        with pytest.raises(FormulaDepthError):
            parse(source)

    def it_rejects_a_deep_power_chain(self):
        # `2^2^2^...^2` — right-associative `^` recurses through
        # `_parse_pow` the same way unary does through `_parse_unary`.
        source = "^".join(["2"] * 1000)
        with pytest.raises(FormulaDepthError):
            parse(source)

    def it_accepts_modest_depth_under_the_cap(self):
        # Sanity — a 10-deep chain is well under the 256 default and
        # must still parse+evaluate cleanly.
        source = ("-" * 10) + "1"
        assert evaluate(source) == 1.0  # even count → positive

    def it_honors_a_custom_max_depth_kwarg_on_parse(self):
        source = ("-" * 10) + "1"
        with pytest.raises(FormulaDepthError):
            parse(source, max_depth=4)

    def it_honors_a_custom_max_depth_kwarg_on_evaluate(self):
        source = ("-" * 10) + "1"
        with pytest.raises(FormulaDepthError):
            evaluate(source, max_depth=4)

    def it_does_not_leak_a_recursion_error(self):
        # Stricter contract: the public error must be FormulaDepthError
        # — never RecursionError, which carries no ``source``/``position``
        # info and trips ``except Exception`` handlers differently.
        source = ("-" * 20000) + "1"
        try:
            parse(source)
        except FormulaDepthError:
            pass
        except RecursionError:  # pragma: no cover — canary
            pytest.fail("parser leaked RecursionError past the depth cap")
