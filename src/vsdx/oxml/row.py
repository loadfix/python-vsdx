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
"""``<Row>`` — grouping of cells inside a ``<Section>``.

Three flavours (per MS Learn's ``Row_Type`` page):

- **Indexed** — ``@IX`` is present; rows are ordered 0..N. Used in
  most sections (Scratch, Controls, Property, Action, etc.).
- **Named** — ``@N`` carries the row name (used in User-defined cells
  and a few others).
- **Geometry-typed** — ``@T`` carries a geometry operator
  (``MoveTo`` / ``LineTo`` / ``ArcTo`` / …) and ``@IX`` is still
  present to order rows within the Geometry section.

All three flavours are the same XML element — discrimination is
value-level on the attributes, not class-level. See
``audits/2026-05-09-vsdx-scoping.md`` §2.7.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    XsdString,
    XsdUnsignedInt,
    ZeroOrMore,
)

__all__ = ["CT_Row"]


class CT_Row(BaseOxmlElement):
    """The universal Visio ``<Row>`` element.

    Contains zero or more ``<Cell>`` children; row identity / order is
    carried by a combination of ``@IX``, ``@N``, and ``@T``.

    .. versionadded:: 0.1.0
    """

    # ``@IX`` — ordinal index within the parent section (indexed rows).
    ix = OptionalAttribute("IX", XsdUnsignedInt)
    # ``@N`` — row name (named rows, e.g. User.MyName).
    name_ = OptionalAttribute("N", XsdString)
    # ``@T`` — geometry row type (``LineTo`` / ``MoveTo`` / …).
    t = OptionalAttribute("T", XsdString)
    # ``@Del`` — marker for "this row deletes an inherited master
    # row" (Visio's inheritance-delete sentinel). Rare; present only
    # on page shapes that need to null-out a master-inherited row.
    del_ = OptionalAttribute("Del", XsdString)

    # Descriptor generates ``cell_lst`` getter on the class.
    cell = ZeroOrMore("vsdx:Cell")
