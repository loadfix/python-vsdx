"""Unit tests for `vsdx.parts.master` module."""

from __future__ import annotations

from ooxml_opc import OpcPackage

from vsdx.constants import CT_VSDX_MASTER, CT_VSDX_MASTERS, NS_VSDX_CORE
from vsdx.parts.master import MasterPart, MastersPart


class DescribeMastersPart:
    def it_can_construct_a_default_masters_index_part(self) -> None:
        masters = MastersPart.new(None)  # type: ignore[arg-type]

        assert isinstance(masters, MastersPart)
        assert masters.content_type == CT_VSDX_MASTERS
        assert masters.partname == "/visio/masters/masters.xml"
        assert masters.element.tag == f"{{{NS_VSDX_CORE}}}Masters"


class DescribeMasterPart:
    def it_can_construct_a_default_master_part(self) -> None:
        package = OpcPackage()

        master = MasterPart.new(package)

        assert isinstance(master, MasterPart)
        assert master.content_type == CT_VSDX_MASTER
        assert master.partname == "/visio/masters/master1.xml"
        assert master.element.tag == f"{{{NS_VSDX_CORE}}}MasterContents"

    def it_mints_sequential_partnames_within_a_package(self) -> None:
        package = OpcPackage()

        first = MasterPart.new(package)
        package.relate_to(first, "masterRel")
        second = MasterPart.new(package)

        assert first.partname == "/visio/masters/master1.xml"
        assert second.partname == "/visio/masters/master2.xml"
