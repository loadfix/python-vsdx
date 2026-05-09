"""Tests for :mod:`vsdx.templates` — the bundled assets loader.

``default.vsdx`` now lands in ``src/vsdx/templates/`` as a library
asset. Master fragments (``fragments/*.xml``) don't land until the
per-master source fixtures (``rectangle-master.office.vsdx`` etc.)
are harvested into XML fragments at library-build time — tests here
pin the contract for both the landed-asset and the pending-asset
states.
"""

from __future__ import annotations

import zipfile

import pytest

from vsdx.templates import (
    TemplateNotAvailable,
    available_masters,
    default_template_path,
    master_fragment_path,
)


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
    def it_raises_template_not_available_until_fragment_lands(self, master):
        with pytest.raises(TemplateNotAvailable):
            master_fragment_path(master)

    def it_raises_key_error_on_unknown_master(self):
        with pytest.raises(KeyError):
            master_fragment_path("Pentagon")


class DescribeAvailableMasters:
    def it_yields_nothing_when_no_fragments_are_installed(self):
        assert list(available_masters()) == []
