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
"""``<Shapes>`` — container of ``<Shape>`` elements (recursive).

Appears at three levels in a Visio package:

1. Inside ``<PageContents>`` (the page part) — page-level shape
   collection.
2. Inside ``<MasterContents>`` (a master part) — master's shape
   collection.
3. Inside ``<Shape Type="Group">`` (a group shape) — nested child
   shapes.

Because it's recursive, a single :class:`CT_Shapes` class covers all
three locations. Parents discriminate by context (PageContents'
shapes vs MasterContents' shapes vs group-shape's nested shapes) at
the proxy layer.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    ZeroOrMore,
)

__all__ = ["CT_Shapes"]


class CT_Shapes(BaseOxmlElement):
    """Container for ``<Shape>`` children; recursive.

    .. versionadded:: 0.1.0
    """

    # Auto-generates ``shape_lst`` getter on this class.
    shape = ZeroOrMore("vsdx:Shape")
