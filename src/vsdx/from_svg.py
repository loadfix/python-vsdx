# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""SVG → Visio importer — issue #51.

Public entry points:

* :meth:`vsdx.page.Page.add_svg` — parse an SVG file and append its
  shapes to a page.
* :meth:`vsdx.page.Page.add_svg_string` — same idea, in-memory.
* :func:`add_svg_to_page` / :func:`add_svg_string_to_page` — the
  module-level spellings the page methods delegate to.

Supported SVG element subset
----------------------------

* ``<rect>`` → :class:`~vsdx.shapes.autoshape.Rectangle`.
* ``<circle>`` / ``<ellipse>`` → :class:`~vsdx.shapes.autoshape.Ellipse`.
* ``<line>`` → straight-line custom-geometry shape.
* ``<polyline>`` / ``<polygon>`` → custom-geometry shape with one
  open / closed path.
* ``<path>`` — best-effort: only the ``M`` / ``L`` / ``H`` / ``V`` /
  ``Z`` commands (and their lowercase relative forms) are honoured.
  Curves (``C`` / ``S`` / ``Q`` / ``T``) and elliptical arcs (``A``)
  collapse to straight ``L`` segments to the endpoint — the diagram
  still loads, but the curve is approximated.
* ``<text>`` → master-less text shape with the text content set.
* ``<g>`` → :class:`~vsdx.shapes.group.GroupShape` containing the
  children's shapes. Group-level ``transform="translate(...)"``
  applies to every descendant.
* Common attributes — ``fill``, ``stroke``, ``stroke-width``, and
  ``transform="translate(x,y)"``. ``rotate(...)`` / ``scale(...)`` /
  ``matrix(...)`` are silently ignored in v1.

Coordinate / unit translation
-----------------------------

SVG's user-space origin is top-left and its default unit is the
CSS pixel. Visio's drawing-space origin is bottom-left and its
unit is the inch. We:

1. Resolve every coordinate via :func:`_parse_length` so
   ``"10mm"`` / ``"2cm"`` / ``"1.5in"`` / ``"100px"`` / ``"75pt"``
   all reduce to inches at the issue's specified 72 DPI for ``px``.
