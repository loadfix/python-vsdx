"""Tests for :mod:`vsdx.templates` — the bundled assets loader.

Actual assets (``default.vsdx``, ``fragments/*.xml``) don't land until
the fixtures in ``/tmp/vsdx-fixture-requests.md`` are produced. These
tests pin the *interface* so consumers can write against it today.
"""

from __future__ import annotations

import pytest

from vsdx.templates import (
    TemplateNotAvailable,
    available_masters,
    default_template_path,
    master_fragment_path,
)


class DescribeDefaultTemplate:
    def it_raises_template_not_available_until_fixture_lands(self):
        with pytest.raises(TemplateNotAvailable) as excinfo:
            default_template_path()
        assert "/tmp/vsdx-fixture-requests.md" in str(excinfo.value)


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
