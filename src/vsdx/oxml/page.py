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
    back_page = OptionalAttribute("BackPage", XsdUnsignedInt)

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
