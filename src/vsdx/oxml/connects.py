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
"""``<Connects>``, ``<Connect>`` — connector glue.

Every Visio connector shape (by convention, a shape instanced from
the built-in Dynamic Connector master) records its endpoint glue as
two ``<Connect>`` entries inside ``<Connects>`` on the page's
``<PageContents>``:

.. code-block:: xml

    <Connects>
      <Connect FromSheet="5" FromCell="BeginX" FromPart="9"
               ToSheet="3" ToCell="PinX"/>
      <Connect FromSheet="5" FromCell="EndX"   FromPart="12"
               ToSheet="4" ToCell="PinX"/>
    </Connects>

- ``@FromSheet`` — ID of the connector shape.
- ``@FromCell`` — the endpoint cell on the connector
  (``BeginX`` / ``EndX``).
- ``@FromPart`` — integer hinting which anchor on the connector (9
  for begin, 12 for end; documented in ``VisFromParts_Type``).
- ``@ToSheet`` — ID of the glued-to shape.
- ``@ToCell`` — the anchor cell on the target
  (``PinX`` / ``Connections.X1`` / …).
- ``@ToPart`` — numeric part code on the target, optional.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    RequiredAttribute,
    XsdString,
    XsdUnsignedInt,
    ZeroOrMore,
)

__all__ = [
    "CT_Connect",
    "CT_Connects",
]


class CT_Connect(BaseOxmlElement):
    """One endpoint-glue record inside ``<Connects>``.

    .. versionadded:: 0.1.0
    """

    from_sheet = RequiredAttribute("FromSheet", XsdUnsignedInt)
    from_cell = RequiredAttribute("FromCell", XsdString)
    from_part = OptionalAttribute("FromPart", XsdUnsignedInt)
    to_sheet = RequiredAttribute("ToSheet", XsdUnsignedInt)
    to_cell = OptionalAttribute("ToCell", XsdString)
    to_part = OptionalAttribute("ToPart", XsdUnsignedInt)


class CT_Connects(BaseOxmlElement):
    """Container inside ``<PageContents>`` for all connector glue.

    .. versionadded:: 0.1.0
    """

    # Auto-generates ``connect_lst`` getter.
    connect = ZeroOrMore("vsdx:Connect")
