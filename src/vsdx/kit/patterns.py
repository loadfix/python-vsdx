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
"""High-level diagram pattern factories — issue #52.

Four opinionated builders that turn plain-Python descriptions into a
fully-formed :class:`~vsdx.document.VisioDocument`. The patterns share
the kit conventions of :mod:`vsdx.kit.swim_lanes` /
:mod:`vsdx.kit.process` / :mod:`vsdx.kit.org_chart` (single-call
factory, no in-place edits, no third-party deps) and lean on the
shared infrastructure already shipped in earlier waves:

* :func:`aws_three_tier` — three-tier cloud reference architecture
  built around the container shape from issue #120 (Wave 5). Each
  tier (web / app / data) is a labelled :class:`~vsdx.container.Container`
  whose member shapes are the named resources, and a region-level
  outer container wraps the three tiers. Inter-tier connectors glue
  the first resource of each tier to its neighbour so the rendered
  diagram reads top-to-bottom.
* :func:`sequence_diagram` — UML-style sequence diagram. Actors are
  laid out left-to-right as small header boxes; each actor drops a
  vertical "lifeline" line down the body of the page; messages
  between actors are horizontal arrows stacked top-to-bottom in
  declaration order, labelled with the message text.
* :func:`gantt_chart` — horizontal-bar Gantt chart on a date axis.
  Each task carries ``start`` / ``end`` :class:`~datetime.date`
  instances; the page x-axis spans the project's full date range and
  bars are placed on horizontal swim-lanes (one per task).
* :func:`mind_map` — radial mind map. The root concept sits at page
  centre; branches fan out around it via the
  :func:`vsdx.layout.layout` helper from issue #50 (Wave 8) running
  in ``"radial"`` mode. Sub-branches hang off their parent on the
  next ring.

All four factories return a single-page
:class:`~vsdx.document.VisioDocument`. Save with
:meth:`~vsdx.document.VisioDocument.save` and the result opens in
Visio desktop.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.routing import ROUTING_RIGHT_ANGLE
from vsdx.shapes.base import Shape

if TYPE_CHECKING:
    from vsdx.container import Container


# ---------------------------------------------------------------------------
# Public constants — three-tier tier names
# ---------------------------------------------------------------------------

#: Tier label for the public-facing layer.
AWS_TIER_WEB: str = "Web"

#: Tier label for the application / business-logic layer.
AWS_TIER_APP: str = "App"

#: Tier label for persistent storage.
AWS_TIER_DATA: str = "Data"

#: Frozen tuple of every recognised tier label, top → bottom.
AWS_TIER_ORDER: Tuple[str, ...] = (
    AWS_TIER_WEB,
    AWS_TIER_APP,
    AWS_TIER_DATA,
)


# ---------------------------------------------------------------------------
# Layout constants — module-private; tweakable via build kwargs
# ---------------------------------------------------------------------------

# AWS three-tier
_AWS_PAGE_MARGIN_X: float = 0.5
_AWS_PAGE_MARGIN_Y: float = 0.5
_AWS_TITLE_BAND_HEIGHT: float = 0.6
_AWS_REGION_PADDING: float = 0.5
_AWS_TIER_PADDING: float = 0.4
_AWS_TIER_GAP: float = 0.3
_AWS_RESOURCE_WIDTH: float = 1.6
_AWS_RESOURCE_HEIGHT: float = 0.6
_AWS_RESOURCE_GAP: float = 0.25
_AWS_DEFAULT_PAGE_WIDTH: float = 14.0
_AWS_DEFAULT_PAGE_HEIGHT: float = 10.0

# Sequence diagram
_SEQ_PAGE_MARGIN_X: float = 0.5
_SEQ_PAGE_MARGIN_Y: float = 0.5
_SEQ_TITLE_BAND_HEIGHT: float = 0.6
_SEQ_ACTOR_BOX_HEIGHT: float = 0.6
_SEQ_ACTOR_BOX_WIDTH: float = 1.4
_SEQ_MESSAGE_GAP: float = 0.5
_SEQ_LIFELINE_TAIL: float = 0.4
_SEQ_DEFAULT_PAGE_WIDTH: float = 14.0
_SEQ_DEFAULT_PAGE_HEIGHT: float = 10.0

# Gantt chart
_GANTT_PAGE_MARGIN_X: float = 0.5
_GANTT_PAGE_MARGIN_Y: float = 0.5
_GANTT_TITLE_BAND_HEIGHT: float = 0.6
_GANTT_LABEL_COL_WIDTH: float = 2.5
_GANTT_HEADER_HEIGHT: float = 0.45
_GANTT_ROW_HEIGHT: float = 0.5
_GANTT_ROW_GAP: float = 0.1
_GANTT_DEFAULT_PAGE_WIDTH: float = 14.0
_GANTT_DEFAULT_PAGE_HEIGHT: float = 8.5

# Mind map
_MIND_PAGE_MARGIN_X: float = 0.5
_MIND_PAGE_MARGIN_Y: float = 0.5
_MIND_TITLE_BAND_HEIGHT: float = 0.6
_MIND_NODE_WIDTH: float = 1.8
_MIND_NODE_HEIGHT: float = 0.55
_MIND_RING_SPACING: float = 1.6
_MIND_DEFAULT_PAGE_WIDTH: float = 14.0
_MIND_DEFAULT_PAGE_HEIGHT: float = 10.0


# ---------------------------------------------------------------------------
# Validation helpers — shared
# ---------------------------------------------------------------------------


def _ensure_str(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(
            "%s must be a str (got %r)" % (name, type(value).__name__)
        )
    return value


def _ensure_non_empty_str_seq(
    name: str, values: Sequence[Any]
) -> List[str]:
    if values is None:
        raise TypeError("%s must be a sequence of str, got None" % name)
    out: List[str] = []
    for ix, v in enumerate(values):
        if not isinstance(v, str) or not v:
            raise ValueError(
                "%s[%d] must be a non-empty str (got %r)" % (name, ix, v)
            )
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# AWS three-tier
# ---------------------------------------------------------------------------


def aws_three_tier(
    *,
    name: str,
    region: str,
    web_tier: Sequence[str],
    app_tier: Sequence[str],
    data_tier: Sequence[str],
    page_width: float = _AWS_DEFAULT_PAGE_WIDTH,
    page_height: float = _AWS_DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Author an AWS-style three-tier reference architecture.

    Each tier (Web / App / Data) is rendered as a labelled
    :class:`~vsdx.container.Container` (the container shape from issue
    #120, Wave 5) with its named resources stacked horizontally inside.
    A region-level outer container wraps the three tier containers and
    carries the ``region`` label so the diagram identifies its
    deployment scope at a glance. Vertical connectors glue the leading
    resource of each tier to its downstream neighbour.

    :param name: deployment name — rendered as the page title and the
        outer (region) container's label prefix (``"<name> — <region>"``).
    :param region: region identifier (e.g. ``"ap-southeast-2"``) — the
        suffix on the outer container's label.
    :param web_tier: ordered iterable of public-tier resource names.
    :param app_tier: ordered iterable of application-tier resource
        names.
    :param data_tier: ordered iterable of data-tier resource names.
    :param page_width: page width in inches. Default: ``14.0``.
    :param page_height: page height in inches. Default: ``10.0``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *name*; falls back to ``"AWS three-tier"`` when *name* is empty.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.
        Save with :meth:`~vsdx.document.VisioDocument.save`.

    :raises TypeError: when *name* / *region* is not a ``str``, or
        when any tier is not a sequence of strings.
    :raises ValueError: when a tier is empty, when a resource name is
        not a non-empty ``str``, or when the page is too small to
        accommodate the containers.

    .. versionadded:: 0.4.0
    """
    name = _ensure_str("name", name)
    region = _ensure_str("region", region)
    tiers: Dict[str, List[str]] = {
        AWS_TIER_WEB: _ensure_non_empty_str_seq("web_tier", web_tier),
        AWS_TIER_APP: _ensure_non_empty_str_seq("app_tier", app_tier),
        AWS_TIER_DATA: _ensure_non_empty_str_seq("data_tier", data_tier),
    }
    for tier_name, members in tiers.items():
        if not members:
            raise ValueError(
                "%s tier must contain at least one resource" % tier_name
            )

    inner_w = page_width - 2 * _AWS_PAGE_MARGIN_X
    inner_h = page_height - 2 * _AWS_PAGE_MARGIN_Y - _AWS_TITLE_BAND_HEIGHT
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _AWS_PAGE_MARGIN_X)
        )
    if inner_h <= 0:
        raise ValueError(
            "page_height=%r is too small for the title band" % page_height
        )

    # Outer (region) container fills the body. Tier containers stack
    # vertically inside it with equal heights.
    region_w = inner_w
    region_h = inner_h
    region_pin_x = _AWS_PAGE_MARGIN_X + region_w / 2
    region_pin_y = _AWS_PAGE_MARGIN_Y + region_h / 2

    # Vertical real estate inside the region container after padding
    # for its own border and inset.
    tier_zone_h = (
        region_h
        - 2 * _AWS_REGION_PADDING
        - 2 * _AWS_TIER_GAP
    )
    if tier_zone_h <= 0:
        raise ValueError(
            "page_height=%r is too small to fit the three tiers" % page_height
        )
    tier_h = tier_zone_h / 3.0
    if tier_h < _AWS_TIER_PADDING * 2 + _AWS_RESOURCE_HEIGHT:
        raise ValueError(
            "page_height=%r is too small — each tier needs at least "
            "%.2f inches" % (page_height, _AWS_TIER_PADDING * 2 + _AWS_RESOURCE_HEIGHT)
        )
    tier_w = region_w - 2 * _AWS_REGION_PADDING

    doc = Visio()
    page_label = page_name or name.strip() or "AWS three-tier"
    page = doc.pages.add_page(
        name=page_label, width=page_width, height=page_height
    )

    # Title band
    if name:
        title_pin_y = page_height - _AWS_PAGE_MARGIN_Y - _AWS_TITLE_BAND_HEIGHT / 2
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(_AWS_PAGE_MARGIN_X + inner_w / 2, title_pin_y),
            size=(inner_w, _AWS_TITLE_BAND_HEIGHT),
            text=name,
        )

    # Region container
    region_label = "%s — %s" % (name or "Region", region)
    region_container = page.add_container(
        title=region_label,
        title_position="top-left",
        style="rounded",
        at=(region_pin_x, region_pin_y),
        size=(region_w, region_h),
    )

    # Tier centre Y positions (top to bottom in screen coords means
    # descending Y in Visio's bottom-anchored coord system).
    region_top = _AWS_PAGE_MARGIN_Y + region_h - _AWS_REGION_PADDING
    tier_centres_y: List[float] = []
    for ix in range(3):
        cy = region_top - _AWS_TIER_PADDING - tier_h / 2 - ix * (tier_h + _AWS_TIER_GAP)
        tier_centres_y.append(cy)

    tier_containers: Dict[str, "Container"] = {}
    leading_resources: Dict[str, Shape] = {}
    for tier_ix, tier_name in enumerate(AWS_TIER_ORDER):
        members = tiers[tier_name]
        tier_centre_x = _AWS_PAGE_MARGIN_X + region_w / 2
        tier_centre_y = tier_centres_y[tier_ix]
        # The tier container is added at page level — Visio renders
        # nested containers via positional overlap rather than via a
        # parent-child reparenting (matches issue #120's authoring
        # convention for stacked boundary shapes).
        tier_container = page.add_container(
            title="%s tier" % tier_name,
            title_position="top-left",
            style="rounded",
            at=(tier_centre_x, tier_centre_y),
            size=(tier_w, tier_h),
        )
        tier_containers[tier_name] = tier_container

        # Drop resources horizontally inside the tier band.
        resource_count = len(members)
        avail_w = tier_w - 2 * _AWS_TIER_PADDING
        # Compute resource width — shrink to fit if too many resources.
        resource_w = min(_AWS_RESOURCE_WIDTH, max(0.5, (
            avail_w - (resource_count - 1) * _AWS_RESOURCE_GAP
        ) / max(resource_count, 1)))
        total_w = (
            resource_count * resource_w
            + (resource_count - 1) * _AWS_RESOURCE_GAP
        )
        first_x = tier_centre_x - total_w / 2 + resource_w / 2
        for r_ix, resource_name in enumerate(members):
            r_x = first_x + r_ix * (resource_w + _AWS_RESOURCE_GAP)
            shape = page.shapes.add_shape(
                VS_SHAPE_TYPE.RECTANGLE,
                at=(r_x, tier_centre_y),
                size=(resource_w, _AWS_RESOURCE_HEIGHT),
                text=resource_name,
            )
            if r_ix == 0:
                leading_resources[tier_name] = shape

    # Inter-tier connectors — glue the leading resource of each tier to
    # the leading resource of the next tier.
    for ix in range(len(AWS_TIER_ORDER) - 1):
        upper = leading_resources[AWS_TIER_ORDER[ix]]
        lower = leading_resources[AWS_TIER_ORDER[ix + 1]]
        page.add_connector(upper, lower, routing=ROUTING_RIGHT_ANGLE)

    # Suppress lint: region_container is intentionally unused beyond
    # authoring — it's referenced to keep the proxy alive long enough
    # for ``add_container`` side-effects to settle.
    _ = region_container
    _ = tier_containers

    return doc