2. Determine the SVG canvas height from the root ``<svg>``'s
   ``height`` attribute (falling back to the ``viewBox``'s 4th
   number, then to the page's height).
3. Y-flip every coordinate against the canvas height so a
   top-anchored SVG rectangle lands at the same visual position
   on a Visio page.

Out of scope (documented as future work)
----------------------------------------

* Gradients, filters, masks, ``<clipPath>``, animations, embedded
  raster (``<image>``).
* Bezier / arc curves: ``C`` / ``S`` / ``Q`` / ``T`` / ``A`` path
  commands fall back to straight lines for the v1 importer.
* SVG transform forms beyond ``translate(x,y)``: ``rotate``,
  ``scale``, ``matrix``, ``skewX`` / ``skewY``.
* Text styling — ``font-size`` / ``font-family`` / ``text-anchor``
  attributes are dropped on import. The Visio shape carries the
  text run only.
* CSS via ``<style>`` blocks or external stylesheets — only inline
  ``fill="..."`` / ``stroke="..."`` attributes are honoured.

Security note
-------------

The XML parse uses the stdlib ``xml.etree.ElementTree``. The default
``XMLParser`` does not resolve external entities, so a basic
billion-laughs / XXE attack is blocked at the parser level. Callers
feeding *untrusted* SVG should still pre-filter with
:mod:`defusedxml`.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import (
    TYPE_CHECKING,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from vsdx.page import Page
    from vsdx.shapes.base import Shape


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Conversion factor for SVG ``px`` → inch. The SVG 1.1 spec fixes the
#: CSS pixel at 1/96 inch, but the issue brief asks for 72 DPI so we
#: honour that — at 72 DPI one inch is 72 px.
PX_PER_INCH: float = 72.0

#: SVG namespace URI; both namespaced (``{ns}rect``) and unnamespaced
#: (``rect``) inputs are tolerated when iterating an SVG tree.
SVG_NS: str = "http://www.w3.org/2000/svg"


# ---------------------------------------------------------------------------
# Length parsing
# ---------------------------------------------------------------------------

_LENGTH_RE = re.compile(
    r"""
    ^\s*
    (?P<num>[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
    \s*
    (?P<unit>px|pt|pc|mm|cm|in|em|ex|%)?
    \s*$
    """,
    re.VERBOSE,
)


def _parse_length(raw: Optional[str], default_inches: float = 0.0) -> float:
    """Parse an SVG length string into inches.

    Honours ``px`` (at the configured :data:`PX_PER_INCH`), ``pt``
    (1/72 in), ``pc`` (12 pt), ``mm`` (25.4/in), ``cm``, ``in``. ``em``
    / ``ex`` / ``%`` and unknown units fall back to *default_inches*
    so the import still proceeds — best-effort is the goal.
    """
    if raw is None:
        return default_inches
    if isinstance(raw, (int, float)):
        # CSS pixel default for bare numerics.
        return float(raw) / PX_PER_INCH
    m = _LENGTH_RE.match(str(raw))
    if not m:
        return default_inches
    num = float(m.group("num"))
    unit = (m.group("unit") or "px").lower()
    if unit == "px":
        return num / PX_PER_INCH
    if unit == "pt":
        return num / 72.0
    if unit == "pc":
        return num * 12.0 / 72.0
    if unit == "mm":
        return num / 25.4
    if unit == "cm":
        return num / 2.54
    if unit == "in":
        return num
    # em / ex / % — no font-context here, so degrade to the default.
    return default_inches


# ---------------------------------------------------------------------------
# Color parsing
# ---------------------------------------------------------------------------

# A pragmatic subset of CSS-named colours — enough to cover the common
# SVG vocabulary without bundling the full 147-entry table.
_NAMED_COLORS: Dict[str, str] = {
    "aliceblue": "F0F8FF",
    "aqua": "00FFFF",
    "aquamarine": "7FFFD4",
    "azure": "F0FFFF",
    "beige": "F5F5DC",
    "black": "000000",
    "blue": "0000FF",
    "brown": "A52A2A",
    "coral": "FF7F50",
    "crimson": "DC143C",
    "cyan": "00FFFF",
    "darkblue": "00008B",
    "darkgray": "A9A9A9",
    "darkgreen": "006400",
    "darkgrey": "A9A9A9",
    "darkorange": "FF8C00",
    "darkred": "8B0000",
    "fuchsia": "FF00FF",
    "gold": "FFD700",
    "gray": "808080",
    "green": "008000",
    "grey": "808080",
    "indigo": "4B0082",
    "ivory": "FFFFF0",
    "khaki": "F0E68C",
    "lavender": "E6E6FA",
    "lightblue": "ADD8E6",
    "lightgray": "D3D3D3",
    "lightgreen": "90EE90",
    "lightgrey": "D3D3D3",
    "lime": "00FF00",
    "magenta": "FF00FF",
    "maroon": "800000",
    "navy": "000080",
    "olive": "808000",
    "orange": "FFA500",
    "pink": "FFC0CB",
    "purple": "800080",
    "red": "FF0000",
    "salmon": "FA8072",
    "silver": "C0C0C0",
    "skyblue": "87CEEB",
    "tan": "D2B48C",
    "teal": "008080",
    "tomato": "FF6347",
    "turquoise": "40E0D0",
    "violet": "EE82EE",
    "white": "FFFFFF",
    "yellow": "FFFF00",
    "yellowgreen": "9ACD32",
}

_HEX3_RE = re.compile(r"^#([0-9a-fA-F]{3})$")
_HEX6_RE = re.compile(r"^#([0-9a-fA-F]{6})$")
_RGB_RE = re.compile(
    r"""^\s*rgb\(\s*
        (?P<r>\d{1,3})\s*,\s*
        (?P<g>\d{1,3})\s*,\s*
        (?P<b>\d{1,3})\s*\)\s*$""",
    re.VERBOSE,
)


def _parse_color(raw: Optional[str]) -> Optional[str]:
    """Turn an SVG paint string into a Visio-style ``"#RRGGBB"`` value.

    Returns ``None`` for ``"none"`` / ``"transparent"`` / unrecognised
    input — callers treat ``None`` as "leave the cell at its master
    default" rather than emitting a no-paint cell.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    lower = s.lower()
    if lower in ("none", "transparent"):
        return None
    if lower in _NAMED_COLORS:
        return "#" + _NAMED_COLORS[lower]
    m = _HEX6_RE.match(s)
    if m:
        return "#" + m.group(1).upper()
    m = _HEX3_RE.match(s)
    if m:
        triple = m.group(1)
        return "#" + "".join(c * 2 for c in triple).upper()
    m = _RGB_RE.match(s)
    if m:
        r = max(0, min(255, int(m.group("r"))))
        g = max(0, min(255, int(m.group("g"))))
        b = max(0, min(255, int(m.group("b"))))
        return "#%02X%02X%02X" % (r, g, b)
    return None


# ---------------------------------------------------------------------------
# Transform parsing — ``translate(x,y)`` only in v1.
# ---------------------------------------------------------------------------

_TRANSLATE_RE = re.compile(
    r"translate\s*\(\s*"
    r"(?P<x>[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s*[ ,]\s*(?P<y>[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?))?"
    r"\s*\)"
)


def _parse_translate(raw: Optional[str]) -> Tuple[float, float]:
    """Pull the first ``translate(x, y)`` out of a transform string.

    Returns ``(0, 0)`` when no translate is present, or when the input
    is ``None``. Other transform forms (rotate / scale / matrix) are
    silently ignored — the issue brief treats them as out of scope.

    The returned ``(x, y)`` is in the SVG user-space (px) — the caller
    converts to inches.
    """
    if not raw:
        return (0.0, 0.0)
    m = _TRANSLATE_RE.search(raw)
    if not m:
        return (0.0, 0.0)
    x = float(m.group("x"))
    y = float(m.group("y") or 0.0)
    return (x, y)


# ---------------------------------------------------------------------------
# Path-data tokeniser ('M 10 10 L 20 20 Z' → command stream)
# ---------------------------------------------------------------------------

_PATH_CMD_RE = re.compile(r"[MmLlHhVvZzCcSsQqTtAa]")
_PATH_NUM_RE = re.compile(
    r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?"
)


def _tokenize_path(d: str) -> List[Tuple[str, List[float]]]:
    """Tokenise an SVG ``d`` attribute into ``(command, [args])`` pairs.

    Args lists carry the *raw* numbers — argument-count grouping is the
    caller's responsibility. Unknown commands are tolerated by being
    skipped (the iterator advances past them so a malformed run does
    not block the rest of the path).
    """
    out: List[Tuple[str, List[float]]] = []
    if not d:
        return out
    i = 0
    n = len(d)
    while i < n:
        ch = d[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        if _PATH_CMD_RE.match(ch):
            cmd = ch
            i += 1
            args: List[float] = []
            while i < n:
                # Skip whitespace / commas between numbers.
                while i < n and (d[i].isspace() or d[i] == ","):
                    i += 1
                if i >= n or _PATH_CMD_RE.match(d[i]):
                    break
                m = _PATH_NUM_RE.match(d, i)
                if not m:
                    break
                args.append(float(m.group(0)))
                i = m.end()
            out.append((cmd, args))
        else:
            # Stray character — advance and keep looking.
            i += 1
    return out


def _path_to_segments(d: str) -> List[List[Tuple[float, float]]]:
    """Walk a tokenised path and return one polyline per ``M``-subpath.

    Curve commands (``C`` / ``S`` / ``Q`` / ``T`` / ``A``) collapse to
    straight lines from the current point to the *endpoint* of the
    curve — the issue brief explicitly accepts this lossy fallback.

    Each returned subpath is a list of ``(x, y)`` user-space points,
    where the first point is the subpath origin (the most recent
    ``M``) and a final repeated point is appended when the subpath
    ends with ``Z`` so callers can detect closure with a simple
    ``points[0] == points[-1]`` check.
    """
    segments: List[List[Tuple[float, float]]] = []
    cx = 0.0
    cy = 0.0
    sx = 0.0  # subpath start (target of Z)
    sy = 0.0
    current: Optional[List[Tuple[float, float]]] = None

    def _start_subpath(x: float, y: float) -> List[Tuple[float, float]]:
        seg: List[Tuple[float, float]] = [(x, y)]
        segments.append(seg)
        return seg

    for cmd, args in _tokenize_path(d):
        upper = cmd.upper()
        rel = cmd.islower()
        if upper == "M":
            # First pair is moveto; subsequent pairs are implicit linetos.
            if len(args) < 2:
                continue
            x = args[0] + (cx if rel else 0.0)
            y = args[1] + (cy if rel else 0.0)
            current = _start_subpath(x, y)
            cx, cy = x, y
            sx, sy = x, y
            for k in range(2, len(args) - 1, 2):
                lx = args[k] + (cx if rel else 0.0)
                ly = args[k + 1] + (cy if rel else 0.0)
                current.append((lx, ly))
                cx, cy = lx, ly
        elif upper == "L":
            if current is None:
                current = _start_subpath(cx, cy)
            for k in range(0, len(args) - 1, 2):
                lx = args[k] + (cx if rel else 0.0)
                ly = args[k + 1] + (cy if rel else 0.0)
                current.append((lx, ly))
                cx, cy = lx, ly
        elif upper == "H":
            if current is None:
                current = _start_subpath(cx, cy)
            for k in range(0, len(args)):
                lx = args[k] + (cx if rel else 0.0)
                current.append((lx, cy))
                cx = lx
        elif upper == "V":
            if current is None:
                current = _start_subpath(cx, cy)
            for k in range(0, len(args)):
                ly = args[k] + (cy if rel else 0.0)
                current.append((cx, ly))
                cy = ly
        elif upper == "Z":
            if current is not None:
                current.append((sx, sy))
                cx, cy = sx, sy
                # A subsequent command with no preceding M starts a
                # new subpath at the close point.
                current = None
        elif upper in ("C", "S", "Q", "T"):
            # Cubic / smooth-cubic / quadratic / smooth-quadratic.
            # Lossy fallback: jump to the endpoint of each segment in
            # the run (the last 2 numbers of each chunk).
            if current is None:
                current = _start_subpath(cx, cy)
            chunk = {"C": 6, "S": 4, "Q": 4, "T": 2}[upper]
            for k in range(0, len(args) - chunk + 1, chunk):
                ex = args[k + chunk - 2] + (cx if rel else 0.0)
                ey = args[k + chunk - 1] + (cy if rel else 0.0)
                current.append((ex, ey))
                cx, cy = ex, ey
        elif upper == "A":
            # Elliptical arc — 7 numbers (rx ry x-axis-rot large sweep
            # ex ey). Lossy fallback: jump to the endpoint.
            if current is None:
                current = _start_subpath(cx, cy)
            for k in range(0, len(args) - 6, 7):
                ex = args[k + 5] + (cx if rel else 0.0)
                ey = args[k + 6] + (cy if rel else 0.0)
                current.append((ex, ey))
                cx, cy = ex, ey
        # Unknown commands silently skipped.
    return segments


# ---------------------------------------------------------------------------
# Polyline-attribute parsing
# ---------------------------------------------------------------------------

_POINTS_NUM_RE = re.compile(
    r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?"
)


def _parse_points(raw: Optional[str]) -> List[Tuple[float, float]]:
    """Parse an SVG ``points`` attribute into a list of ``(x, y)`` tuples.

    Tolerates both ``"x,y x,y"`` and ``"x y x y"`` separator forms. An
    odd-length number list drops the trailing orphan number.
    """
    if not raw:
        return []
    nums = [float(n) for n in _POINTS_NUM_RE.findall(raw)]
    out: List[Tuple[float, float]] = []
    for i in range(0, len(nums) - 1, 2):
        out.append((nums[i], nums[i + 1]))
    return out


# ---------------------------------------------------------------------------
# Element-name helpers — accept namespaced or bare tags.
# ---------------------------------------------------------------------------


def _local_name(tag: str) -> str:
    """Return the local-name part of an ElementTree tag (drop namespace)."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


# ---------------------------------------------------------------------------
# Importer — orchestrates the SVG element walk → vsdx shape authoring.
# ---------------------------------------------------------------------------


class _SvgImporter:
    """Stateful walker that turns an SVG tree into vsdx shapes.

    All shapes are authored at top level on :attr:`_page`'s shape
    tree first; ``<g>`` groups are then aggregated into Visio
    :class:`~vsdx.shapes.group.GroupShape` instances via
    :meth:`vsdx.shapes.shapetree.ShapeTree.group` once their
    descendants finish authoring. This avoids the API mismatch
    between top-level and nested shape-tree authoring (e.g. nested
    ``GroupMembers`` only exposes ``add_shape``, not the custom
    geometry hooks the polyline / path / line / text branches need).
    """

    def __init__(self, page: "Page", svg_root: ET.Element):
        self._page = page
        self._root = svg_root
        # Resolve the SVG canvas height once — every Y-flip needs it.
        self._canvas_height_in = self._resolve_canvas_height()
        self._created: List["Shape"] = []

    # -- canvas / unit resolution --------------------------------------

    def _resolve_canvas_height(self) -> float:
        """Pin down the SVG canvas height in inches.

        Priority: the ``height`` attribute → the ``viewBox``'s 4th
        number → the page's height. We default to the page so a
        height-less SVG still imports without weird negative offsets.
        """
        h_attr = self._root.get("height")
        if h_attr:
            return _parse_length(h_attr, default_inches=float(self._page.height))
        viewbox = self._root.get("viewBox")
        if viewbox:
            parts = [p for p in re.split(r"[ ,]+", viewbox.strip()) if p]
            if len(parts) >= 4:
                # viewBox is unitless user coords → treat as px.
                try:
                    return float(parts[3]) / PX_PER_INCH
                except ValueError:
                    pass
        return float(self._page.height)

    # -- coord helpers --------------------------------------------------

    def _to_inches(self, value: float) -> float:
        """User-space coord (px) → inches at the configured DPI."""
        return value / PX_PER_INCH

    def _flip_y(self, y_in: float) -> float:
        """SVG-top-down Y → Visio-bottom-up Y."""
        return self._canvas_height_in - y_in

    # -- entry point ----------------------------------------------------

    def run(self) -> List["Shape"]:
        """Walk every direct child of the SVG root and return the shapes."""
        for child in list(self._root):
            self._handle(child, parent_translate=(0.0, 0.0))
        return self._created

    # -- element dispatch -----------------------------------------------

    def _handle(
        self,
        el: ET.Element,
        parent_translate: Tuple[float, float],
    ) -> Optional["Shape"]:
        local = _local_name(el.tag)
        # Compose the translate stack once per element — every shape in
        # this call sees the cumulative offset.
        tx, ty = _parse_translate(el.get("transform"))
        cum_tx = parent_translate[0] + tx
        cum_ty = parent_translate[1] + ty

        if local == "rect":
            return self._handle_rect(el, (cum_tx, cum_ty))
        if local == "circle":
            return self._handle_circle(el, (cum_tx, cum_ty))
        if local == "ellipse":
            return self._handle_ellipse(el, (cum_tx, cum_ty))
        if local == "line":
            return self._handle_line(el, (cum_tx, cum_ty))
        if local in ("polyline", "polygon"):
            return self._handle_polyline(
                el, (cum_tx, cum_ty), closed=(local == "polygon")
            )
        if local == "path":
            self._handle_path(el, (cum_tx, cum_ty))
            return None  # paths can yield 0..N shapes; caller doesn't track each
        if local == "text":
            return self._handle_text(el, (cum_tx, cum_ty))
        if local == "g":
            return self._handle_group(el, (cum_tx, cum_ty))
        # Other elements (defs, style, title, desc, metadata, image,
        # use, …) are silently skipped — best-effort import.
        return None

    # -- per-element handlers ------------------------------------------

    def _handle_rect(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> Optional["Shape"]:
        x_in = self._to_inches(_user_float(el, "x", 0.0) + translate[0])
        y_in = self._to_inches(_user_float(el, "y", 0.0) + translate[1])
        w_in = self._to_inches(_user_float(el, "width", 0.0))
        h_in = self._to_inches(_user_float(el, "height", 0.0))
        if w_in <= 0 or h_in <= 0:
            return None
        pin_x = x_in + w_in / 2.0
        pin_y = self._flip_y(y_in + h_in / 2.0)
        shape = self._page.shapes.add_shape(
            "Rectangle", at=(pin_x, pin_y), size=(w_in, h_in)
        )
        _apply_paint(shape, el)
        self._created.append(shape)
        return shape

    def _handle_circle(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> Optional["Shape"]:
        cx_in = self._to_inches(_user_float(el, "cx", 0.0) + translate[0])
        cy_in = self._to_inches(_user_float(el, "cy", 0.0) + translate[1])
        r_in = self._to_inches(_user_float(el, "r", 0.0))
        if r_in <= 0:
            return None
        diameter = 2.0 * r_in
        pin_x = cx_in
        pin_y = self._flip_y(cy_in)
        shape = self._page.shapes.add_shape(
            "Ellipse", at=(pin_x, pin_y), size=(diameter, diameter)
        )
        _apply_paint(shape, el)
        self._created.append(shape)
        return shape

    def _handle_ellipse(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> Optional["Shape"]:
        cx_in = self._to_inches(_user_float(el, "cx", 0.0) + translate[0])
        cy_in = self._to_inches(_user_float(el, "cy", 0.0) + translate[1])
        rx_in = self._to_inches(_user_float(el, "rx", 0.0))
        ry_in = self._to_inches(_user_float(el, "ry", 0.0))
        if rx_in <= 0 or ry_in <= 0:
            return None
        pin_x = cx_in
        pin_y = self._flip_y(cy_in)
        shape = self._page.shapes.add_shape(
            "Ellipse",
            at=(pin_x, pin_y),
            size=(2.0 * rx_in, 2.0 * ry_in),
        )
        _apply_paint(shape, el)
        self._created.append(shape)
        return shape

    def _handle_line(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> Optional["Shape"]:
        x1_in = self._to_inches(_user_float(el, "x1", 0.0) + translate[0])
        y1_in = self._to_inches(_user_float(el, "y1", 0.0) + translate[1])
        x2_in = self._to_inches(_user_float(el, "x2", 0.0) + translate[0])
        y2_in = self._to_inches(_user_float(el, "y2", 0.0) + translate[1])
        # Free-floating two-point polyline — Visio renders it as the
        # straight line we want; the user can later glue / route as
        # needed.
        return self._author_polyline_shape(
            [(x1_in, y1_in), (x2_in, y2_in)],
            closed=False,
            el=el,
            stroke_only=True,
        )

    def _handle_polyline(
        self,
        el: ET.Element,
        translate: Tuple[float, float],
        closed: bool,
    ) -> Optional["Shape"]:
        raw_points = _parse_points(el.get("points"))
        if len(raw_points) < 2:
            return None
        points_in = [
            (
                self._to_inches(px + translate[0]),
                self._to_inches(py + translate[1]),
            )
            for (px, py) in raw_points
        ]
        return self._author_polyline_shape(
            points_in,
            closed=closed,
            el=el,
            stroke_only=not closed,
        )

    def _handle_path(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> List["Shape"]:
        d = el.get("d") or ""
        subpaths = _path_to_segments(d)
        out: List["Shape"] = []
        for seg in subpaths:
            if len(seg) < 2:
                continue
            seg_in = [
                (
                    self._to_inches(px + translate[0]),
                    self._to_inches(py + translate[1]),
                )
                for (px, py) in seg
            ]
            closed = seg_in[0] == seg_in[-1] and len(seg_in) > 2
            # When closed, the duplicated end point is implicit in the
            # close() call — strip it so we don't author a zero-length
            # final LineTo.
            if closed:
                seg_in = seg_in[:-1]
            shape = self._author_polyline_shape(
                seg_in,
                closed=closed,
                el=el,
                stroke_only=not closed,
            )
            if shape is not None:
                out.append(shape)
        return out

    def _handle_text(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> Optional["Shape"]:
        # Concatenate every text node — including tspan children —
        # so multi-run labels round-trip as a single Visio text run.
        text = "".join(el.itertext()) if list(el) else (el.text or "")
        text = text.strip()
        if not text:
            return None
        x_in = self._to_inches(_user_float(el, "x", 0.0) + translate[0])
        y_in = self._to_inches(_user_float(el, "y", 0.0) + translate[1])
        shape = self._page.shapes.add_custom_shape(
            at=(x_in, self._flip_y(y_in)),
            size=(_estimate_text_width(text), 0.25),
        )
        shape.text = text
        _apply_paint(shape, el)
        self._created.append(shape)
        return shape

    def _handle_group(
        self, el: ET.Element, translate: Tuple[float, float]
    ) -> Optional["Shape"]:
        # Author every descendant at top level first, then aggregate
        # via :meth:`ShapeTree.group` so the group ends up with the
        # right bounding box. Members are tracked via the per-call
        # snapshot so we don't fold sibling shapes into the wrong
        # group when handlers append to ``self._created``.
        member_shapes: List["Shape"] = []
        for child in list(el):
            before_len = len(self._created)
            self._handle(child, translate)
            # New top-level shapes added by the child handler — track
            # them as members of *this* group.
            for s in self._created[before_len:]:
                member_shapes.append(s)

        if not member_shapes:
            return None
        # ShapeTree.group reparents the members into the group's
        # nested <Shapes> and rewrites their pin coordinates to
        # group-local. The group is appended to the page tree;
        # its bounding box is derived from members, so no explicit
        # at/size kwargs needed.
        try:
            group = self._page.shapes.group(member_shapes)
        except Exception:  # noqa: BLE001 -- broken member is survivable
            return None

        # Replace the member entries in :attr:`_created` with the
        # group itself so the public return-list reflects the
        # post-grouping topology.  Any path / sibling shapes that
        # were authored before this group call survive intact.
        new_created: List["Shape"] = []
        members_set = {id(s) for s in member_shapes}
        replaced = False
        for s in self._created:
            if id(s) in members_set:
                if not replaced:
                    new_created.append(group)
                    replaced = True
                # else: skip — the member has been absorbed into
                # ``group`` already.
            else:
                new_created.append(s)
        self._created = new_created
        return group

    # -- shared polyline authoring -------------------------------------

    def _author_polyline_shape(
        self,
        points_in: Sequence[Tuple[float, float]],
        closed: bool,
        el: ET.Element,
        stroke_only: bool,
    ) -> Optional["Shape"]:
        """Drop a custom-geometry shape covering *points_in* on the page."""
        if len(points_in) < 2:
            return None
        xs = [p[0] for p in points_in]
        ys = [p[1] for p in points_in]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        w = max(max_x - min_x, 1.0 / PX_PER_INCH)  # 1 px floor
        h = max(max_y - min_y, 1.0 / PX_PER_INCH)
        pin_x = min_x + w / 2.0
        pin_y_visio = self._flip_y(min_y + h / 2.0)
        shape = self._page.shapes.add_custom_shape(
            at=(pin_x, pin_y_visio), size=(w, h)
        )
        # Translate user-space points to shape-local coords. Visio's
        # geometry section uses bottom-left = (0, 0); we already have
        # an SVG-top-down listing so the Y flip is height - (y - min_y).
        local_pts = [
            ((px - min_x), h - (py - min_y))
            for (px, py) in points_in
        ]
        geo = shape.geometries[0]
        first_x, first_y = local_pts[0]
        geo.move_to(first_x, first_y)
        for (lx, ly) in local_pts[1:]:
            geo.line_to(lx, ly)
        if closed:
            geo.close()
        _apply_paint(shape, el, stroke_only=stroke_only)
        self._created.append(shape)
        return shape


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------


def _user_float(el: ET.Element, name: str, default: float) -> float:
    """Return *el*'s attribute parsed as a px-space float (no unit conv)."""
    raw = el.get(name)
    if raw is None or raw == "":
        return default
    m = _LENGTH_RE.match(str(raw))
    if not m:
        return default
    num = float(m.group("num"))
    unit = (m.group("unit") or "px").lower()
    # Most SVG element attributes carry user-space numbers; if the
    # caller supplied an in/cm/mm form we convert to px so the importer
    # can apply :data:`PX_PER_INCH` once at the very end.
    if unit == "px":
        return num
    if unit == "pt":
        return num * (PX_PER_INCH / 72.0)
    if unit == "pc":
        return num * 12.0 * (PX_PER_INCH / 72.0)
    if unit == "mm":
        return num * (PX_PER_INCH / 25.4)
    if unit == "cm":
        return num * (PX_PER_INCH / 2.54)
    if unit == "in":
        return num * PX_PER_INCH
    return num


def _apply_paint(
    shape: "Shape", el: ET.Element, stroke_only: bool = False
) -> None:
    """Copy ``fill`` / ``stroke`` / ``stroke-width`` to the Visio shape.

    *stroke_only* (used for ``<line>`` / open ``<polyline>`` /
    ``<path>`` runs) suppresses the fill so callers don't end up with
    an unwanted painted region behind a logical line.
    """
    fill = _parse_color(el.get("fill"))
    stroke = _parse_color(el.get("stroke"))
    if fill is not None and not stroke_only:
        shape.fill_foregnd = fill
    if stroke is not None:
        shape.line_color = stroke
    sw = el.get("stroke-width")
    if sw is not None:
        m = _LENGTH_RE.match(sw)
        if m is None:
            return
        try:
            sw_px = float(m.group("num"))
        except ValueError:
            return
        # Convert px → points (1 pt = 1/72 in; px = 1/72 in at our DPI).
        shape.line_weight = sw_px * (72.0 / PX_PER_INCH)


def _estimate_text_width(text: str) -> float:
    """Rough text-shape width (inches) for an *N*-character label.

    The importer only needs an "envelope" big enough that Visio's
    auto-fit kicks in on first open. 0.08-inch-per-character at 12 pt
    is a crude but workable estimate.
    """
    return max(0.5, 0.08 * len(text))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _parse_svg_text(text: str) -> ET.Element:
    """Parse an SVG document string and return its root element.

    Uses the stdlib :class:`xml.etree.ElementTree.XMLParser` with its
    default settings — no external entities are resolved, so the basic
    XXE / billion-laughs vector is blocked. Callers handling untrusted
    input should still pre-filter with :mod:`defusedxml`.
    """
    return ET.fromstring(text)


def add_svg_to_page(
    page: "Page", path: Union[str, "os.PathLike[str]"]
) -> List["Shape"]:
    """Read *path* and append the parsed SVG's shapes to *page*.

    Returns the list of top-level :class:`~vsdx.shapes.base.Shape`
    instances created — children of imported groups are not in this
    list (they are reachable via the group's
    :attr:`~vsdx.shapes.group.GroupShape.shapes` collection).

    .. versionadded:: 0.4.0
    """
    with open(os.fspath(path), "rb") as fp:
        data = fp.read()
    text = data.decode("utf-8")
    return add_svg_string_to_page(page, text)


def add_svg_string_to_page(page: "Page", text: str) -> List["Shape"]:
    """Parse *text* (SVG source) and append the resulting shapes to *page*.

    See :func:`add_svg_to_page` for the return-shape contract.

    .. versionadded:: 0.4.0
    """
    root = _parse_svg_text(text)
    if _local_name(root.tag) != "svg":
        raise ValueError(
            "expected an <svg> root element, got <%s>" % _local_name(root.tag)
        )
    importer = _SvgImporter(page, root)
    return importer.run()


__all__ = [
    "PX_PER_INCH",
    "SVG_NS",
    "add_svg_string_to_page",
    "add_svg_to_page",
]
