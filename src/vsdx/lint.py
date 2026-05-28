"""Diagram-quality lint for python-vsdx.

Eight structural rules — overlap, disconnected nodes, unlabeled
connectors, line crossings, inconsistent sizing, off-grid pins, text
overflow, label readability. Driver is :func:`lint`, exposed on
:meth:`vsdx.page.Page.lint`. CLI: ``python -m vsdx lint <path>``.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, List, Optional

if TYPE_CHECKING:
    from vsdx.page import Page
    from vsdx.shapes.base import Shape
    from vsdx.shapes.connector import Connector


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

#: Default rule-id allowlist applied when ``rules`` is omitted.
DEFAULT_RULES: tuple[str, ...] = (
    "shape-overlap",
    "disconnected-node",
    "unlabeled-connector",
    "connector-crossings",
    "inconsistent-shape-size",
    "off-grid",
    "text-overflow",
    "label-readability",
)


@dataclass(frozen=True)
class Finding:
    """One lint result.

    *target* is the offending :class:`~vsdx.shapes.base.Shape` (or
    :class:`~vsdx.shapes.connector.Connector`), or ``None`` for
    page-level findings (e.g. a connector-crossings count).
    """

    rule_id: str
    severity: str
    message: str
    target: "Optional[Shape]" = None

    def __str__(self) -> str:
        target_id = (
            getattr(self.target, "shape_id", None) if self.target is not None else None
        )
        prefix = "[%s] %s" % (self.severity, self.rule_id)
        if target_id is not None:
            return "%s shape %s: %s" % (prefix, target_id, self.message)
        return "%s: %s" % (prefix, self.message)


def lint(
    page: "Page",
    rules: "Optional[Iterable[str]]" = None,
) -> List[Finding]:
    """Lint *page* and return a list of :class:`Finding` instances.

    *rules* is an optional iterable of rule-ids; ``None`` runs the full
    :data:`DEFAULT_RULES` set. Unknown rule-ids are silently skipped so
    callers stay forward-compatible with rule names from a future
    package version.

    .. versionadded:: 0.3.0
    """
    selected = set(rules) if rules is not None else set(DEFAULT_RULES)
    findings: List[Finding] = []
    if "shape-overlap" in selected:
        findings.extend(_check_shape_overlap(page))
    if "disconnected-node" in selected:
        findings.extend(_check_disconnected_nodes(page))
    if "unlabeled-connector" in selected:
        findings.extend(_check_unlabeled_connectors(page))
    if "connector-crossings" in selected:
        findings.extend(_check_connector_crossings(page))
    if "inconsistent-shape-size" in selected:
        findings.extend(_check_inconsistent_shape_size(page))
    if "off-grid" in selected:
        findings.extend(_check_off_grid(page))
    if "text-overflow" in selected:
        findings.extend(_check_text_overflow(page))
    if "label-readability" in selected:
        findings.extend(_check_label_readability(page))
    return findings


# -- shared helpers ----------------------------------------------------------


def _bbox(shape: "Shape") -> Optional[tuple[float, float, float, float]]:
    """Return ``(left, bottom, right, top)`` in inches, or ``None`` when
    the shape carries no positive dimensions. Pin assumed centred —
    matches :func:`vsdx.shapes.connector._shape_bbox`."""
    try:
        w = float(shape.width) or 0.0
        h = float(shape.height) or 0.0
        px = float(shape.pin_x) or 0.0
        py = float(shape.pin_y) or 0.0
    except (TypeError, ValueError):
        return None
    if w <= 0.0 or h <= 0.0:
        return None
    return px - w / 2.0, py - h / 2.0, px + w / 2.0, py + h / 2.0


def _is_connector(shape: "Shape") -> bool:
    from vsdx.shapes.connector import Connector

    return isinstance(shape, Connector)


def _non_connectors(page: "Page") -> List["Shape"]:
    return [s for s in page.shapes if not _is_connector(s)]


def _connectors(page: "Page") -> List["Connector"]:
    return [s for s in page.shapes if _is_connector(s)]  # type: ignore[misc]


# -- rule: shape-overlap -----------------------------------------------------


def _check_shape_overlap(page: "Page") -> List[Finding]:
    findings: List[Finding] = []
    boxes = [(s, _bbox(s)) for s in _non_connectors(page)]
    for i, (a, ab) in enumerate(boxes):
        if ab is None:
            continue
        a_area = (ab[2] - ab[0]) * (ab[3] - ab[1])
        if a_area <= 0.0:
            continue
        for b, bb in boxes[i + 1 :]:
            if bb is None:
                continue
            ix = max(0.0, min(ab[2], bb[2]) - max(ab[0], bb[0]))
            iy = max(0.0, min(ab[3], bb[3]) - max(ab[1], bb[1]))
            inter = ix * iy
            if inter <= 0.0:
                continue
            b_area = (bb[2] - bb[0]) * (bb[3] - bb[1])
            smaller = min(a_area, b_area)
            if smaller <= 0.0:
                continue
            ratio = inter / smaller
            if ratio > 0.05:
                findings.append(
                    Finding(
                        rule_id="shape-overlap",
                        severity=SEVERITY_ERROR,
                        message=(
                            "shape %d overlaps shape %d by %.1f%% of the smaller shape"
                            % (a.shape_id, b.shape_id, ratio * 100.0)
                        ),
                        target=a,
                    )
                )
    return findings


# -- rule: disconnected-node -------------------------------------------------


def _check_disconnected_nodes(page: "Page") -> List[Finding]:
    findings: List[Finding] = []
    for shape in _non_connectors(page):
        try:
            if not shape.connections_in and not shape.connections_out:
                findings.append(
                    Finding(
                        rule_id="disconnected-node",
                        severity=SEVERITY_WARNING,
                        message="shape has no incoming or outgoing connectors",
                        target=shape,
                    )
                )
        except Exception:  # noqa: BLE001 — accessor failures shouldn't crash lint
            continue
    return findings


# -- rule: unlabeled-connector -----------------------------------------------


def _check_unlabeled_connectors(page: "Page") -> List[Finding]:
    findings: List[Finding] = []
    for conn in _connectors(page):
        try:
            text = conn.text or ""
        except Exception:  # noqa: BLE001
            text = ""
        if not text.strip():
            findings.append(
                Finding(
                    rule_id="unlabeled-connector",
                    severity=SEVERITY_WARNING,
                    message="connector has no label text",
                    target=conn,
                )
            )
    return findings


# -- rule: connector-crossings -----------------------------------------------

#: Threshold (matches the audit doc's "5+ crossings reads as noisy" rule).
_CROSSING_THRESHOLD = 5


def _segment(conn: "Connector") -> Optional[tuple[float, float, float, float]]:
    bx, by, ex, ey = conn.begin_x, conn.begin_y, conn.end_x, conn.end_y
    if None in (bx, by, ex, ey):
        return None
    return float(bx), float(by), float(ex), float(ey)


def _segments_cross(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    """``True`` when *a* and *b* properly cross (endpoint-touching is
    treated as no-cross — connectors fanning out of a shared anchor
    must not all flag each other)."""

    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    def _orient(px: float, py: float, qx: float, qy: float, rx: float, ry: float) -> float:
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    o1 = _orient(ax1, ay1, ax2, ay2, bx1, by1)
    o2 = _orient(ax1, ay1, ax2, ay2, bx2, by2)
    o3 = _orient(bx1, by1, bx2, by2, ax1, ay1)
    o4 = _orient(bx1, by1, bx2, by2, ax2, ay2)
    return (
        (o1 > 0 and o2 < 0 or o1 < 0 and o2 > 0)
        and (o3 > 0 and o4 < 0 or o3 < 0 and o4 > 0)
    )


def _check_connector_crossings(page: "Page") -> List[Finding]:
    segments = [s for s in (_segment(c) for c in _connectors(page)) if s is not None]
    crossings = sum(
        1
        for i in range(len(segments))
        for j in range(i + 1, len(segments))
        if _segments_cross(segments[i], segments[j])
    )
    if crossings >= _CROSSING_THRESHOLD:
        return [
            Finding(
                rule_id="connector-crossings",
                severity=SEVERITY_INFO,
                message="%d connector crossings detected (threshold %d)"
                % (crossings, _CROSSING_THRESHOLD),
            )
        ]
    return []


# -- rule: inconsistent-shape-size -------------------------------------------


def _shape_kind(shape: "Shape") -> str:
    """Bucket key for the size-consistency rule. Master NameU when
    present (every autoshape carries one); else the ``Type`` attribute."""

    master = getattr(shape, "master_name_u", None)
    if master:
        return "master:%s" % master
    return "type:%s" % (getattr(shape, "shape_type", None) or "?")


def _check_inconsistent_shape_size(page: "Page") -> List[Finding]:
    findings: List[Finding] = []
    buckets: dict[str, list[tuple["Shape", float]]] = {}
    for shape in _non_connectors(page):
        try:
            area = float(shape.width) * float(shape.height)
        except (TypeError, ValueError):
            continue
        if area <= 0.0:
            continue
        buckets.setdefault(_shape_kind(shape), []).append((shape, area))
    for kind, members in buckets.items():
        if len(members) < 2:
            continue
        areas = [a for _, a in members]
        if min(areas) <= 0.0:
            continue
        ratio = max(areas) / min(areas)
        if ratio > 2.0:
            largest = max(members, key=lambda m: m[1])[0]
            findings.append(
                Finding(
                    rule_id="inconsistent-shape-size",
                    severity=SEVERITY_WARNING,
                    message=(
                        "%s area varies %.1fx across %d shapes (max/min)"
                        % (kind, ratio, len(members))
                    ),
                    target=largest,
                )
            )
    return findings


# -- rule: off-grid ----------------------------------------------------------


def _grid_spacing(page: "Page") -> Optional[float]:
    """The page's grid spacing, in inches, or ``None`` when no grid is
    set. Reads ``XGridSpacing`` / ``YGridSpacing`` from the PageSheet;
    when the two axes disagree, the smaller wins so both axes still snap."""

    candidates: list[float] = []
    for raw in (page._sheet_cell_v("XGridSpacing"), page._sheet_cell_v("YGridSpacing")):
        if raw is None:
            continue
        try:
            v = float(raw)
        except ValueError:
            continue
        if v > 0.0:
            candidates.append(v)
    return min(candidates) if candidates else None


def _check_off_grid(page: "Page") -> List[Finding]:
    spacing = _grid_spacing(page)
    if spacing is None or spacing <= 0.0:
        return []
    findings: List[Finding] = []
    tol = spacing * 0.01  # 1 % of grid step — well below floating-point noise
    for shape in _non_connectors(page):
        try:
            px, py = float(shape.pin_x), float(shape.pin_y)
        except (TypeError, ValueError):
            continue
        rx, ry = px / spacing, py / spacing
        if abs(rx - round(rx)) * spacing > tol or abs(ry - round(ry)) * spacing > tol:
            findings.append(
                Finding(
                    rule_id="off-grid",
                    severity=SEVERITY_INFO,
                    message="pin (%g, %g) not aligned to %g-inch grid" % (px, py, spacing),
                    target=shape,
                )
            )
    return findings


# -- rule: text-overflow -----------------------------------------------------

#: Heuristic glyph metrics — the lint runs at the oxml layer with no
#: font engine, so we approximate Visio's auto-fit budget for 10-pt body
#: text (≈0.07 in / char, ≈0.16 in line-height).
_AVG_CHAR_WIDTH_IN = 0.07
_AVG_LINE_HEIGHT_IN = 0.16


def _check_text_overflow(page: "Page") -> List[Finding]:
    findings: List[Finding] = []
    for shape in _non_connectors(page):
        try:
            text = getattr(shape, "text", "") or ""
        except Exception:  # noqa: BLE001
            text = ""
        if not text.strip():
            continue
        try:
            w, h = float(shape.width) or 0.0, float(shape.height) or 0.0
        except (TypeError, ValueError):
            continue
        if w <= 0.0 or h <= 0.0:
            continue
        chars_per_line = max(1, int(w / _AVG_CHAR_WIDTH_IN))
        wrapped = sum(
            max(1, -(-len(line) // chars_per_line))
            for line in (text.splitlines() or [text])
        )
        needed_height = wrapped * _AVG_LINE_HEIGHT_IN
        if needed_height > h * 1.05:  # 5 % slack to dodge rounding
            findings.append(
                Finding(
                    rule_id="text-overflow",
                    severity=SEVERITY_WARNING,
                    message="text needs ~%.2f-in vs %.2f-in shape height"
                    % (needed_height, h),
                    target=shape,
                )
            )
    return findings


# -- rule: label-readability -------------------------------------------------

#: Visio's accessibility floor for body text.
_MIN_READABLE_POINTS = 8.0


def _label_point_size(shape: "Shape") -> Optional[float]:
    """First ``<Cell N="Size">`` from a Char section, in points, or
    ``None`` when no size cell is set. ``@U="PT"`` is honoured; unit-
    less values are inches and converted at 72 pt / inch."""

    for section in getattr(shape._element, "section_lst", []):
        if section.get("N") != "Character":
            continue
        for row in section.row_lst:
            for cell in row.cell_lst:
                if cell.get("N") != "Size":
                    continue
                v = cell.get("V")
                if not v:
                    continue
                try:
                    raw = float(v)
                except ValueError:
                    continue
                u = (cell.get("U") or "").upper()
                return raw if u == "PT" else raw * 72.0
    return None


def _check_label_readability(page: "Page") -> List[Finding]:
    findings: List[Finding] = []
    for shape in page.shapes:
        try:
            text = getattr(shape, "text", "") or ""
        except Exception:  # noqa: BLE001
            text = ""
        if not text.strip():
            continue
        size = _label_point_size(shape)
        if size is not None and size < _MIN_READABLE_POINTS:
            findings.append(
                Finding(
                    rule_id="label-readability",
                    severity=SEVERITY_INFO,
                    message="label is %.1fpt (below %.1fpt readability floor)"
                    % (size, _MIN_READABLE_POINTS),
                    target=shape,
                )
            )
    return findings


__all__ = [
    "DEFAULT_RULES",
    "Finding",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "lint",
]
