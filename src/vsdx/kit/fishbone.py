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
"""Fishbone (Ishikawa) diagram template — issue #129.

Build a cause-and-effect "fishbone" (Ishikawa) diagram from a plain-
Python description::

    from vsdx.kit.fishbone import build_fishbone

    diagram = build_fishbone(
        problem='Customer churn higher than target',
        categories={
            'People':      ['Insufficient training', 'Turnover in CS team'],
            'Process':     ['Slow ticket triage', 'Manual onboarding'],
            'Product':     ['Confusing pricing page', 'Missing dashboards'],
            'Technology':  ['API errors during peak', 'Outdated docs'],
            'Environment': ['Recession headwinds'],
            'Measurement': ['NPS sample too small'],
        },
    )
    diagram.save('churn-fishbone.vsdx')

Layout
------

The classical Ishikawa layout is a horizontal "spine" running the
length of the page with the **problem statement** boxed at the right
end (the head of the fish). Cause categories branch off the spine at
**60°** alternating between the top and bottom of the spine; sub-
causes hang off each category branch as **short parallel** lines
labelled with the sub-cause text. The result reads left-to-right and
top-to-bottom like the skeleton of a fish — hence the colloquial
name.

* Page is landscape (default 14" x 8.5") with a title band at the top.
* Spine runs horizontally at the vertical mid-point of the body.
* Problem-statement rectangle is anchored at the right edge.
* Categories are distributed left-to-right along the spine; the order
  of the *categories* mapping is preserved (Python 3.7+ dict-insertion
  order). Categories alternate top / bottom — the first category goes
  above the spine, the second below, the third above, and so on.
* Each category branch is a diagonal line from its joint on the spine
  up (or down) to a category-label rectangle at the branch's outer
  end.
* Sub-causes are short horizontal line segments, parallel to the
  spine, attached at evenly spaced points along the diagonal branch.
  Each sub-cause carries its label as a text shape adjacent to the
  segment.

Defaults
--------

When *categories* is omitted (or ``None``), the canonical "**6Ms**"
schema is used: People, Process, Product, Technology, Environment,
Measurement. Each default category is seeded with an empty sub-cause
list — the resulting diagram renders the six branches with nothing
hanging off them, which is the conventional starting point for a
brainstorming workshop.

The 6Ms are exposed publicly as :data:`FISHBONE_DEFAULT_CATEGORIES`
for callers that want to extend or reorder the default schema.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import math
from typing import (
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shapes.base import Shape


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Default fishbone category schema — the canonical "6Ms" used in Lean
#: / Six Sigma practice. Each entry maps to an empty sub-cause list.
#:
#: The order is fixed (and matches Microsoft's built-in Visio template
#: shipped with the "Cause and Effect Diagram" stencil): People,
#: Process, Product, Technology, Environment, Measurement.
FISHBONE_DEFAULT_CATEGORIES: Tuple[str, ...] = (
    "People",
    "Process",
    "Product",
    "Technology",
    "Environment",
    "Measurement",
)

#: Branch angle (degrees) between a category branch and the horizontal
#: spine. ``60`` matches the conventional Ishikawa rendering used in
#: Microsoft's built-in template — branches lean *toward* the head of
#: the fish, not perpendicular to the spine.
FISHBONE_BRANCH_ANGLE_DEG: float = 60.0


# ---------------------------------------------------------------------------
# Layout constants — module-private; override-able via build kwargs
# ---------------------------------------------------------------------------

_PAGE_MARGIN_X: float = 0.5
_PAGE_MARGIN_Y: float = 0.5
_TITLE_BAND_HEIGHT: float = 0.6

# Spine geometry — both endpoints sit on the body's vertical midline.
# The head (right end) anchors the problem-statement rectangle.
_SPINE_INSET_LEFT: float = 0.5
_PROBLEM_BOX_WIDTH: float = 2.5
_PROBLEM_BOX_HEIGHT: float = 1.0

# Category-label rectangle (the "rib end") sizing.
_CATEGORY_BOX_WIDTH: float = 1.4
_CATEGORY_BOX_HEIGHT: float = 0.5

# Sub-cause rendering — short horizontal whisker plus a text caption.
_SUBCAUSE_WHISKER_LEN: float = 0.6
_SUBCAUSE_TEXT_WIDTH: float = 1.6
_SUBCAUSE_TEXT_HEIGHT: float = 0.3

# Default page dimensions (landscape; same defaults as swim_lanes /
# process kits).
_DEFAULT_PAGE_WIDTH: float = 14.0
_DEFAULT_PAGE_HEIGHT: float = 8.5


CategoriesLike = Mapping[str, Sequence[str]]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_problem(problem: str) -> str:
    if not isinstance(problem, str):
        raise TypeError(
            "problem must be a str (got %r)" % type(problem).__name__
        )
    if not problem:
        raise ValueError("problem must be a non-empty str")
    return problem


def _normalise_categories(
    categories: Optional[CategoriesLike],
) -> Dict[str, List[str]]:
    """Coerce *categories* into a ``{name: [sub_causes...]}`` dict.

    ``None`` (or omitted) defaults to the 6Ms with empty sub-cause
    lists. A non-mapping argument is rejected, as is a category whose
    value is not a sequence of strings.
    """
    if categories is None:
        return {name: [] for name in FISHBONE_DEFAULT_CATEGORIES}

    if not isinstance(categories, Mapping):
        raise TypeError(
            "categories must be a Mapping[str, Sequence[str]] (got %r)"
            % type(categories).__name__
        )

    if not categories:
        raise ValueError("categories must contain at least one category")

    out: Dict[str, List[str]] = {}
    for raw_name, raw_subs in categories.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError(
                "category name must be a non-empty str (got %r)" % raw_name
            )
        if raw_name in out:
            raise ValueError(
                "category name %r is duplicated" % raw_name
            )
        if raw_subs is None:
            raise TypeError(
                "category %r sub-causes must be a sequence of str, "
                "got None" % raw_name
            )
        sub_list: List[str] = []
        for ix, sub in enumerate(raw_subs):
            if not isinstance(sub, str) or not sub:
                raise ValueError(
                    "category %r sub-cause %d must be a non-empty str "
                    "(got %r)" % (raw_name, ix, sub)
                )
            sub_list.append(sub)
        out[raw_name] = sub_list
    return out


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _draw_segment(
    page,
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> Shape:
    """Author a master-less line segment from *(x0, y0)* to *(x1, y1)*.

    Implemented as an :meth:`~vsdx.shapes.shapetree.ShapeTree.\
add_custom_shape` whose bounding box is the axis-aligned rectangle
    spanned by the two endpoints. The geometry path is a single
    ``MoveTo`` + ``LineTo`` rendered relative to that bounding box
    (Visio's local coord space — bottom-left is ``(0, 0)``,
    top-right is ``(width, height)``).

    Lines that are collinear with one of the bbox edges (a strictly
    horizontal or vertical segment) collapse to a zero-extent
    bbox in one dimension; that's fine — Visio still strokes the
    geometry path. The bbox just gives the segment a centre-pin and
    a ``Width`` / ``Height``.
    """
    width = abs(x1 - x0)
    height = abs(y1 - y0)
    pin_x = (x0 + x1) / 2
    pin_y = (y0 + y1) / 2
    shape = page.shapes.add_custom_shape(
        at=(pin_x, pin_y),
        size=(max(width, 1e-6), max(height, 1e-6)),
    )

    # Path coordinates in the shape's local coord space — bottom-left
    # is (0, 0), top-right is (width, height). Map the global endpoints
    # back into local coords.
    lx0 = 0.0 if x0 <= x1 else width
    ly0 = 0.0 if y0 <= y1 else height
    lx1 = width if x0 <= x1 else 0.0
    ly1 = height if y0 <= y1 else 0.0
    geometry = shape.geometry
    geometry.move_to(lx0, ly0)
    geometry.line_to(lx1, ly1)
    return shape


def _category_branch_endpoint(
    *,
    joint_x: float,
    joint_y: float,
    direction: int,
    branch_length: float,
) -> Tuple[float, float]:
    """Compute the outer endpoint of a category branch.

    Branches lean toward the *head* of the fish (the problem box at
    the right end of the spine), which means each branch slopes back
    to the **left** as it moves away from the spine.

    *direction* is ``+1`` for a top branch (above the spine) and
    ``-1`` for a bottom branch.
    """
    angle_rad = math.radians(FISHBONE_BRANCH_ANGLE_DEG)
    dx = -branch_length * math.cos(angle_rad)
    dy = direction * branch_length * math.sin(angle_rad)
    return joint_x + dx, joint_y + dy


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_fishbone(
    problem: str,
    categories: Optional[CategoriesLike] = None,
    *,
    title: Optional[str] = None,
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Author a fishbone (Ishikawa) cause-and-effect diagram.

    The output is a single-page :class:`~vsdx.document.VisioDocument`
    with a horizontal spine, a problem-statement rectangle at the right
    end, category branches alternating top / bottom, and sub-cause
    whiskers parallel to the spine.

    :param problem: the problem statement — boxed at the right end of
        the spine (the head of the fish). Must be a non-empty ``str``.
    :param categories: ordered mapping of *category name* →
        *sub-causes*. Each sub-cause must be a non-empty ``str``; an
        empty list is fine and renders the branch with no whiskers.
        When omitted (or ``None``), the canonical 6Ms schema (People,
        Process, Product, Technology, Environment, Measurement) is
        used — see :data:`FISHBONE_DEFAULT_CATEGORIES`.

        Mapping order is preserved (Python 3.7+ dict-insertion order),
        so callers control left-to-right placement and the
        top / bottom alternation.

    :param title: optional caption rendered in a title band along the
        top of the page. Defaults to *problem* when omitted, which is
        the most common use case (the problem statement is also the
        diagram's title).
    :param page_width: page width in inches. Default: ``14.0``
        (landscape).
    :param page_height: page height in inches. Default: ``8.5``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title* (whitespace-trimmed); falls back to ``"Fishbone"``
        when *title* is empty.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *problem* / *title* is not a ``str``, or
        when *categories* is not a mapping.
    :raises ValueError: when *problem* is empty, when *categories* is
        empty / has duplicate keys / has empty names, when a sub-cause
        is empty or non-string, or when the page is too small to
        accommodate the title band, the spine, and the branches.

    .. versionadded:: 0.4.0
    """
    # -- 1. Argument validation ------------------------------------------
    problem = _validate_problem(problem)
    cat_dict = _normalise_categories(categories)

    if title is None:
        title = problem
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)

    # -- 2. Geometry checks ----------------------------------------------
    inner_w = page_width - 2 * _PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _PAGE_MARGIN_X)
        )

    body_top = page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT
    body_bottom = _PAGE_MARGIN_Y
    body_height = body_top - body_bottom
    if body_height <= 0:
        raise ValueError(
            "page_height=%r is too small for the title band" % page_height
        )

    spine_y = (body_top + body_bottom) / 2

    # The spine runs from a left inset to the *left* edge of the
    # problem box. The problem box is then anchored on the right margin.
    problem_pin_x = page_width - _PAGE_MARGIN_X - _PROBLEM_BOX_WIDTH / 2
    problem_left = problem_pin_x - _PROBLEM_BOX_WIDTH / 2
    spine_x_left = _PAGE_MARGIN_X + _SPINE_INSET_LEFT
    spine_x_right = problem_left
    spine_length = spine_x_right - spine_x_left
    if spine_length <= 0:
        raise ValueError(
            "page_width=%r is too small to fit the spine + problem box"
            % page_width
        )

    # Distribute categories along the spine — evenly spaced joints, but
    # leaving a small gap from the head so the first joint doesn't
    # coincide with the problem box.
    cat_names = list(cat_dict.keys())
    n_categories = len(cat_names)
    # Available headroom for branches above and below the spine.
    half_body = (body_height / 2) - 0.2
    if half_body <= 0:
        raise ValueError(
            "page_height=%r is too small to fit the branches above and "
            "below the spine" % page_height
        )
    # Branch length sized so the diagonal endpoint stays within the
    # body — sin(60°) * length ≈ half_body. We leave a 20 % safety
    # margin to keep the category-label box on-page.
    sin_branch = math.sin(math.radians(FISHBONE_BRANCH_ANGLE_DEG))
    branch_length = (half_body * 0.8) / sin_branch
    branch_length = max(0.5, branch_length)

    # Joint x-positions: evenly spaced over the spine, but offset
    # leftward from the head so each diagonal points "back" into open
    # space. We use n equal segments and place the joints at the
    # right end of each segment so the rightmost joint is just a hair
    # back from the head.
    joint_xs: List[float] = []
    if n_categories == 1:
        joint_xs.append(spine_x_left + spine_length * 0.5)
    else:
        # First joint sits ~10 % in from the left, last joint ~10 %
        # back from the head; remaining joints equally spaced.
        first = spine_x_left + spine_length * 0.15
        last = spine_x_right - spine_length * 0.15
        if last < first:
            first = last = (spine_x_left + spine_x_right) / 2
        if n_categories == 2:
            joint_xs = [first, last]
        else:
            step = (last - first) / (n_categories - 1)
            for i in range(n_categories):
                joint_xs.append(first + step * i)

    # -- 3. Document + page ----------------------------------------------
    doc = Visio()
    name = (page_name or title.strip() or "Fishbone")
    page = doc.pages.add_page(name=name, width=page_width, height=page_height)

    # -- 4. Title band ---------------------------------------------------
    if title:
        title_pin_x = _PAGE_MARGIN_X + inner_w / 2
        title_pin_y = (
            page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT / 2
        )
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(inner_w, _TITLE_BAND_HEIGHT),
            text=title,
        )

    # -- 5. Spine --------------------------------------------------------
    _draw_segment(
        page,
        x0=spine_x_left,
        y0=spine_y,
        x1=spine_x_right,
        y1=spine_y,
    )

    # -- 6. Problem box --------------------------------------------------
    problem_pin_y = spine_y
    page.shapes.add_shape(
        VS_SHAPE_TYPE.RECTANGLE,
        at=(problem_pin_x, problem_pin_y),
        size=(_PROBLEM_BOX_WIDTH, _PROBLEM_BOX_HEIGHT),
        text=problem,
    )

    # -- 7. Category branches + sub-causes -------------------------------
    for ix, cat_name in enumerate(cat_names):
        # Alternate top / bottom: even indices go up, odd go down.
        direction = 1 if (ix % 2 == 0) else -1
        joint_x = joint_xs[ix]
        joint_y = spine_y
        end_x, end_y = _category_branch_endpoint(
            joint_x=joint_x,
            joint_y=joint_y,
            direction=direction,
            branch_length=branch_length,
        )

        # Diagonal branch line.
        _draw_segment(page, x0=joint_x, y0=joint_y, x1=end_x, y1=end_y)

        # Category-label rectangle at the outer end of the branch.
        # Pin slightly above (or below) the line endpoint so the label
        # sits clear of the diagonal.
        label_pin_y = end_y + (
            direction * (_CATEGORY_BOX_HEIGHT / 2 + 0.05)
        )
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(end_x, label_pin_y),
            size=(_CATEGORY_BOX_WIDTH, _CATEGORY_BOX_HEIGHT),
            text=cat_name,
        )

        # Sub-causes: short horizontal whiskers attached to evenly
        # spaced points along the diagonal branch. Skip the joint
        # itself (t=0) and the label end (t=1) — sub-causes hang off
        # the *interior* of the branch.
        sub_causes = cat_dict[cat_name]
        n_subs = len(sub_causes)
        if n_subs == 0:
            continue
        for sx, sub in enumerate(sub_causes):
            t = (sx + 1) / (n_subs + 1)
            attach_x = joint_x + t * (end_x - joint_x)
            attach_y = joint_y + t * (end_y - joint_y)
            whisker_end_x = attach_x - _SUBCAUSE_WHISKER_LEN
            whisker_end_y = attach_y
            _draw_segment(
                page,
                x0=attach_x,
                y0=attach_y,
                x1=whisker_end_x,
                y1=whisker_end_y,
            )
            # Sub-cause label sits above (top branches) or below
            # (bottom branches) the whisker so it never collides
            # with the diagonal.
            label_pin_x = whisker_end_x - _SUBCAUSE_TEXT_WIDTH / 2 + 0.1
            label_pin_y = whisker_end_y + (
                direction * (_SUBCAUSE_TEXT_HEIGHT / 2 + 0.02)
            )
            page.shapes.add_shape(
                VS_SHAPE_TYPE.RECTANGLE,
                at=(label_pin_x, label_pin_y),
                size=(_SUBCAUSE_TEXT_WIDTH, _SUBCAUSE_TEXT_HEIGHT),
                text=sub,
            )

    return doc


__all__ = [
    "FISHBONE_BRANCH_ANGLE_DEG",
    "FISHBONE_DEFAULT_CATEGORIES",
    "CategoriesLike",
    "build_fishbone",
]
