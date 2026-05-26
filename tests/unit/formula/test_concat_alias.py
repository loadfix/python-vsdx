"""Tests for the CONCAT alias of CONCATENATE.

CONCAT is the Visio 2013+ spelling of CONCATENATE. Both must dispatch
to the same builtin (no inter-arg separator) so authoring code can
ship either spelling without a rewrite pass.
"""

from __future__ import annotations

from vsdx.formula import BUILTINS, evaluate


class DescribeConcatAlias:
    def it_registers_CONCAT_and_CONCATENATE_as_separate_entries(self):
        assert "CONCAT" in BUILTINS
        assert "CONCATENATE" in BUILTINS

    def it_dispatches_both_names_to_the_same_callable(self):
        assert BUILTINS["CONCAT"].func is BUILTINS["CONCATENATE"].func

    def it_evaluates_CONCAT_with_no_separator(self):
        assert evaluate('CONCAT("a", "b", "c")') == "abc"

    def it_matches_CONCATENATE_for_identical_inputs(self):
        a = evaluate('CONCAT("foo", "_", "bar")')
        b = evaluate('CONCATENATE("foo", "_", "bar")')
        assert a == b == "foo_bar"

    def it_coerces_numeric_args_to_strings(self):
        # Visio's CONCAT/CONCATENATE stringify numeric args using the
        # integer-without-trailing-zero convention.
        assert evaluate('CONCAT("Width=", 10)') == "Width=10"
