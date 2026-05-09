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
"""``<Page>``, ``<PageSheet>``, ``<PageContents>``, ``<Rel>``.

Visio splits page data across two files:

- ``/visio/pages/pages.xml`` — the page index. Contains one
  ``<Page>`` per page, with the page's ``<PageSheet>`` (page-level
  ShapeSheet cells like ``PageWidth`` / ``PageHeight`` /
  ``PageScale``) and a ``<Rel>`` pointing at the corresponding page
  part via ``r:id``.
- ``/visio/pages/pageN.xml`` — the page part. Its root is
  ``<PageContents>``, which holds ``<Shapes>`` (the drawing
  content) and ``<Connects>`` (connector glue).

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
    ZeroOrOne,
)

__all__ = [
    "CT_Page",
    "CT_PageContents",
    "CT_PageSheet",
    "CT_Rel",
]


class CT_PageSheet(BaseOxmlElement):
    """Page-level ShapeSheet (inside ``<Page>``).

    Holds singleton cells (``PageWidth`` / ``PageHeight`` /
    ``PageScale`` / ``DrawingScale`` / ``DrawingSizeType`` / …) and
    occasional sections (``Scratch``, ``User``, ``Property``,
    ``Hyperlink``, ``Actions``) that apply at page scope.

    Same Cell/Section mechanics as :class:`CT_Shape` but without the
    shape-identifier attributes.

    .. versionadded:: 0.1.0
    """

    # -- stylesheet references applied to the PageSheet itself --
    line_style = OptionalAttribute("LineStyle", XsdUnsignedInt)
    fill_style = OptionalAttribute("FillStyle", XsdUnsignedInt)
    text_style = OptionalAttribute("TextStyle", XsdUnsignedInt)
    unique_id = OptionalAttribute("UniqueID", XsdString)

    cell = ZeroOrMore("vsdx:Cell")
    section = ZeroOrMore("vsdx:Section")


class CT_Rel(BaseOxmlElement):
    """``<Rel r:id="rId1"/>`` — OPC relationship pointer inside a Page/Master.

    Carries the ``r:id`` that ties the page-index entry (in
    ``pages.xml``) to its page part (``page%d.xml``), or the
    master-index entry (``masters.xml``) to its master part
    (``master%d.xml``).

    .. versionadded:: 0.1.0
    """

    rId = RequiredAttribute("r:id", XsdString)


class CT_Page(BaseOxmlElement):
    """A single entry in the page index.

    Attributes per MS Learn ``Page_Type``:

    - ``@ID`` — unique page ID (page-scoped shape-ID space derives
      from this).
    - ``@Name`` — localised page name (display).
    - ``@NameU`` — universal (locale-invariant) page name.
    - ``@IsCustomName`` / ``@IsCustomNameU`` — booleans (``0``/``1``)
      indicating whether the user has renamed the page.
    - ``@ViewScale`` / ``@ViewCenterX`` / ``@ViewCenterY`` —
      persisted viewport state for next-open.
    - ``@BackPage`` — optional ID of the page used as this page's
      background.

    .. versionadded:: 0.1.0
    """

    id_ = RequiredAttribute("ID", XsdUnsignedInt)
    name = OptionalAttribute("Name", XsdString)
    name_u = OptionalAttribute("NameU", XsdString)
    is_custom_name = OptionalAttribute("IsCustomName", XsdString)
    is_custom_name_u = OptionalAttribute("IsCustomNameU", XsdString)
    view_scale = OptionalAttribute("ViewScale", XsdString)
    view_center_x = OptionalAttribute("ViewCenterX", XsdString)
    view_center_y = OptionalAttribute("ViewCenterY", XsdString)
    # ``@Background="1"`` marks the page as a background page. Absent /
    # ``"0"`` → foreground page (default). See 0.2.0 scoping doc §5.1.
    #
    # .. versionadded:: 0.2.0
    background = OptionalAttribute("Background", XsdString)
    # ``@BackPage="NameU"`` on a foreground page names the background
    # page that renders underneath. **Name reference, not rel-id** —
    # verified against dave-howard/vsdx 0.6.1. Widened from ``XsdUnsignedInt``
    # (the 0.1.0 speculation) to ``XsdString``.
    #
    # .. versionchanged:: 0.2.0
    #     Retyped from ``XsdUnsignedInt`` to ``XsdString`` to match real
    #     Visio-desktop output.
    back_page = OptionalAttribute("BackPage", XsdString)

    pageSheet = ZeroOrOne("vsdx:PageSheet")
    rel = ZeroOrOne("vsdx:Rel")


class CT_PageContents(BaseOxmlElement):
    """Root of ``/visio/pages/page%d.xml``.

    Contains a single ``<Shapes>`` and optional ``<Connects>``. No
    attributes.

    .. versionadded:: 0.1.0
    """

    shapes = ZeroOrOne("vsdx:Shapes")
    connects = ZeroOrOne("vsdx:Connects")

    @property
    def shapes_element(self):
        """Return the ``<Shapes>`` child, creating one if absent.

        Proxy-layer convenience. The track-3 :class:`ShapeTree` proxy
        treats the shapes container as always-present; we create-on-read
        here so a brand-new page part (whose ``<PageContents/>`` is
        empty) materialises a ``<Shapes/>`` the first time any shape is
        appended.

        .. versionadded:: 0.1.0
        """
        return self.get_or_add_shapes()

    @property
    def connects_element(self):
        """Return the ``<Connects>`` child, creating one if absent.

        Proxy-layer convenience, same pattern as
        :attr:`shapes_element`. ``<Connects>`` is optional in
        well-formed Visio XML (pages without connectors legitimately
        omit it); we create-on-read here so the authoring proxy can
        append ``<Connect>`` entries without a dance through
        ``get_or_add_connects``.

        .. versionadded:: 0.1.0
        """
        return self.get_or_add_connects()
