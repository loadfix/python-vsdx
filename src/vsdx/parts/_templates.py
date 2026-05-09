"""Minimal default-XML templates used by :mod:`vsdx.parts`.

Each template is a bytes literal carrying the bare minimum a Visio
part needs to round-trip through ``ooxml_opc``'s package writer:

- the XML declaration with ``standalone="yes"`` (Microsoft-canonical
  form, matches what ``serialize_part_xml`` emits on re-save);
- a root element in the Visio core namespace
  (``http://schemas.microsoft.com/office/visio/2011/1/core``) declared
  as the default (empty-prefix) namespace — this matches what real
  Visio desktop writes and keeps serialisation prefix-stable.

These templates let the parts layer construct "empty but valid" parts
without blocking on the track 1 ``CT_*`` element classes. When those
classes land, each part's ``new()`` classmethod can switch to
``CT_VisioDocument.new_default()`` etc. in a follow-up patch. The
templates stay as a fallback.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

from vsdx.constants import NS_R, NS_VSDX_CORE

# -- XML declaration. ``serialize_part_xml`` rewrites lxml's single-quoted --
# -- form to double quotes on write; we emit the double-quoted form here   --
# -- so the load → new-element → serialise path is byte-stable without a  --
# -- normalisation round-trip.                                              --
_XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _root(local_name: str, *, attrs: str = "") -> bytes:
    """Return default XML blob for a Visio-namespaced root element.

    The root element carries ``xmlns=<NS_VSDX_CORE>`` and
    ``xmlns:r=<NS_R>`` so downstream relationship-bearing children
    (``<Rel r:id="…"/>``) serialise with the ``r:`` prefix Microsoft
    Office expects. `attrs` is injected verbatim into the opening
    tag (e.g. ``xml:space="preserve"``).
    """
    attrs_part = f" {attrs}" if attrs else ""
    body = (
        f'<{local_name} xmlns="{NS_VSDX_CORE}" xmlns:r="{NS_R}"'
        f"{attrs_part}/>"
    )
    return _XML_DECL + body.encode("utf-8")


#: Default ``/visio/document.xml`` blob — ``<VisioDocument/>`` with
#: the Visio core default namespace and the OPC relationships prefix.
#: Track 1's ``CT_VisioDocument`` will hydrate additional children
#: (``DocumentSettings``, ``StyleSheets``, etc.) on the save path; the
#: 0.1.0 parts layer only needs a round-trippable empty shell.
DEFAULT_DOCUMENT_XML = _root("VisioDocument")

#: Default ``/visio/pages/pages.xml`` blob — empty ``<Pages/>`` index.
DEFAULT_PAGES_XML = _root("Pages")

#: Default ``/visio/pages/page%d.xml`` blob — empty
#: ``<PageContents/>``. Page metadata (``@ID``, ``@Name``) lives in
#: ``pages.xml``; this is the per-page shape-tree part.
DEFAULT_PAGE_XML = _root("PageContents")

#: Default ``/visio/masters/masters.xml`` blob — empty ``<Masters/>``
#: index.
DEFAULT_MASTERS_XML = _root("Masters")

#: Default ``/visio/masters/master%d.xml`` blob — empty
#: ``<MasterContents/>``.
DEFAULT_MASTER_XML = _root("MasterContents")

#: Default ``/visio/windows.xml`` blob — empty ``<Windows/>``.
DEFAULT_WINDOWS_XML = _root("Windows")
