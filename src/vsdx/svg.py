"""Minimal SVG renderer for vsdx pages — R17-4.

Turns a :class:`~vsdx.page.Page` into a standalone SVG 1.1 document
without spinning up Visio or a full rendering pipeline. Only common
shape kinds are handled today:

* :class:`~vsdx.shapes.autoshape.Rectangle` — emitted as ``<rect>``.
* :class:`~vsdx.shapes.autoshape.Ellipse` — emitted as ``<ellipse>``.
* Plain :class:`~vsdx.shapes.base.TextShape` instances with non-empty
  text and zero/unknown geometry — emitted as ``<text>`` at the shape
  pin.
* :class:`~vsdx.shapes.connector.Connector` instances — emitted as a
  straight ``<line>`` from ``BeginX`` / ``BeginY`` to ``EndX`` /
  ``EndY``. Right-angle routing, waypoints, and arrowheads are out of
  scope.

Anything else (triangle, group, custom master) renders as an empty
``<rect>`` placeholder with an ``<!-- unsupported ... -->`` comment so
the export continues end-to-end.

Coordinate translation: Visio's origin is bottom-left and the unit is
the inch. SVG's origin is top-left and the unit is the user-space
pixel. We pick a ``1 inch = 96 px`` scale (the SVG default DPI) and
flip the Y axis against the page height so ``pin_y`` reads the same
way it does in Visio desktop.

Security note: every piece of caller-authored text (shape text, master
names on unsupported-shape comments) is escaped with
:func:`xml.sax.saxutils.escape` before emission so an attacker-
controlled ``shape.text`` cannot inject markup into the SVG.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, List, Optional
from xml.sax.saxutils import escape as _xml_escape
from xml.sax.saxutils import quoteattr as _xml_quoteattr

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.page import Page
    from vsdx.shapes.base import Shape


# 96 CSS pixels per inch is the SVG default user-unit mapping. Callers
# that need a different scale can post-process the output (or we can
# add a ``dpi=`` kwarg later when the need lands).
_PX_PER_INCH = 96.0


def _format_coord(value: float) -> str:
    """Format a float for SVG emission — trim trailing zeros."""
    if value == int(value):
        return str(int(value))
    return ("%.4f" % value).rstrip("0").rstrip(".")


def _parse_color(raw: Optional[str], default: str) -> str:
    """Turn a Visio FillForegnd / LineColor cell value into an SVG paint.

    Visio colour cells carry either a six-hex-digit RGB (``"FF0000"``
    or ``"#FF0000"``), a theme-colour index (``"0"`` — ``"24"``), or a
    theme expression (``THEMEGUARD(...)``). We only handle the direct
    RGB form today; anything else falls back to *default*. Theme
    resolution lands when the theme-colour plumbing becomes the common
    case in diagram renders.
    """
    if raw is None or raw == "":
        return default
    stripped = raw.strip()
    if stripped.startswith("#") and len(stripped) == 7:
        return stripped
    if len(stripped) == 6 and all(c in "0123456789abcdefABCDEF" for c in stripped):
        return "#" + stripped.upper()
    return default


def _inches_to_px(value: float) -> float:
    return value * _PX_PER_INCH


def _svg_xy_for_pin(
    pin_x: float, pin_y: float, page_height: float
) -> tuple[float, float]:
    """Visio page-inches (bottom-left origin) -> SVG user-space (top-left)."""
    return _inches_to_px(pin_x), _inches_to_px(page_height - pin_y)


def _render_rectangle(shape: "Shape", page_height: float) -> str:
    w = float(shape.width) or 0.0
    h = float(shape.height) or 0.0
    pin_x = float(shape.pin_x)
    pin_y = float(shape.pin_y)
    # Visio pins are centres; SVG <rect> positions by top-left corner.
    left_in = pin_x - w / 2.0
    top_in_svg = page_height - (pin_y + h / 2.0)
    x_px = _inches_to_px(left_in)
    y_px = _inches_to_px(top_in_svg)
    w_px = _inches_to_px(w)
    h_px = _inches_to_px(h)
    fill = _parse_color(shape.fill_foregnd, "#FFFFFF")
    stroke = _parse_color(shape.line_color, "#000000")
    return (
        '<rect x="%s" y="%s" width="%s" height="%s" '
        'fill="%s" stroke="%s" stroke-width="1"/>'
        % (
            _format_coord(x_px),
            _format_coord(y_px),
            _format_coord(w_px),
            _format_coord(h_px),
            fill,
            stroke,
        )
    )


def _render_ellipse(shape: "Shape", page_height: float) -> str:
    w = float(shape.width) or 0.0
    h = float(shape.height) or 0.0
    pin_x = float(shape.pin_x)
    pin_y = float(shape.pin_y)
    cx_px, cy_px = _svg_xy_for_pin(pin_x, pin_y, page_height)
    rx_px = _inches_to_px(w / 2.0)
    ry_px = _inches_to_px(h / 2.0)
    fill = _parse_color(shape.fill_foregnd, "#FFFFFF")
    stroke = _parse_color(shape.line_color, "#000000")
    return (
        '<ellipse cx="%s" cy="%s" rx="%s" ry="%s" '
        'fill="%s" stroke="%s" stroke-width="1"/>'
        % (
            _format_coord(cx_px),
            _format_coord(cy_px),
            _format_coord(rx_px),
            _format_coord(ry_px),
            fill,
            stroke,
        )
    )


def _render_connector(shape: "Shape", page_height: float) -> str:
    # Straight segment from (BeginX, BeginY) to (EndX, EndY). Right-
    # angle routing and arrowheads are deliberately absent until the
    # full routing engine lands.
    bx = getattr(shape, "begin_x", None) or 0.0
    by = getattr(shape, "begin_y", None) or 0.0
    ex = getattr(shape, "end_x", None) or 0.0
    ey = getattr(shape, "end_y", None) or 0.0
    x1_px, y1_px = _svg_xy_for_pin(float(bx), float(by), page_height)
    x2_px, y2_px = _svg_xy_for_pin(float(ex), float(ey), page_height)
    stroke = _parse_color(getattr(shape, "line_color", None), "#000000")
    return (
        '<line x1="%s" y1="%s" x2="%s" y2="%s" '
        'stroke="%s" stroke-width="1"/>'
        % (
            _format_coord(x1_px),
            _format_coord(y1_px),
            _format_coord(x2_px),
            _format_coord(y2_px),
            stroke,
        )
    )


def _render_text(shape: "Shape", page_height: float) -> Optional[str]:
    """Render the shape's in-shape text as a ``<text>`` element.

    Returns ``None`` when the shape carries no text — the caller uses
    that to decide whether a text-only shape needs a placeholder.
    """
    text = getattr(shape, "text", None)
    if not text:
        return None
    pin_x = float(shape.pin_x)
    pin_y = float(shape.pin_y)
    x_px, y_px = _svg_xy_for_pin(pin_x, pin_y, page_height)
    return (
        '<text x="%s" y="%s" text-anchor="middle" '
        'dominant-baseline="middle" font-family="Calibri,sans-serif" '
        'font-size="12" fill="#000000">%s</text>'
        % (_format_coord(x_px), _format_coord(y_px), _xml_escape(text))
    )


def _render_shape(shape: "Shape", page_height: float) -> List[str]:
    """Return the list of SVG element strings for *shape*.

    A shape can expand to more than one SVG element — a rectangle
    with text yields a ``<rect>`` and a ``<text>``. Unsupported
    shapes yield a placeholder ``<rect>`` and a comment so the file
    stays valid.
    """
    # Deferred imports dodge the page <-> svg cycle that would
    # otherwise trip up vsdx.__init__.
    from vsdx.shapes.autoshape import Ellipse, Rectangle
    from vsdx.shapes.connector import Connector

    parts: List[str] = []
    if isinstance(shape, Rectangle):
        parts.append(_render_rectangle(shape, page_height))
        text_el = _render_text(shape, page_height)
        if text_el is not None:
            parts.append(text_el)
        return parts

    if isinstance(shape, Ellipse):
        parts.append(_render_ellipse(shape, page_height))
        text_el = _render_text(shape, page_height)
        if text_el is not None:
            parts.append(text_el)
        return parts

    if isinstance(shape, Connector):
        parts.append(_render_connector(shape, page_height))
        return parts

    # Plain text shape — no geometry-bearing master. Render just the
    # text at the pin if there's any content to show.
    text_el = _render_text(shape, page_height)
    if text_el is not None and not shape.master_name_u:
        parts.append(text_el)
        return parts

    # Unsupported: emit a zero-size placeholder rect anchored at the
    # pin so callers counting elements can still find one element per
    # source shape. The master name is escaped so an attacker cannot
    # inject markup via a crafted master attribute.
    master = shape.master_name_u or "(unknown)"
    parts.append("<!-- unsupported shape: master=%s -->" % _xml_escape(master))
    pin_x = float(shape.pin_x)
    pin_y = float(shape.pin_y)
    x_px, y_px = _svg_xy_for_pin(pin_x, pin_y, page_height)
    parts.append(
        '<rect x="%s" y="%s" width="0" height="0" fill="none" stroke="none"/>'
        % (_format_coord(x_px), _format_coord(y_px))
    )
    return parts


def page_to_svg(page: "Page") -> str:
    """Render *page* as a standalone SVG 1.1 document string.

    See module docstring for the coordinate / scale conventions and the
    supported-shape list. The return value is an encoded-declaration-
    free string suitable for both direct ``.write()`` and embedding
    inside an HTML ``<iframe srcdoc="">`` attribute.
    """
    page_width = float(page.width)
    page_height = float(page.height)
    w_px = _inches_to_px(page_width)
    h_px = _inches_to_px(page_height)

    elements: List[str] = []
    for shape in page.shapes:
        elements.extend(_render_shape(shape, page_height))

    title = page.name or ""
    header = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'width="%s" height="%s" viewBox="0 0 %s %s" version="1.1">'
        % (
            _format_coord(w_px),
            _format_coord(h_px),
            _format_coord(w_px),
            _format_coord(h_px),
        )
    )
    title_el = "<title>%s</title>" % _xml_escape(title) if title else ""
    body = "".join(elements)
    footer = "</svg>"
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" + header + title_el + body + footer


def write_page_svg(page: "Page", path: str) -> str:
    """Render *page* and write the result to *path* (UTF-8).

    Returns the same string :func:`page_to_svg` would have. The file
    is overwritten if it already exists.
    """
    svg = page_to_svg(page)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(svg)
    return svg


def document_to_svg_all(document: "VisioDocument", directory: str) -> List[str]:
    """Batch-export every page in *document* into *directory*.

    Each page emits a ``page-<index>-<safe-name>.svg`` file at the
    given directory (created if absent). Returns the ordered list of
    written paths so callers can tee the export into a manifest.
    """
    os.makedirs(directory, exist_ok=True)
    written: List[str] = []
    for idx, page in enumerate(document.pages, start=1):
        safe_name = _safe_filename(page.name or "page")
        path = os.path.join(directory, "page-%d-%s.svg" % (idx, safe_name))
        write_page_svg(page, path)
        written.append(path)
    return written


def _safe_filename(name: str) -> str:
    """Return a filesystem-safe rendering of *name*.

    Keeps alphanumerics, dashes, underscores, and dots verbatim;
    collapses every other codepoint to a dash. The result is clamped
    to 64 chars so very long page names don't blow past filesystem
    name limits.
    """
    cleaned = []
    for ch in name:
        if ch.isalnum() or ch in "-_.":
            cleaned.append(ch)
        else:
            cleaned.append("-")
    out = "".join(cleaned).strip("-") or "page"
    return out[:64]


# Internal re-export: keep the public surface at :func:`Page.to_svg` /
# :func:`VisioDocument.to_svg_all`.
__all__ = [
    "document_to_svg_all",
    "page_to_svg",
    "write_page_svg",
]
