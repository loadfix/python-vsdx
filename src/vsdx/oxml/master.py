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
"""``<Master>``, ``<MasterContents>``, ``<Icon>``.

Visio splits master data across two files (paralleling the page
model):

- ``/visio/masters/masters.xml`` — master index. One ``<Master>`` per
  master, with identifying attributes, the small icon bitmap
  (``<Icon>``), a ``<PageSheet>`` carrying the master's default
  ShapeSheet cells, and a ``<Rel r:id=…>`` pointing at the master
  part.
- ``/visio/masters/master%d.xml`` — master part. Root is
  ``<MasterContents>`` which holds a single ``<Shapes>`` (the shape
  tree that users drop-copies from when they instantiate the
  master).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from ooxml_xmlchemy import (
    BaseOxmlElement,
    OptionalAttribute,
    RequiredAttribute,
    XsdString,
    XsdUnsignedInt,
    ZeroOrOne,
)

__all__ = [
    "CT_Icon",
    "CT_Master",
    "CT_MasterContents",
]


class CT_Icon(BaseOxmlElement):
    """``<Icon>`` — base64-encoded master-icon bitmap.

    Visio's stencil palette shows this icon next to the master name.
    The oxml layer keeps the payload as raw text; decoding is the
    proxy layer's concern (and of no 0.1.0 public interest — icons
    ride round-trip only).

    .. versionadded:: 0.1.0
    """


class CT_Master(BaseOxmlElement):
    """Master-index entry in ``/visio/masters/masters.xml``.

    Identifying attributes:

    - ``@ID`` — master ID in the document (used by
      ``Shape/@Master``).
    - ``@NameU`` — universal master name (locale-invariant).
    - ``@Name`` — localised master name.
    - ``@BaseID`` — curly-braced GUID identifying the master's
      lineage; preserved across Save-As.
    - ``@UniqueID`` — curly-braced GUID fresh per save.
    - ``@MasterType`` — ``0`` for normal, ``1`` for icon-only, ``2``
      for "shape master" etc (per MS Learn ``MasterType_Type``).
    - ``@Hidden`` — ``0`` / ``1``.
    - ``@MatchByName`` — ``0`` / ``1``.
    - ``@IconSize`` — one of the Visio icon-size enumeration values.
    - ``@PatternFlags`` — bit flags for stencil pattern behaviour.
    - ``@Prompt`` — help text shown in the stencil palette.
    - ``@AlignName`` — icon label alignment.

    .. versionadded:: 0.1.0
    """

    id_ = RequiredAttribute("ID", XsdUnsignedInt)
    name = OptionalAttribute("Name", XsdString)
    name_u = OptionalAttribute("NameU", XsdString)
    base_id = OptionalAttribute("BaseID", XsdString)
    unique_id = OptionalAttribute("UniqueID", XsdString)
    # ``@Master`` on a ``<Master>`` index entry identifies a *parent*
    # master in the master-chain inheritance model. The proxy layer's
    # :meth:`~vsdx.shapes.base.Shape.master_chain` walks this pointer
    # transitively. Typed as ``XsdString`` rather than ``XsdUnsignedInt``
    # because authoring in this library uses NameU strings for master
    # references (see :class:`~vsdx.oxml.shape.CT_Shape` comment).
    master = OptionalAttribute("Master", XsdString)
    master_type = OptionalAttribute("MasterType", XsdUnsignedInt)
    hidden = OptionalAttribute("Hidden", XsdString)
    match_by_name = OptionalAttribute("MatchByName", XsdString)
    icon_size = OptionalAttribute("IconSize", XsdString)
    pattern_flags = OptionalAttribute("PatternFlags", XsdUnsignedInt)
    prompt = OptionalAttribute("Prompt", XsdString)
    align_name = OptionalAttribute("AlignName", XsdString)
    icon_update = OptionalAttribute("IconUpdate", XsdString)

    icon = ZeroOrOne("vsdx:Icon")
    # The master carries its own PageSheet holding default Shape cells
    # inherited by instance shapes.
    pageSheet = ZeroOrOne("vsdx:PageSheet")
    rel = ZeroOrOne("vsdx:Rel")


class CT_MasterContents(BaseOxmlElement):
    """Root of ``/visio/masters/master%d.xml``.

    Contains the master's ``<Shapes>``. Same shape shape as
    ``<PageContents>`` but without ``<Connects>`` (masters don't
    include connectors — connectors are page-scoped instances).

    .. versionadded:: 0.1.0
    """

    shapes = ZeroOrOne("vsdx:Shapes")

    @property
    def shapes_element(self):
        """Return the ``<Shapes>`` child, creating one if absent.

        Proxy-layer convenience — see
        :attr:`vsdx.oxml.page.CT_PageContents.shapes_element` for the
        full rationale (same semantics here on MasterContents).

        .. versionadded:: 0.1.0
        """
        return self.get_or_add_shapes()
