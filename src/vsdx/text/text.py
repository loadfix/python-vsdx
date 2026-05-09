"""``TextFrame`` / ``Paragraph`` / ``Run`` proxies for Visio in-shape text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional

from vsdx.shared import ElementProxy

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Text  # TODO(vsdx/track-1): from vsdx.oxml.text


class TextFrame(ElementProxy):
    """In-shape text.

    Wraps the ``<Text>`` child of a ``<Shape>``. For 0.1.0 the read /
    write surface is a single ``.text`` string — the element's text
    content between cp/pp/tp markers is the concatenation of the
    paragraph runs.
    """

    _element: "CT_Text"

    def __init__(self, text_element: "CT_Text") -> None:
        super().__init__(text_element)

    # -- simple string read/write ---------------------------------------

    @property
    def text(self) -> str:
        """Full text content of the frame, joined across paragraphs."""
        return self._element.text or ""

    @text.setter
    def text(self, value: str) -> None:
        """Replace the entire text content with *value*.

        0.1.0 normalises the element to carry a single string body and
        no child runs. When Track 1's richer ``CT_Text`` lands we'll
        preserve cp/pp/tp markers across updates, but for the happy
        path (``shape.text = 'Start'``) the marker-less form is what
        Visio desktop itself emits for brand-new shapes.
        """
        self._element.text = value

    # -- paragraph iteration --------------------------------------------

    @property
    def paragraphs(self) -> list["Paragraph"]:
        """List of paragraphs. 0.1.0: exactly one paragraph mirroring ``.text``."""
        return [Paragraph(self._element)]

    def clear(self) -> None:
        """Remove all text content."""
        self._element.text = ""

    def add_paragraph(self, text: str = "") -> "Paragraph":
        """Append a paragraph.

        0.1.0 implementation: newline-joins onto ``.text``. A future
        release will emit a real ``<pp/>`` marker run.
        """
        existing = self._element.text or ""
        joined = f"{existing}\n{text}" if existing else text
        self._element.text = joined
        return Paragraph(self._element)


class Paragraph(ElementProxy):
    """A paragraph run within a ``TextFrame``.

    0.1.0: thin wrapper around the parent ``CT_Text`` — the whole
    element carries one paragraph. Multi-paragraph support lands when
    the pp-marker machinery goes in (0.2.0).
    """

    _element: "CT_Text"

    @property
    def text(self) -> str:
        return self._element.text or ""

    @text.setter
    def text(self, value: str) -> None:
        self._element.text = value

    @property
    def runs(self) -> list["Run"]:
        return [Run(self._element)]

    def add_run(self, text: str = "") -> "Run":
        existing = self._element.text or ""
        self._element.text = existing + text
        return Run(self._element)


class Run(ElementProxy):
    """A character-run within a ``Paragraph``.

    0.1.0: thin wrapper around ``CT_Text`` — one run == the full text.
    Per-run formatting (font, size, colour) is wired up in 0.2.0 when
    the ``<Section N="Character">`` row machinery is in the oxml layer.
    """

    _element: "CT_Text"

    @property
    def text(self) -> str:
        return self._element.text or ""

    @text.setter
    def text(self, value: str) -> None:
        self._element.text = value


__all__ = ["Paragraph", "Run", "TextFrame"]
