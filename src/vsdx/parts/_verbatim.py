"""Verbatim-blob preservation mixin for Visio XML parts.

Microsoft Visio writes inner XML parts (``/visio/document.xml``,
``/visio/pages/page%d.xml``, ``/visio/masters/master%d.xml``,
``/visio/pages/pages.xml``, ``/visio/masters/masters.xml``,
``/visio/windows.xml``) in an idiosyncratic on-disk form that lxml
cannot reproduce by serialisation:

- XML declaration uses **single-quoted** attribute values and a
  **lowercase** encoding (``<?xml version='1.0' encoding='utf-8' ?>``)
  with no ``standalone`` attribute and a ``\r\n`` separator before
  the root element. lxml emits ``<?xml version="1.0" encoding="UTF-8"
  standalone="yes"?>\n`` regardless.
- Every attribute in the tree uses **single quotes**
  (``xmlns='…'``, ``PinX='1.5'``). lxml's serializer always emits
  double-quoted attributes.

Because lxml can't reproduce Visio's serialisation, the only path to
a byte-identical round-trip on an **unmodified** read is to preserve
the original on-disk bytes verbatim and hand them back at save time.
The trick is detecting "unmodified" cheaply.

Approach: at :meth:`load` we snapshot the original bytes *and* the
lxml-canonical serialisation of the freshly parsed element tree. At
``blob`` access we re-serialise the (possibly mutated) tree through
lxml again and compare to the snapshot — if the two lxml dumps match,
the tree hasn't been mutated, and we can safely return the original
bytes verbatim. If they differ, we fall back to the opc-standard
``serialize_part_xml`` output, losing byte parity but preserving
content correctness.

This pattern is cheap enough to run on every save (a single
``etree.tostring`` plus a bytes comparison) and it automatically
handles the "read then immediately save" case this harness exercises.
Mutation invalidation is automatic — the caller doesn't need to
remember to flip a dirty bit.

Reference: :class:`vsdx.parts.theme.ThemePart` uses a similar
verbatim-on-load strategy but keyed off "theme element ever parsed"
rather than content equality; the theme part stores raw bytes until
someone parses them, whereas the Visio inner parts are parsed at load
time (by the xmlchemy ``CT_*`` descriptors) and mutated via the proxy
layer, so we need content-based detection.

.. versionadded:: 0.1.1
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, cast

from lxml import etree

from ooxml_opc import XmlPart

if TYPE_CHECKING:
    from ooxml_xmlchemy import BaseOxmlElement

    from ooxml_opc import OpcPackage
    from ooxml_opc.packuri import PackURI


__all__ = ["VerbatimXmlPart"]


def _canonical_dump(element: "BaseOxmlElement") -> bytes:
    """Return ``etree.tostring(element)`` — the lxml canonical form.

    No XML declaration, no pretty-printing. This is the fingerprint we
    compare against the load-time snapshot to decide whether the tree
    has been mutated. We intentionally avoid ``method='c14n'`` here —
    C14N canonicalisation is both slower and **too aggressive**: it
    normalises namespace prefix bindings and attribute ordering, so a
    semantically-identical but lxml-reshuffled tree would fingerprint
    the same as the original and we'd return stale bytes.

    The plain ``tostring`` output is what lxml would emit on save
    anyway, so it's the right reference for "did the tree change
    between parse and emit?".
    """
    return cast(bytes, etree.tostring(element))


class VerbatimXmlPart(XmlPart):
    """:class:`~ooxml_opc.part.XmlPart` subclass that preserves on-disk bytes
    when the parsed tree is unmutated.

    Overrides :meth:`load` to capture the source blob and a snapshot
    of the parsed element's lxml serialisation; overrides the
    :attr:`blob` property to return the source bytes when the tree
    hasn't drifted from that snapshot, falling back to the standard
    ``XmlPart.blob`` serialisation path otherwise.

    Parts that subclass :class:`VerbatimXmlPart` rather than
    :class:`~ooxml_opc.part.XmlPart` get Visio-style round-trip fidelity
    for free. Packages built from scratch via :meth:`new` go through
    the :attr:`XmlPart.blob` fallback (no source bytes exist to
    preserve) and serialise in the standard opc form — which is what
    Visio desktop will accept on open.
    """

    @classmethod
    def load(
        cls,
        partname: "PackURI",
        content_type: str,
        package: "OpcPackage",
        blob: bytes,
    ) -> "VerbatimXmlPart":
        """Parse `blob` and stash both the original bytes and a
        fingerprint of the freshly-parsed element tree for later
        mutation detection.
        """
        part = cast(VerbatimXmlPart, super().load(partname, content_type, package, blob))
        part._source_blob = blob
        part._source_fingerprint = _canonical_dump(part._element)
        return part

    # -- instance attrs (declared for type-checkers only) --------------
    _source_blob: Optional[bytes] = None
    _source_fingerprint: Optional[bytes] = None

    @property
    def blob(self) -> bytes:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Return original bytes if tree is unmutated; else lxml-serialised.

        The comparison is bytes-equality between the load-time
        fingerprint (captured in :meth:`load`) and the current lxml
        serialisation of :attr:`element`. Mutations made through any
        path — descriptor setters, ``element.set(...)``, hand-tree
        surgery via ``element.append(...)`` — all show up in that
        comparison, so the dirty-detection has no hand-maintained
        invalidation points.

        For parts created via :meth:`~ooxml_opc.part.XmlPart.__init__`
        (i.e. the :meth:`new` codepath), no source bytes are available,
        so we fall through to the base ``XmlPart.blob`` path.
        """
        if self._source_blob is None or self._source_fingerprint is None:
            return super().blob
        current = _canonical_dump(self._element)
        if current == self._source_fingerprint:
            return self._source_blob
        return super().blob
