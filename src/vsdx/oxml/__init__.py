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

"""Hardened lxml parser + namespace registry + ``CT_*`` registration.

Mirrors ``ooxml_chart.oxml`` / ``ooxml_shared_drawingml.oxml`` but for
the Visio namespace. Parser is XXE/billion-laughs-hardened
(``resolve_entities=False``, ``no_network=True``, ``huge_tree=False``).
Installs a :class:`NamespaceRegistry` so descriptors resolve the
``vsdx:`` and ``r:`` prefixes; the composite registry stacks it
alongside whatever sibling packages register.

Visio's convention is that serialised XML uses the **default
namespace** for the Visio URI (``xmlns="…/visio/2011/1/core"``) with
no prefix. Internally we use the prefix ``vsdx:`` for :func:`qn`
resolution and for ``nsdecls`` in unit-test inputs; lxml normalises
to the default namespace on real-world writes.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from lxml import etree
from ooxml_xmlchemy import (
    NamespaceRegistry,
    configure_namespace_registry,
)

from vsdx.constants import NS_R, NS_VSDX_CORE, NS_XML

if TYPE_CHECKING:
    from ooxml_xmlchemy import BaseOxmlElement


__all__ = [
    "nsdecls",
    "nsmap",
    "parse_xml",
    "qn",
    "register_element_cls",
]


# -- namespace prefix mapping used everywhere in this package --------------
# ``vsdx`` is an internal convenience — lxml serialises it as the default
# namespace on real-world writes because that's what Visio emits.
nsmap: dict[str, str] = {
    "vsdx": NS_VSDX_CORE,
    "r": NS_R,
    "xml": NS_XML,
}

# -- inverse: Clark-URI -> prefix --
_pfxmap: dict[str, str] = {uri: pfx for pfx, uri in nsmap.items()}


def qn(namespace_prefixed_tag: str) -> str:
    """Return the Clark-notation form of ``namespace_prefixed_tag``.

    .. versionadded:: 0.1.0
    """
    prefix, local = namespace_prefixed_tag.split(":", 1)
    return f"{{{nsmap[prefix]}}}{local}"


def _clark_to_nsptag(clark_name: str) -> str:
    if not clark_name.startswith("{"):
        return clark_name
    uri, local = clark_name[1:].split("}", 1)
    return f"{_pfxmap[uri]}:{local}"


def nsdecls(*prefixes: str) -> str:
    """Return ``"xmlns:pfx=..."`` declarations for *prefixes* (space-separated).

    .. versionadded:: 0.1.0
    """
    return " ".join(f'xmlns:{pfx}="{nsmap[pfx]}"' for pfx in prefixes)


# -- lxml parser with hardened safety settings ------------------------------
_element_class_lookup = etree.ElementNamespaceClassLookup()

_oxml_parser = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=False,
    remove_blank_text=False,
)
_oxml_parser.set_element_class_lookup(_element_class_lookup)


def parse_xml(xml: "str | bytes") -> "BaseOxmlElement":
    """Return the root ``BaseOxmlElement`` parsed from *xml*.

    Uses the hardened package-wide parser. Safe to call on
    attacker-controlled bytes (XXE / billion-laughs blocked).

    .. versionadded:: 0.1.0
    """
    return cast("BaseOxmlElement", etree.fromstring(xml, _oxml_parser))


def _OxmlElement(  # noqa: N802
    nsptag_str: str, nsmap_override: "dict[str, str] | None" = None
) -> "BaseOxmlElement":
    prefix, _ = nsptag_str.split(":", 1)
    ns = nsmap_override if nsmap_override is not None else {prefix: nsmap[prefix]}
    element = _oxml_parser.makeelement(qn(nsptag_str), nsmap=ns)
    return cast("BaseOxmlElement", element)


def register_element_cls(
    nsptag_str: str, cls: "type[BaseOxmlElement]"
) -> None:
    """Associate ``cls`` with the element named *nsptag_str* on the parser.

    .. versionadded:: 0.1.0
    """
    prefix, local = nsptag_str.split(":", 1)
    namespace = _element_class_lookup.get_namespace(nsmap[prefix])
    namespace[local] = cls


class _Registry:
    """:class:`NamespaceRegistry` implementation backed by :data:`nsmap`."""

    nsmap = nsmap

    def qn(self, namespace_prefixed_tag: str) -> str:
        return qn(namespace_prefixed_tag)

    def clark_to_nsptag(self, clark_name: str) -> str:
        return _clark_to_nsptag(clark_name)

    def OxmlElement(  # noqa: N802
        self,
        nsptag_str: str,
        nsmap: "dict[str, str] | None" = None,
    ) -> "BaseOxmlElement":
        return _OxmlElement(nsptag_str, nsmap)


_registry: NamespaceRegistry = _Registry()
configure_namespace_registry(_registry)


# -- CT_* imports sit below the registry configuration so xmlchemy
# -- descriptors resolving ``qn()`` at class-body evaluation time see
# -- a valid registry.

from vsdx.oxml.cell import CT_Cell  # noqa: E402
from vsdx.oxml.row import CT_Row  # noqa: E402
from vsdx.oxml.section import CT_Section  # noqa: E402
from vsdx.oxml.shape import CT_ForeignData, CT_Shape, CT_Text  # noqa: E402
from vsdx.oxml.shapes import CT_Shapes  # noqa: E402
from vsdx.oxml.page import (  # noqa: E402
    CT_Page,
    CT_PageContents,
    CT_PageSheet,
    CT_Rel,
)
from vsdx.oxml.pages import CT_Pages  # noqa: E402
from vsdx.oxml.master import (  # noqa: E402
    CT_Icon,
    CT_Master,
    CT_MasterContents,
)
from vsdx.oxml.masters import CT_Masters  # noqa: E402
from vsdx.oxml.document import (  # noqa: E402
    CT_Colors,
    CT_DocumentProperties,
    CT_DocumentSettings,
    CT_DocumentSheet,
    CT_EventList,
    CT_FaceNames,
    CT_StyleSheet,
    CT_StyleSheets,
    CT_VisioDocument,
)
from vsdx.oxml.connects import CT_Connect, CT_Connects  # noqa: E402
from vsdx.oxml.window import CT_Window, CT_Windows  # noqa: E402


__all__ += [
    "CT_Cell",
    "CT_Colors",
    "CT_Connect",
    "CT_Connects",
    "CT_DocumentProperties",
    "CT_DocumentSettings",
    "CT_DocumentSheet",
    "CT_EventList",
    "CT_FaceNames",
    "CT_ForeignData",
    "CT_Icon",
    "CT_Master",
    "CT_MasterContents",
    "CT_Masters",
    "CT_Page",
    "CT_PageContents",
    "CT_PageSheet",
    "CT_Pages",
    "CT_Rel",
    "CT_Row",
    "CT_Section",
    "CT_Shape",
    "CT_Shapes",
    "CT_StyleSheet",
    "CT_StyleSheets",
    "CT_Text",
    "CT_VisioDocument",
    "CT_Window",
    "CT_Windows",
]


# -- element-class registrations -------------------------------------------
# cell / row / section
register_element_cls("vsdx:Cell", CT_Cell)
register_element_cls("vsdx:Row", CT_Row)
register_element_cls("vsdx:Section", CT_Section)
register_element_cls("vsdx:Trigger", CT_Cell)
# shape / shapes / text / foreignData
register_element_cls("vsdx:Shape", CT_Shape)
register_element_cls("vsdx:Shapes", CT_Shapes)
register_element_cls("vsdx:Text", CT_Text)
register_element_cls("vsdx:ForeignData", CT_ForeignData)
# page / pages
register_element_cls("vsdx:Page", CT_Page)
register_element_cls("vsdx:Pages", CT_Pages)
register_element_cls("vsdx:PageSheet", CT_PageSheet)
register_element_cls("vsdx:PageContents", CT_PageContents)
register_element_cls("vsdx:Rel", CT_Rel)
# master / masters
register_element_cls("vsdx:Master", CT_Master)
register_element_cls("vsdx:Masters", CT_Masters)
register_element_cls("vsdx:MasterContents", CT_MasterContents)
register_element_cls("vsdx:Icon", CT_Icon)
# document
register_element_cls("vsdx:VisioDocument", CT_VisioDocument)
register_element_cls("vsdx:DocumentProperties", CT_DocumentProperties)
register_element_cls("vsdx:DocumentSettings", CT_DocumentSettings)
register_element_cls("vsdx:DocumentSheet", CT_DocumentSheet)
register_element_cls("vsdx:StyleSheets", CT_StyleSheets)
register_element_cls("vsdx:StyleSheet", CT_StyleSheet)
register_element_cls("vsdx:Colors", CT_Colors)
register_element_cls("vsdx:FaceNames", CT_FaceNames)
register_element_cls("vsdx:EventList", CT_EventList)
# connects
register_element_cls("vsdx:Connects", CT_Connects)
register_element_cls("vsdx:Connect", CT_Connect)
# windows
register_element_cls("vsdx:Windows", CT_Windows)
register_element_cls("vsdx:Window", CT_Window)
