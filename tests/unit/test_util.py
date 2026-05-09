"""Unit tests for ``vsdx.util`` length classes."""

from __future__ import annotations

import math

import pytest

from vsdx.util import Cm, Emu, Inches, Length, Mm, Pt, lazyproperty


class DescribeInches:
    def it_carries_the_value_in_inches(self):
        v = Inches(2.5)
        assert float(v) == 2.5
        assert v.inches == 2.5

    def its_cm_accessor_converts_correctly(self):
        assert Inches(1).cm == pytest.approx(2.54)

    def its_mm_accessor_converts_correctly(self):
        assert Inches(1).mm == pytest.approx(25.4)

    def its_pt_accessor_converts_correctly(self):
        assert Inches(1).pt == pytest.approx(72.0)

    def its_emu_accessor_converts_correctly(self):
        assert Inches(1).emu == 914400


class DescribeCm:
    def it_stores_in_inches_internally(self):
        v = Cm(2.54)
        assert v.inches == pytest.approx(1.0)


class DescribeMm:
    def it_stores_in_inches_internally(self):
        v = Mm(25.4)
        assert v.inches == pytest.approx(1.0)


class DescribePt:
    def it_stores_in_inches_internally(self):
        v = Pt(72.0)
        assert v.inches == pytest.approx(1.0)


class DescribeEmu:
    def it_accepts_emu_and_converts_to_inches(self):
        v = Emu(914400)
        assert v.inches == pytest.approx(1.0)


class DescribeLazyproperty:
    def it_caches_the_computed_value(self):
        call_count = [0]

        class C:
            @lazyproperty
            def v(self):
                call_count[0] += 1
                return object()

        obj = C()
        first = obj.v
        second = obj.v
        assert first is second
        assert call_count[0] == 1
