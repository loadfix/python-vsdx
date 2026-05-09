"""Text-frame proxy for in-shape text.

Visio's in-shape text lives at ``<Shape>/<Text>``. The element's
children are character-run (``<cp>``), paragraph-run (``<pp>``), and
tab-run (``<tp>``) markers that *index* into the shape's
``Character`` / ``Paragraph`` sections. String text is carried
directly as XML text content between markers.

For 0.1.0 we expose:

* ``TextFrame`` — wraps ``<Text>`` on a shape, exposes ``.text``
  (simple read/write) and iteration over ``.paragraphs``.
* ``Paragraph`` — wraps a paragraph run. ``.text`` read/write.
* ``Run`` — single character-property-scoped span of text.

For 0.1.0's "one paragraph, one run" simple case (the 95% of
flowcharts), writing ``shape.text = 'hi'`` is a one-liner and the
marker / section dance stays implicit. Richer authoring (multi-run,
colour / font-size per run) is 0.2.0 scope.
"""

from __future__ import annotations

from vsdx.text.text import Paragraph, Run, TextFrame

__all__ = ["Paragraph", "Run", "TextFrame"]
