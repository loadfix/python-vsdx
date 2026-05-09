"""Behavioural tests for :class:`Master` / :class:`Masters`."""

from __future__ import annotations

import pytest

from vsdx import Visio
from vsdx.master import BUILT_IN_MASTER_NAMES, Master


class DescribeMasters:
    def it_starts_empty(self):
        assert len(Visio().masters) == 0

    def it_can_add_a_master(self):
        doc = Visio()
        m = doc.masters.add_master("MyBox")
        assert isinstance(m, Master)
        assert m.name_u == "MyBox"
        assert len(doc.masters) == 1

    def it_looks_up_masters_by_name_u(self):
        doc = Visio()
        m = doc.masters.add_master("Star")
        assert doc.masters["Star"] is m

    def its_contains_checks_name_u(self):
        doc = Visio()
        doc.masters.add_master("Star")
        assert "Star" in doc.masters
        assert "NotAMaster" not in doc.masters

    def it_supports_int_indexing(self):
        doc = Visio()
        m0 = doc.masters.add_master("A")
        m1 = doc.masters.add_master("B")
        assert doc.masters[0] is m0
        assert doc.masters[1] is m1

    def it_raises_KeyError_on_missing_name_u(self):
        with pytest.raises(KeyError):
            _ = Visio().masters["Nope"]

    def ensure_registers_on_first_use(self):
        doc = Visio()
        m = doc.masters.ensure("Process")
        assert m.name_u == "Process"
        # second call returns the same master
        assert doc.masters.ensure("Process") is m
        assert len(doc.masters) == 1


class DescribeBuiltInMasterNames:
    def it_lists_the_0_1_0_catalog(self):
        assert "Rectangle" in BUILT_IN_MASTER_NAMES
        assert "Ellipse" in BUILT_IN_MASTER_NAMES
        assert "Triangle" in BUILT_IN_MASTER_NAMES
        assert "Dynamic connector" in BUILT_IN_MASTER_NAMES
