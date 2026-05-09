"""Tests for :mod:`vsdx.templates` — the bundled assets loader.

Both ``default.vsdx`` and the four built-in master fragments now land
in ``src/vsdx/templates/`` as library assets, extracted from the
per-master ``*-master.office.vsdx`` fixtures in the reference corpus.
Tests here pin the landed-asset contract.
"""

from __future__ import annotations

import zipfile

import pytest
from lxml import etree

from vsdx.templates import (
    TemplateNotAvailable,
    available_masters,
    default_template_path,
    master_fragment_path,
)

_VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"


class DescribeDefaultTemplate:
    def it_returns_a_path_to_the_bundled_default_vsdx(self):
        path = default_template_path()
        assert path.exists()
        assert path.name == "default.vsdx"

    def it_is_a_valid_zip_archive_with_visio_parts(self):
        path = default_template_path()
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        assert "[Content_Types].xml" in names
        assert any(n.startswith("visio/") for n in names)


class DescribeMasterFragments:
    @pytest.mark.parametrize(
        "master", ["Rectangle", "Ellipse", "Triangle", "Dynamic Connector"]
    )
    def it_returns_a_path_to_the_bundled_master_fragment(self, master):
        path = master_fragment_path(master)
        assert path.exists()
        assert path.name.endswith(".master.xml")

    @pytest.mark.parametrize(
        "master, expected_nameu",
        [
            ("Rectangle", "Rectangle"),
            ("Ellipse", "Ellipse"),
            ("Triangle", "Triangle"),
            ("Dynamic Connector", "Dynamic connector"),
        ],
    )
    def it_points_at_a_well_formed_master_element(self, master, expected_nameu):
        path = master_fragment_path(master)
        root = etree.parse(str(path)).getroot()
        assert root.tag == f"{{{_VISIO_NS}}}Master"
        assert root.get("NameU") == expected_nameu

    @pytest.mark.parametrize(
        "master", ["Rectangle", "Ellipse", "Triangle", "Dynamic Connector"]
    )
    def it_has_a_sibling_master_contents_fragment(self, master):
        master_path = master_fragment_path(master)
        contents_path = master_path.with_name(
            master_path.name.replace(".master.xml", ".masterContents.xml")
        )
        assert contents_path.exists()
        root = etree.parse(str(contents_path)).getroot()
        assert root.tag == f"{{{_VISIO_NS}}}MasterContents"

    def it_raises_key_error_on_unknown_master(self):
        with pytest.raises(KeyError):
            master_fragment_path("Pentagon")

    def it_raises_template_not_available_when_file_is_missing(
        self, monkeypatch, tmp_path
    ):
        from vsdx import templates as mod

        monkeypatch.setitem(mod._MASTER_FRAGMENTS, "Rectangle", "missing.master.xml")
        with pytest.raises(TemplateNotAvailable):
            master_fragment_path("Rectangle")


class DescribeAvailableMasters:
    def it_yields_every_bundled_master(self):
        assert sorted(available_masters()) == sorted(
            ["Rectangle", "Ellipse", "Triangle", "Dynamic Connector"]
        )