# ---------------------------------------------------------------------------
# Sequence diagram
# ---------------------------------------------------------------------------


MessageLike = Tuple[str, str, str]


def sequence_diagram(
    *,
    title: str,
    actors: Sequence[str],
    messages: Sequence[MessageLike],
    page_width: float = _SEQ_DEFAULT_PAGE_WIDTH,
    page_height: float = _SEQ_DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Author a UML-style sequence diagram and return the document.

    Each actor in *actors* renders as a small header box at the top of
    the page; a vertical "lifeline" line drops from the bottom of each
    header to a fixed tail just above the bottom margin. Each message
    in *messages* (a ``(sender, receiver, text)`` triple) renders as a
    horizontal arrow between the sender's and receiver's lifelines,
    labelled with *text*. Messages stack top-to-bottom in declaration
    order.

    Self-messages — where ``sender == receiver`` — render as a small
    rectangle on the actor's lifeline labelled with the message text;
    no horizontal arrow is drawn.

    :param title: caption rendered in the page's title band.
    :param actors: ordered iterable of actor names. Each name must be
        unique within the diagram.
    :param messages: iterable of ``(sender, receiver, text)`` triples.
        Both endpoints must be members of *actors*; *text* may be any
        ``str`` (an empty string is allowed and renders an unlabelled
        arrow).
    :param page_width: page width in inches. Default: ``14.0``.
    :param page_height: page height in inches. Default: ``10.0``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title*; falls back to ``"Sequence diagram"`` when empty.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises TypeError: when *title* is not a ``str`` or *actors* /
        *messages* is not iterable.
    :raises ValueError: when *actors* is empty, contains duplicates,
        or has empty names; when a message tuple has the wrong shape;
        when a message references an unknown actor; or when the page
        is too small.

    .. versionadded:: 0.4.0
    """
    title = _ensure_str("title", title)
    actor_list = _ensure_non_empty_str_seq("actors", actors)
    if len(set(actor_list)) != len(actor_list):
        raise ValueError("actors must be unique (got %r)" % actor_list)

    parsed_messages: List[Tuple[str, str, str]] = []
    for ix, msg in enumerate(messages):
        if (
            not isinstance(msg, tuple)
            or len(msg) != 3
        ):
            raise ValueError(
                "messages[%d] must be a (sender, receiver, text) tuple "
                "(got %r)" % (ix, msg)
            )
        sender, receiver, text = msg
        if not isinstance(sender, str) or not sender:
            raise ValueError(
                "messages[%d] sender must be a non-empty str (got %r)"
                % (ix, sender)
            )
        if not isinstance(receiver, str) or not receiver:
            raise ValueError(
                "messages[%d] receiver must be a non-empty str (got %r)"
                % (ix, receiver)
            )
        if not isinstance(text, str):
            raise ValueError(
                "messages[%d] text must be a str (got %r)" % (ix, text)
            )
        if sender not in actor_list:
            raise ValueError(
                "messages[%d] sender %r is not in actors" % (ix, sender)
            )
        if receiver not in actor_list:
            raise ValueError(
                "messages[%d] receiver %r is not in actors" % (ix, receiver)
            )
        parsed_messages.append((sender, receiver, text))

    inner_w = page_width - 2 * _SEQ_PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _SEQ_PAGE_MARGIN_X)
        )
    body_top = page_height - _SEQ_PAGE_MARGIN_Y - _SEQ_TITLE_BAND_HEIGHT
    body_bottom = _SEQ_PAGE_MARGIN_Y
    body_h = body_top - body_bottom
    if body_h <= _SEQ_ACTOR_BOX_HEIGHT + _SEQ_LIFELINE_TAIL:
        raise ValueError(
            "page_height=%r is too small for the actor headers + lifelines"
            % page_height
        )

    doc = Visio()
    page_label = page_name or title.strip() or "Sequence diagram"
    page = doc.pages.add_page(
        name=page_label, width=page_width, height=page_height
    )

    # Title band
    if title:
        title_pin_y = page_height - _SEQ_PAGE_MARGIN_Y - _SEQ_TITLE_BAND_HEIGHT / 2
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(_SEQ_PAGE_MARGIN_X + inner_w / 2, title_pin_y),
            size=(inner_w, _SEQ_TITLE_BAND_HEIGHT),
            text=title,
        )

    # Actor lane x-coordinates — equally spaced across the body.
    n = len(actor_list)
    if n == 1:
        lane_x: List[float] = [_SEQ_PAGE_MARGIN_X + inner_w / 2]
    else:
        lane_step = inner_w / (n + 1)
        lane_x = [_SEQ_PAGE_MARGIN_X + (i + 1) * lane_step for i in range(n)]

    # Actor header boxes — pinned at the top of the body.
    actor_header_y = body_top - _SEQ_ACTOR_BOX_HEIGHT / 2
    actor_x_by_name: Dict[str, float] = {}
    for ix, actor in enumerate(actor_list):
        x = lane_x[ix]
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(x, actor_header_y),
            size=(_SEQ_ACTOR_BOX_WIDTH, _SEQ_ACTOR_BOX_HEIGHT),
            text=actor,
        )
        actor_x_by_name[actor] = x

    # Lifeline vertical lines — bottom of header to bottom of body.
    lifeline_top = body_top - _SEQ_ACTOR_BOX_HEIGHT
    lifeline_bottom = body_bottom + _SEQ_LIFELINE_TAIL / 2
    for actor in actor_list:
        x = actor_x_by_name[actor]
        line_h = lifeline_top - lifeline_bottom
        line_pin_y = (lifeline_top + lifeline_bottom) / 2
        line_shape = page.shapes.add_custom_shape(
            at=(x, line_pin_y),
            size=(0.05, max(line_h, 1e-6)),
        )
        # Vertical line within the bbox.
        line_shape.geometry.move_to(0.5, 0.0)
        line_shape.geometry.line_to(0.5, 1.0)

    # Messages — stacked top-to-bottom in declaration order. The first
    # message sits a fixed gap below the actor headers.
    avail_h = lifeline_top - lifeline_bottom
    msg_count = len(parsed_messages)
    if msg_count > 0:
        # Reserve top gap and bottom gap so the first / last messages
        # don't crowd the headers / page edge.
        usable = max(avail_h - _SEQ_MESSAGE_GAP, _SEQ_MESSAGE_GAP)
        step = min(_SEQ_MESSAGE_GAP, usable / max(msg_count, 1))
        first_y = lifeline_top - _SEQ_MESSAGE_GAP
        for ix, (sender, receiver, text) in enumerate(parsed_messages):
            msg_y = first_y - ix * step
            sender_x = actor_x_by_name[sender]
            receiver_x = actor_x_by_name[receiver]
            if sender == receiver:
                # Self-message — small loop rectangle on the lifeline.
                page.shapes.add_shape(
                    VS_SHAPE_TYPE.RECTANGLE,
                    at=(sender_x + 0.4, msg_y),
                    size=(0.7, 0.3),
                    text=text,
                )
                continue
            # Horizontal arrow from sender to receiver. Implemented as
            # a custom-shape line so the arrow sits in the rendered
            # page; the text label lives in a separate small rectangle
            # placed at the midpoint.
            mid_x = (sender_x + receiver_x) / 2
            line_w = abs(receiver_x - sender_x)
            arrow = page.shapes.add_custom_shape(
                at=(mid_x, msg_y),
                size=(max(line_w, 1e-6), 0.05),
            )
            # Determine direction in local coords.
            if sender_x <= receiver_x:
                arrow.geometry.move_to(0.0, 0.5)
                arrow.geometry.line_to(1.0, 0.5)
            else:
                arrow.geometry.move_to(1.0, 0.5)
                arrow.geometry.line_to(0.0, 0.5)
            if text:
                page.shapes.add_shape(
                    VS_SHAPE_TYPE.RECTANGLE,
                    at=(mid_x, msg_y + 0.18),
                    size=(min(line_w * 0.75, 1.8), 0.3),
                    text=text,
                )

    return doc


# ---------------------------------------------------------------------------
# Gantt chart
# ---------------------------------------------------------------------------


TaskLike = Mapping[str, Any]


def _gantt_parse_date(value: Any, *, ix: int, key: str) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "tasks[%d] %r %r is not an ISO date (%s)"
                % (ix, key, value, exc)
            ) from exc
    raise TypeError(
        "tasks[%d] %r must be a datetime.date or ISO date string "
        "(got %r)" % (ix, key, type(value).__name__)
    )


def gantt_chart(
    *,
    title: str = "",
    tasks: Sequence[TaskLike],
    page_width: float = _GANTT_DEFAULT_PAGE_WIDTH,
    page_height: float = _GANTT_DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
) -> VisioDocument:
    """Author a horizontal-bar Gantt chart on a date axis.

    Each task carries:

    * ``"name"`` (required) — the task label, also rendered in the
      left label column.
    * ``"start"`` / ``"end"`` (required) — :class:`~datetime.date`
      instances or ISO ``YYYY-MM-DD`` strings. ``end`` must be on or
      after ``start``.

    The page x-axis spans the union of every task's ``start`` /
    ``end``; the leftmost column carries task labels and the rest of
    the page hosts one horizontal bar per task on its own row.
    Today's date renders as a thin vertical "today line" when it
    falls inside the project window.

    :param title: caption rendered in the page's title band.
        Default: ``""`` (no title band).
    :param tasks: iterable of task descriptors. Must be non-empty.
    :param page_width: page width in inches. Default: ``14.0``.
    :param page_height: page height in inches. Default: ``8.5``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title*; falls back to ``"Gantt chart"`` when *title* is empty.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises TypeError: when *title* is not a ``str``, when *tasks* is
        not iterable, when a task's ``start`` / ``end`` is not a
        :class:`~datetime.date` or ISO string.
    :raises ValueError: when *tasks* is empty, when a task is missing
        required keys, when ``end`` precedes ``start``, when names
        collide, or when the page is too small for the requested
        rows.

    .. versionadded:: 0.4.0
    """
    title = _ensure_str("title", title)
    task_list: List[TaskLike] = list(tasks)
    if not task_list:
        raise ValueError("tasks must contain at least one task")

    parsed: List[Tuple[str, datetime.date, datetime.date]] = []
    seen: Dict[str, int] = {}
    for ix, task in enumerate(task_list):
        if not isinstance(task, Mapping):
            raise TypeError(
                "tasks[%d] must be a Mapping (got %r)"
                % (ix, type(task).__name__)
            )
        if "name" not in task:
            raise ValueError("tasks[%d] is missing 'name'" % ix)
        if "start" not in task:
            raise ValueError("tasks[%d] is missing 'start'" % ix)
        if "end" not in task:
            raise ValueError("tasks[%d] is missing 'end'" % ix)
        name = task["name"]
        if not isinstance(name, str) or not name:
            raise ValueError(
                "tasks[%d] 'name' must be a non-empty str (got %r)"
                % (ix, name)
            )
        if name in seen:
            raise ValueError(
                "tasks[%d] duplicate name %r (also at index %d)"
                % (ix, name, seen[name])
            )
        seen[name] = ix
        start = _gantt_parse_date(task["start"], ix=ix, key="start")
        end = _gantt_parse_date(task["end"], ix=ix, key="end")
        if end < start:
            raise ValueError(
                "tasks[%d] %r: end %s precedes start %s"
                % (ix, name, end.isoformat(), start.isoformat())
            )
        parsed.append((name, start, end))

    project_start = min(p[1] for p in parsed)
    project_end = max(p[2] for p in parsed)
    span_days = max((project_end - project_start).days, 1)

    inner_w = page_width - 2 * _GANTT_PAGE_MARGIN_X
    if inner_w <= _GANTT_LABEL_COL_WIDTH + 1.0:
        raise ValueError(
            "page_width=%r is too small for the label column" % page_width
        )
    title_band = _GANTT_TITLE_BAND_HEIGHT if title else 0.0
    body_top = page_height - _GANTT_PAGE_MARGIN_Y - title_band
    body_bottom = _GANTT_PAGE_MARGIN_Y
    body_h = body_top - body_bottom
    needed_h = (
        _GANTT_HEADER_HEIGHT
        + len(parsed) * (_GANTT_ROW_HEIGHT + _GANTT_ROW_GAP)
    )
    if body_h < needed_h:
        raise ValueError(
            "page_height=%r is too small for %d tasks (need %.2f inches "
            "of body)" % (page_height, len(parsed), needed_h)
        )

    doc = Visio()
    page_label = page_name or title.strip() or "Gantt chart"
    page = doc.pages.add_page(
        name=page_label, width=page_width, height=page_height
    )

    # Title band
    if title:
        title_pin_y = page_height - _GANTT_PAGE_MARGIN_Y - _GANTT_TITLE_BAND_HEIGHT / 2
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(_GANTT_PAGE_MARGIN_X + inner_w / 2, title_pin_y),
            size=(inner_w, _GANTT_TITLE_BAND_HEIGHT),
            text=title,
        )

    chart_left = _GANTT_PAGE_MARGIN_X + _GANTT_LABEL_COL_WIDTH
    chart_right = _GANTT_PAGE_MARGIN_X + inner_w
    chart_w = chart_right - chart_left

    def _date_to_x(d: datetime.date) -> float:
        offset = (d - project_start).days
        return chart_left + (offset / span_days) * chart_w

    # Header band — show the project window endpoints + label "Date".
    header_y = body_top - _GANTT_HEADER_HEIGHT / 2
    page.shapes.add_shape(
        VS_SHAPE_TYPE.RECTANGLE,
        at=(_GANTT_PAGE_MARGIN_X + _GANTT_LABEL_COL_WIDTH / 2, header_y),
        size=(_GANTT_LABEL_COL_WIDTH, _GANTT_HEADER_HEIGHT),
        text="Task",
    )
    header_text = "%s — %s" % (
        project_start.isoformat(),
        project_end.isoformat(),
    )
    page.shapes.add_shape(
        VS_SHAPE_TYPE.RECTANGLE,
        at=(chart_left + chart_w / 2, header_y),
        size=(chart_w, _GANTT_HEADER_HEIGHT),
        text=header_text,
    )

    # Per-task row — label cell + bar.
    row_top = body_top - _GANTT_HEADER_HEIGHT
    for ix, (name, start, end) in enumerate(parsed):
        row_centre_y = (
            row_top
            - _GANTT_ROW_GAP
            - _GANTT_ROW_HEIGHT / 2
            - ix * (_GANTT_ROW_HEIGHT + _GANTT_ROW_GAP)
        )
        # Label cell
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(_GANTT_PAGE_MARGIN_X + _GANTT_LABEL_COL_WIDTH / 2, row_centre_y),
            size=(_GANTT_LABEL_COL_WIDTH, _GANTT_ROW_HEIGHT),
            text=name,
        )
        # Bar — span from start to end. Single-day tasks get a 1-day
        # minimum width so they're visible.
        bar_left_x = _date_to_x(start)
        bar_right_x = _date_to_x(end)
        bar_w = max(bar_right_x - bar_left_x, chart_w / max(span_days, 1))
        bar_pin_x = bar_left_x + bar_w / 2
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(bar_pin_x, row_centre_y),
            size=(bar_w, _GANTT_ROW_HEIGHT * 0.7),
            text="",
        )

    # "Today" indicator — a thin vertical rectangle when today is
    # within the project window. Renders behind the bars at the same
    # y-extent as the chart body.
    today = datetime.date.today()
    if project_start <= today <= project_end:
        today_x = _date_to_x(today)
        body_chart_top = row_top - _GANTT_ROW_GAP
        body_chart_bottom = (
            row_top
            - _GANTT_ROW_GAP
            - len(parsed) * (_GANTT_ROW_HEIGHT + _GANTT_ROW_GAP)
        )
        body_chart_h = body_chart_top - body_chart_bottom
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(today_x, (body_chart_top + body_chart_bottom) / 2),
            size=(0.04, max(body_chart_h, 1e-6)),
            text="",
        )

    return doc


# ---------------------------------------------------------------------------
# Mind map
# ---------------------------------------------------------------------------


BranchesLike = Mapping[str, Union[Sequence[str], Mapping[str, Any], None]]


def _mind_normalise_branches(
    branches: Optional[BranchesLike],
    *,
    path: str = "branches",
) -> Dict[str, Dict[str, Any]]:
    """Coerce *branches* into a uniform ``{name: {sub_branches: {...}}}`` shape.

    Accepts the relaxed authoring form where a branch may be:

    * ``None`` — no sub-branches (leaf)
    * a ``Sequence[str]`` — sub-branch names (each a leaf)
    * a ``Mapping[str, ...]`` — recursive nested structure
    """
    if branches is None:
        return {}
    if not isinstance(branches, Mapping):
        raise TypeError(
            "%s must be a Mapping (got %r)"
            % (path, type(branches).__name__)
        )
    out: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_subs in branches.items():
        if not isinstance(raw_name, str) or not raw_name:
            raise ValueError(
                "%s key must be a non-empty str (got %r)" % (path, raw_name)
            )
        if raw_name in out:
            raise ValueError(
                "%s has duplicate key %r" % (path, raw_name)
            )
        if raw_subs is None:
            out[raw_name] = {}
        elif isinstance(raw_subs, Mapping):
            out[raw_name] = _mind_normalise_branches(
                raw_subs, path="%s[%r]" % (path, raw_name)
            )
        elif isinstance(raw_subs, (list, tuple)):
            sub_dict: Dict[str, Dict[str, Any]] = {}
            for ix, sub in enumerate(raw_subs):
                if not isinstance(sub, str) or not sub:
                    raise ValueError(
                        "%s[%r][%d] must be a non-empty str (got %r)"
                        % (path, raw_name, ix, sub)
                    )
                if sub in sub_dict:
                    raise ValueError(
                        "%s[%r] has duplicate sub-branch %r"
                        % (path, raw_name, sub)
                    )
                sub_dict[sub] = {}
            out[raw_name] = sub_dict
        else:
            raise TypeError(
                "%s[%r] must be None, a sequence, or a mapping "
                "(got %r)" % (path, raw_name, type(raw_subs).__name__)
            )
    return out


def mind_map(
    *,
    root: str,
    branches: Optional[BranchesLike] = None,
    title: Optional[str] = None,
    page_width: float = _MIND_DEFAULT_PAGE_WIDTH,
    page_height: float = _MIND_DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    spacing: float = _MIND_RING_SPACING,
) -> VisioDocument:
    """Author a radial mind map and return the document.

    The *root* concept renders at page centre as a rounded box;
    *branches* (an arbitrarily nested mapping) populate concentric
    rings around it via :func:`vsdx.layout.layout` running in
    ``"radial"`` mode (issue #50, Wave 8). Each branch is connected
    to its parent via a default dynamic connector.

    :param root: the central node label. Must be a non-empty ``str``.
    :param branches: nested branch structure. Each key is a branch
        label; each value may be ``None`` (leaf), a sequence of
        sub-branch names, or another nested mapping. ``None`` (the
        default) renders a lone root with no branches.
    :param title: caption rendered in the page's title band. Defaults
        to *root* when omitted.
    :param page_width: page width in inches. Default: ``14.0``.
    :param page_height: page height in inches. Default: ``10.0``.
    :param page_name: ``@NameU`` for the rendered page. Defaults to
        *title*; falls back to ``"Mind map"`` when title is empty.
    :param spacing: ring radius step in inches forwarded to the
        radial layout. Default: ``1.6``.

    :returns: a fully-formed :class:`~vsdx.document.VisioDocument`.

    :raises TypeError: when *root* is not a ``str``, *title* is not a
        ``str`` / ``None``, or *branches* is not a mapping.
    :raises ValueError: when *root* is empty, when a branch key is
        empty / duplicated, or when a sub-branch name is empty.

    .. versionadded:: 0.4.0
    """
    root = _ensure_str("root", root)
    if not root:
        raise ValueError("root must be a non-empty str")
    normalised = _mind_normalise_branches(branches)
    if title is None:
        title = root
    title = _ensure_str("title", title)

    inner_w = page_width - 2 * _MIND_PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _MIND_PAGE_MARGIN_X)
        )
    body_top = page_height - _MIND_PAGE_MARGIN_Y - _MIND_TITLE_BAND_HEIGHT
    body_bottom = _MIND_PAGE_MARGIN_Y
    body_h = body_top - body_bottom
    if body_h <= 0:
        raise ValueError(
            "page_height=%r is too small for the title band" % page_height
        )

    doc = Visio()
    page_label = page_name or title.strip() or "Mind map"
    page = doc.pages.add_page(
        name=page_label, width=page_width, height=page_height
    )

    # NOTE: the title band is authored *after* the radial layout below
    # — the layout treats every non-connector shape on the page as a
    # node, so a title rect added up-front would be flung onto the
    # outer ring as an unreachable orphan. Authoring it after keeps
    # the title pinned in the page's title-band region.

    centre_x = _MIND_PAGE_MARGIN_X + inner_w / 2
    centre_y = body_bottom + body_h / 2

    # Drop every node at the centre first; the radial layout below
    # spreads them around the root.
    proxies: Dict[str, Shape] = {}

    def _drop(label: str) -> Shape:
        return page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(centre_x, centre_y),
            size=(_MIND_NODE_WIDTH, _MIND_NODE_HEIGHT),
            text=label,
        )

    # Walk the nested structure depth-first. Detect duplicate node
    # names across the whole tree because the radial layout indexes
    # nodes by identity but the connector wiring uses labels.
    def _collect(
        subtree: Mapping[str, Mapping[str, Any]],
        parent_label: str,
        path: str,
    ) -> None:
        for label, sub in subtree.items():
            if label in proxies or label == root:
                raise ValueError(
                    "%s collides with another node in the mind map "
                    "(node names must be globally unique)" % path
                )
            shape = _drop(label)
            proxies[label] = shape
            page.add_connector(proxies[parent_label], shape)
            _collect(sub, label, "%s[%r]" % (path, label))

    proxies[root] = _drop(root)
    _collect(normalised, root, "branches")

    # Run the radial layout — origin at the page centre. The shape
    # at ``proxies[root]`` is the explicit centre.
    page.layout(
        "radial",
        center_shape=proxies[root],
        spacing=spacing,
        origin=(centre_x, centre_y),
    )

    # Title band — authored last so the radial layout above doesn't
    # treat it as an orphan node and re-pin it to an outer ring.
    if title:
        title_pin_y = page_height - _MIND_PAGE_MARGIN_Y - _MIND_TITLE_BAND_HEIGHT / 2
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(_MIND_PAGE_MARGIN_X + inner_w / 2, title_pin_y),
            size=(inner_w, _MIND_TITLE_BAND_HEIGHT),
            text=title,
        )

    return doc


__all__ = [
    "AWS_TIER_APP",
    "AWS_TIER_DATA",
    "AWS_TIER_ORDER",
    "AWS_TIER_WEB",
    "BranchesLike",
    "MessageLike",
    "TaskLike",
    "aws_three_tier",
    "gantt_chart",
    "mind_map",
    "sequence_diagram",
]
