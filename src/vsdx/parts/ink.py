"""|InkPart| for Visio — ``application/inkml+xml`` under ``/visio/ink/``.

Visio stores digital-ink annotations as separate package parts carrying a
W3C `InkML <http://www.w3.org/2003/InkML>`_ payload, identical in shape to
the ink parts docx and pptx emit. The payload parser + element classes
live in the shared :mod:`ooxml_ink` package; this module wraps that with
a Visio-specific partname template, a ``new()`` authoring factory, and
``append_trace`` / ``rebuild_blob`` helpers that ``Page.add_ink_stroke``
drives.

Unlike pptx — which has to subclass its own internal ``pptx.opc.package.
Part`` because the pptx relationship layer type-checks against that class
— vsdx uses the shared :class:`ooxml_opc.Part` directly, so the Visio
:class:`InkPart` can subclass the shared :class:`ooxml_ink.part.InkPart`
verbatim.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence, cast

from lxml import etree
from ooxml_ink import CONTENT_TYPE_INK
from ooxml_ink.oxml.inkml import CT_Ink
from ooxml_ink.part import InkPart as _SharedInkPart
from ooxml_opc.packuri import PackURI

if TYPE_CHECKING:
    from ooxml_opc import OpcPackage


__all__ = ["InkPart", "PACK_URI_TMPL_VSDX_INK", "append_trace", "rebuild_blob"]


# -- W3C InkML namespace URI; reused across xpath / element queries --
_INKML_NS = "http://www.w3.org/2003/InkML"

#: Partname template for Visio ink parts. ``% N`` yields
#: ``"/visio/ink/ink1.xml"``. Mirrors the docx (`/word/ink/`) and pptx
#: (`/ppt/ink/`) conventions — Visio does not have an official MS-Learn
#: naming rule for ink parts, so we adopt the sibling-format convention.
PACK_URI_TMPL_VSDX_INK = "/visio/ink/ink%d.xml"


class InkPart(_SharedInkPart):
    """A Visio ``application/inkml+xml`` part.

    Subclasses the shared :class:`ooxml_ink.part.InkPart` to add a
    Visio-specific partname allocator (``/visio/ink/ink%d.xml``) and a
    cache slot that :func:`append_trace` / :func:`rebuild_blob` mutate.
    The inherited :attr:`ink` accessor parses :attr:`blob` lazily on
    first read.

    Loading is handled by the shared :meth:`~ooxml_ink.part.InkPart.load`
    classmethod — :func:`vsdx.package.register_visio_parts` installs this
    class as the content-type handler for
    :data:`~ooxml_ink.CONTENT_TYPE_INK`.

    .. versionadded:: 0.3.0
    """

    @classmethod
    def new(cls, package: "OpcPackage") -> "InkPart":
        """Return a newly-created empty :class:`InkPart` registered with *package*.

        Mints the next free ``/visio/ink/ink{n}.xml`` partname via the
        package's numeric allocator, wires up a blank ``<inkml:ink/>``
        root, and serialises it so :attr:`blob` is ready to save. The
        caller is responsible for establishing the
        :data:`~ooxml_ink.RELATIONSHIP_TYPE_INK` relationship from the
        page part — see :meth:`vsdx.page.Page.add_ink_stroke`.

        .. versionadded:: 0.3.0
        """
        partname = PackURI(str(package.next_partname(PACK_URI_TMPL_VSDX_INK)))
        part = cls(partname, CONTENT_TYPE_INK, package)
        ink = CT_Ink.new()
        part._ink = ink
        part._blob = _serialize_ink(ink)
        return part


def append_trace(
    part: "InkPart",
    points: "Sequence[Sequence[float]]",
    pressure: "Sequence[float] | None" = None,
    color: "str | None" = None,
    width: "float | None" = None,
) -> "etree._Element":
    """Append an ``<inkml:trace>`` to *part* and return the new element.

    *points* is a sequence of ``(x, y)`` pairs. When *pressure* is
    supplied it must be the same length as *points*; pressure values are
    written as a third ``F`` channel per sample
    (``"X Y F, X Y F"``).

    *color* (hex RGB; ``"#RRGGBB"`` or ``"RRGGBB"``) and *width* (pixel
    width) create a matched ``<inkml:brush>`` under
    ``<inkml:definitions>`` and wire the new trace to it via
    ``brushRef="#brN"``. Omit both to emit a bare trace with no brush
    metadata.

    Mutates *part* in place and re-serialises :attr:`InkPart.blob` on
    exit so subsequent saves pick up the new trace.

    .. versionadded:: 0.3.0
    """
    if pressure is not None and len(pressure) != len(points):
        raise ValueError(
            "pressure length %d does not match points length %d"
            % (len(pressure), len(points))
        )

    ink = part.ink
    trace = etree.SubElement(ink, "{%s}trace" % _INKML_NS)

    samples = []
    for i, pt in enumerate(points):
        coords = [format(float(c), "g") for c in pt[:2]]
        if pressure is not None:
            coords.append(format(float(pressure[i]), "g"))
        samples.append(" ".join(coords))
    trace.text = ", ".join(samples)

    if color is not None or width is not None:
        brush_id = _get_or_create_brush(ink, color=color, width=width)
        trace.set("brushRef", "#%s" % brush_id)

    rebuild_blob(part)
    return trace


def rebuild_blob(part: "InkPart") -> None:
    """Re-serialise *part*'s in-memory ``<inkml:ink>`` element to its blob.

    Call after direct edits to the element tree returned by
    :attr:`InkPart.ink` so those edits reach :attr:`InkPart.blob` (and
    therefore the saved package bytes).

    No-op when the part's ``ink`` tree has not yet been parsed — blob
    remains authoritative in that case.

    .. versionadded:: 0.3.0
    """
    cached_ink = part._ink
    if cached_ink is None:
        return
    part._blob = _serialize_ink(cached_ink)


# -- internals -------------------------------------------------------------


def _serialize_ink(ink: "CT_Ink") -> bytes:
    """Return the serialised bytes for *ink* with a standalone XML declaration."""
    return cast(
        bytes,
        etree.tostring(
            ink,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        ),
    )


def _get_or_create_brush(
    ink: "CT_Ink",
    color: "str | None" = None,
    width: "float | None" = None,
) -> str:
    """Return a fresh brush ``xml:id`` for the given colour / width pair.

    Always creates a new ``<inkml:brush>`` under ``<inkml:definitions>``
    rather than attempting to reuse an existing one — colour or width
    changes between adjacent strokes are common and de-duplicating would
    require a property-set hash for marginal byte savings. The unique id
    is ``"brN"`` where ``N`` is one past the count of existing brushes.
    """
    defs = ink.get_or_add_definitions()

    xml_id_qn = "{http://www.w3.org/XML/1998/namespace}id"
    existing = list(defs.iterchildren("{%s}brush" % _INKML_NS))
    brush_id = "br%d" % (len(existing) + 1)

    brush = etree.SubElement(defs, "{%s}brush" % _INKML_NS)
    brush.set(xml_id_qn, brush_id)

    if color is not None:
        value = color if color.startswith("#") else "#%s" % color
        prop = etree.SubElement(brush, "{%s}brushProperty" % _INKML_NS)
        prop.set("name", "color")
        prop.set("value", value)

    if width is not None:
        prop = etree.SubElement(brush, "{%s}brushProperty" % _INKML_NS)
        prop.set("name", "width")
        prop.set("value", format(float(width), "g"))

    return brush_id
