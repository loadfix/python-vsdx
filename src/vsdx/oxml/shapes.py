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

    def add_shape(self, master_name_u=None):
        """Append a new ``<Shape>`` child and return it.

        Overrides the zero-arg ``add_shape`` xmlchemy autogenerates from
        the ``ZeroOrMore("vsdx:Shape")`` descriptor with a proxy-friendly
        keyword variant. When *master_name_u* is supplied, the new
        ``<Shape>`` carries ``@Master=name_u`` (the convention the proxy
        uses to look up the registered master at save time).

        .. versionadded:: 0.1.0
        """
        shape_el = self._add_shape()
        if master_name_u is not None:
            shape_el.set("Master", str(master_name_u))
        return shape_el
