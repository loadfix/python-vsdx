# pyright: reportImportCycles=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUntypedBaseClass=false
# pyright: reportMissingTypeStubs=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportMissingImports=false
# pyright: reportPrivateUsage=false
"""``<Pages>`` — root of ``/visio/pages/pages.xml``.

Simple container; one ``<Page>`` child per page in the drawing.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    ZeroOrMore,
)

__all__ = ["CT_Pages"]


class CT_Pages(BaseOxmlElement):
    """The page index — ``/visio/pages/pages.xml`` root.

    .. versionadded:: 0.1.0
    """

    # Auto-generates ``page_lst`` getter on this class.
    page = ZeroOrMore("vsdx:Page")
