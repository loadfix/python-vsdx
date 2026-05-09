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
"""``<Cell>`` — the universal name/value element.

Visio's ShapeSheet collapses into a single generic element type whose
semantics vary by the ``@N`` (name) attribute. All ~150 named-cell
pages in MS Learn's Elements reference (PinX, PinY, Width, Height,
LineWeight, FillForegnd, LineColor, BeginX, EndX, …) are instances of
this one element with different ``@N`` values. See
``audits/2026-05-09-vsdx-scoping.md`` §2.7 for the full analysis.

Attributes (per MS Learn ``Cell_Type``):

- ``@N`` — cell name (required for singleton cells, optional for
  tabular cells inside a ``<Row>``).
- ``@V`` — value. Opaque string at the oxml layer; may be a decimal,
  integer, themed-color sentinel (``"Themed"``), or empty.
- ``@F`` — formula. Opaque string (:class:`ST_FormulaString`). Not
  evaluated in 0.1.0.
- ``@U`` — display-unit hint (``IN`` / ``MM`` / ``CM`` / …).
- ``@E`` — error value (rare; present when Visio couldn't evaluate
  ``@F``).

The proxy layer (track 3) does named-cell dispatch; the oxml layer
keeps ``CT_Cell`` a single generic class.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    XsdString,
)

__all__ = ["CT_Cell"]


class CT_Cell(BaseOxmlElement):
    """The universal Visio ``<Cell>`` element.

    Covers every named cell in Visio's ShapeSheet vocabulary via the
    ``@N`` attribute (``PinX``, ``PinY``, ``LineWeight``, …).

    .. versionadded:: 0.1.0
    """

    # ``@N`` is optional at XSD level because tabular cells inside a
    # ``<Row>`` may omit it when their position inside the row implies
    # the cell name (Visio emits it anyway in practice, but the XSD
    # marks it optional to allow compact encodings).
    name_ = OptionalAttribute("N", XsdString)
    # ``@V`` holds the current (possibly-stale if ``@F`` is present)
    # value. Kept opaque at the oxml layer — typed views live in the
    # proxy.
    v = OptionalAttribute("V", XsdString)
    # ``@F`` is the ShapeSheet formula. Stored as an opaque string;
    # the proxy layer uses a curated allow-list + passthrough
    # strategy.
    f = OptionalAttribute("F", XsdString)
    # ``@U`` is the display-unit hint.
    u = OptionalAttribute("U", XsdString)
    # ``@E`` is the error value (present only when Visio detected a
    # formula-evaluation error).
    e = OptionalAttribute("E", XsdString)
