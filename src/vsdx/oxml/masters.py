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
"""``<Masters>`` — root of ``/visio/masters/masters.xml``.

Carries a single attribute (``@MastersRoot``, rarely used) and a flat
list of ``<Master>`` children. A Visio drawing with no masters omits
this part entirely.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    XsdString,
    ZeroOrMore,
)

__all__ = ["CT_Masters"]


class CT_Masters(BaseOxmlElement):
    """The master index — ``/visio/masters/masters.xml`` root.

    .. versionadded:: 0.1.0
    """

    masters_root = OptionalAttribute("MastersRoot", XsdString)

    # Auto-generates ``master_lst`` getter on this class.
    master = ZeroOrMore("vsdx:Master")
