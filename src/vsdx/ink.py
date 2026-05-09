"""Ink-annotation proxies and authoring helpers for Visio pages.

Visio stores ink annotations as separate package parts carrying a W3C
`InkML 1.0 <http://www.w3.org/2003/InkML>`_ payload — the same shape
docx (``/word/ink/``) and pptx (``/ppt/ink/``) use. python-vsdx parks
them under ``/visio/ink/ink{n}.xml`` and references each part from the
owning :class:`~vsdx.page.Page`'s page-part relationships using the
shared :data:`ooxml_ink.RELATIONSHIP_TYPE_INK` URI.

Exposed at two granularities:

- :class:`InkStroke` — one per ``<inkml:trace>`` on a page. Surfaces
  ``.points`` / ``.color`` / ``.width`` / ``.pressure`` and is the shape
  returned by :meth:`vsdx.page.Page.add_ink_stroke`.
- :attr:`vsdx.page.Page.ink_strokes` /
  :attr:`vsdx.document.VisioDocument.ink_strokes` — flat stroke iteration
  across the page or document.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ooxml_ink.oxml.inkml import CT_Ink, CT_Trace


__all__ = ["InkStroke"]


class InkStroke:
    """Proxy for a single ``<inkml:trace>`` ink stroke on a Visio page.

    Wraps the underlying :class:`ooxml_ink.oxml.inkml.CT_Trace` element
    and resolves brush-level styling (colour / width) through the
    containing :class:`ooxml_ink.oxml.inkml.CT_Ink` root's
    ``<inkml:definitions>`` preamble.

    Read-only in 0.3.0 — the authoring workflow is append-only via
    :meth:`vsdx.page.Page.add_ink_stroke`; mutating setters land in a
    later revision.

    .. versionadded:: 0.3.0
    """

    def __init__(self, trace: "CT_Trace", ink: "CT_Ink"):
        self._trace = trace
        self._ink = ink

    # -- core data ----------------------------------------------------------

    @property
    def points(self) -> "list[tuple[float, ...]]":
        """List of sample points carried by the underlying ``<inkml:trace>``.

        Each element is a 2-tuple ``(x, y)`` — or, when the stroke was
        authored with per-point pressure, a 3-tuple ``(x, y, pressure)``.
        All points in a single stroke share the same arity.

        Returns ``[]`` for an empty ``<inkml:trace>``. Raises
        :class:`ValueError` when the sample text is not parseable.
        """
        text = (self._trace.sample_point_text or "").strip()
        if not text:
            return []
        samples: list[tuple[float, ...]] = []
        for raw in text.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                nums = tuple(float(tok) for tok in raw.split())
            except ValueError as exc:
                raise ValueError(
                    f"unparseable InkML sample {raw!r} in <inkml:trace>"
                ) from exc
            if len(nums) < 2:
                raise ValueError(
                    f"InkML sample {raw!r} has fewer than 2 channels (X, Y required)"
                )
            samples.append(nums)
        return samples

    @property
    def id(self) -> "str | None":
        """The ``xml:id`` attribute value on the underlying trace, or |None|.

        Present on Office-authored traces; :meth:`~vsdx.page.Page.
        add_ink_stroke` leaves it unset.
        """
        return self._trace.id

    # -- brush-level styling ------------------------------------------------

    @property
    def color(self) -> "str | None":
        """Hex-RGB string of the stroke colour, or |None|.

        Resolved by looking up the trace's ``brushRef`` in the ink
        part's ``<inkml:definitions>`` and reading the
        ``<inkml:brushProperty name="color" value="#RRGGBB"/>`` child of
        the referenced brush.
        """
        return self._brush_property("color")

    @property
    def width(self) -> "float | None":
        """Nib width of the stroke in pixels, or |None|.

        Reads ``<inkml:brushProperty name="width"/>`` on the brush
        referenced by the trace's ``brushRef``. The returned value is a
        float; callers that need an integer pixel count should round
        explicitly.
        """
        raw = self._brush_property("width")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @property
    def pressure(self) -> "list[float] | None":
        """Per-point pressure channel if the stroke carries one, else |None|.

        Returns the third-channel values from :attr:`points` (the ``F``
        pressure channel in Office's InkML) when every point carries a
        pressure sample, otherwise |None|.
        """
        pts = self.points
        if not pts:
            return None
        if all(len(p) >= 3 for p in pts):
            return [p[2] for p in pts]
        return None

    # -- internals ----------------------------------------------------------

    def _brush_property(self, name: str) -> "str | None":
        """Return the ``<inkml:brushProperty name=name value="..."/>`` value.

        Looks up the trace's ``brushRef`` (skipping the leading ``#`` if
        present) against the ink part's ``<inkml:definitions>`` and
        returns the requested brush-property's ``value`` attribute.
        |None| when the trace has no ``brushRef``, the referenced brush
        is missing, or the property is not declared on that brush.
        """
        brush_ref = self._trace.brushRef
        if not brush_ref:
            return None
        brush_id = brush_ref.lstrip("#")
        defs = self._ink.definitions
        if defs is None:
            return None
        xml_id_qn = "{http://www.w3.org/XML/1998/namespace}id"
        inkml_ns = "http://www.w3.org/2003/InkML"
        brush_elm = None
        for elm in defs.iterchildren("{%s}brush" % inkml_ns):
            if elm.get(xml_id_qn) == brush_id or elm.get("id") == brush_id:
                brush_elm = elm
                break
        if brush_elm is None:
            return None
        for prop in brush_elm.iterchildren("{%s}brushProperty" % inkml_ns):
            if prop.get("name") == name:
                return prop.get("value")
        return None
