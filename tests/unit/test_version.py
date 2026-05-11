"""Version / public-module smoke tests."""

from __future__ import annotations

import vsdx


class DescribeVersion:
    def it_exposes_a_calver_version_string(self) -> None:
        assert isinstance(vsdx.__version__, str)
        assert vsdx.__version__.startswith("0.")

    def it_reports_the_0_2_1_dev_version(self) -> None:
        # Patch-bump from 0.2.0.dev0 following the wave-12 security
        # fixes (formula depth cap, input-size cap, redacted
        # connection string helper).
        assert vsdx.__version__ == "0.2.1.dev0"


class DescribePublicConstants:
    def it_exposes_the_visio_core_namespace(self) -> None:
        assert vsdx.NS_VSDX_CORE == (
            "http://schemas.microsoft.com/office/visio/2011/1/core"
        )

    def it_exposes_the_opc_relationships_namespace(self) -> None:
        assert vsdx.NS_R.endswith("/officeDocument/2006/relationships")

    def it_exposes_the_main_vsdx_content_types(self) -> None:
        assert "drawing.main" in vsdx.CT_VSDX_DRAWING_MAIN
        assert "page" in vsdx.CT_VSDX_PAGE
        assert "master" in vsdx.CT_VSDX_MASTER
        assert "windows" in vsdx.CT_VSDX_WINDOWS

    def it_exposes_the_visio_relationship_types(self) -> None:
        assert "visio/2010/relationships/document" in vsdx.RT_VISIO_DOCUMENT
        assert "visio/2010/relationships/pages" in vsdx.RT_VISIO_PAGES
        assert "visio/2010/relationships/master" in vsdx.RT_VISIO_MASTER
