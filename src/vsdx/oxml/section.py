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
"""``<Section>`` — collection of ``<Row>`` elements.

Section kinds (``@N``) include:

- ``Geometry`` — path geometry (rows are typed via ``Row/@T``).
- ``Character`` / ``Paragraph`` / ``Tabs`` — text formatting.
- ``Scratch`` — shape-local temporary cells.
- ``Connection`` / ``ConnectionABCD`` — connection points.
- ``Controls`` — control handles.
- ``Layer`` — layer assignment.
- ``User`` — user-defined cells.
- ``Property`` — shape data (custom properties).
- ``Actions`` — right-click menu actions.
- ``Hyperlink`` — hyperlinks.
- ``Field`` — text-field substitutions.
- ``Reviewer`` / ``Annotation`` — review markup.

A shape may carry multiple Geometry sections (``IX=0``, ``IX=1``, …)
for compound paths.

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

__all__ = ["CT_Section"]


class CT_Section(BaseOxmlElement):
    """The universal Visio ``<Section>`` element.

    Contains zero or more ``<Row>`` children plus occasional direct
    ``<Cell>`` children (rare — ``Layer`` sections can carry
    singleton cells for section-level properties).

    .. versionadded:: 0.1.0
    """

    # ``@N`` — section name (``Geometry`` / ``Character`` / …). Required
    # in real Visio output but the XSD marks it optional; match XSD.
    name_ = OptionalAttribute("N", XsdString)
    # ``@IX`` — section ordinal, used when multiple sections of the
    # same kind co-exist (compound Geometry, multiple User sections).
    ix = OptionalAttribute("IX", XsdUnsignedInt)
    # ``@Del`` — inheritance-delete marker; see CT_Row.del_ .
    del_ = OptionalAttribute("Del", XsdString)

    row = ZeroOrMore("vsdx:Row")
    # Direct Cell children (rare; mostly for Layer sections).
    cell = ZeroOrMore("vsdx:Cell")
