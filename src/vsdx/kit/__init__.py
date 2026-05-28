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
"""Authoring "kit" — high-level diagram templates layered on the core API.

The :mod:`vsdx.kit` namespace gathers small, opinionated builders that
turn a list of plain-Python descriptions into a fully-formed
:class:`~vsdx.document.VisioDocument`. Each kit module is a one-shot
template — call the builder, save the document, done. No mutation
helpers, no in-place edits — if you need those, drop down to the core
:func:`~vsdx.api.Visio` / :class:`~vsdx.page.Page` API.

Available kits:

* :func:`vsdx.kit.swim_lanes.build_swim_lane_diagram` — cross-functional
  swim-lane diagrams (issue #121, the first kit).
* :func:`vsdx.kit.process.build_sipoc` — five-column SIPOC scoping
  table (issue #128).
* :func:`vsdx.kit.process.build_process_map` — vertical flowchart
  with start / task / decision / end step kinds (issue #128).
* :func:`vsdx.kit.fishbone.build_fishbone` — Ishikawa cause-and-effect
  diagram with horizontal spine, alternating top / bottom category
  branches at 60°, and parallel sub-cause whiskers (issue #129).
* :func:`vsdx.kit.org_chart.build_org_chart` /
  :func:`vsdx.kit.org_chart.build_org_chart_from_csv` —
  hierarchical org charts authored from a programmatic roster or a
  CSV file (issue #122).
* :func:`vsdx.kit.floor_plan.build_floor_plan` — office floor plan
  with rooms, furniture, and wall fixtures (issue #127).

The kit modules avoid third-party runtime deps so they remain
import-light. The ``[kit]`` extra in ``pyproject.toml`` is reserved
as a stable opt-in marker — at this writing it is empty, but pinning
it now means downstream consumers can write ``pip install
'python-vsdx[kit]'`` and that install command keeps working as future
kits grow optional dependencies.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

from vsdx.kit.fishbone import (
    FISHBONE_BRANCH_ANGLE_DEG,
    FISHBONE_DEFAULT_CATEGORIES,
    build_fishbone,
)
from vsdx.kit.floor_plan import (
    FIXTURE_KIND_DOOR,
    FIXTURE_KIND_WINDOW,
    FIXTURE_KINDS,
    FIXTURE_WALL_SIDES,
    FURNITURE_DEFAULT_SIZES,
    FURNITURE_KIND_BED,
    FURNITURE_KIND_BOOKSHELF,
    FURNITURE_KIND_CHAIR,
    FURNITURE_KIND_DESK,
    FURNITURE_KIND_SOFA,
    FURNITURE_KIND_TABLE,
    FURNITURE_KINDS,
    METERS_PER_FOOT,
    UNIT_FEET,
    UNIT_METERS,
    UNIT_TOKENS,
    build_floor_plan,
)
from vsdx.kit.org_chart import (
    DEFAULT_MANAGER_COL,
    DEFAULT_NAME_COL,
    DEFAULT_PHOTO_COL,
    DEFAULT_TEAM_COL,
    DEFAULT_TITLE_COL,
    build_org_chart,
    build_org_chart_from_csv,
)
from vsdx.kit.process import (
    PROCESS_KIND_DECISION,
    PROCESS_KIND_END,
    PROCESS_KIND_START,
    PROCESS_KIND_TASK,
    PROCESS_STEP_KINDS,
    SIPOC_COLUMN_ORDER,
    build_process_map,
    build_sipoc,
)
from vsdx.kit.swim_lanes import (
    SWIM_LANE_STEP_KINDS,
    SWIM_LANE_KIND_DECISION,
    SWIM_LANE_KIND_DEFAULT,
    SWIM_LANE_KIND_END,
    SWIM_LANE_KIND_START,
    build_swim_lane_diagram,
)

__all__ = [
    "DEFAULT_MANAGER_COL",
    "DEFAULT_NAME_COL",
    "DEFAULT_PHOTO_COL",
    "DEFAULT_TEAM_COL",
    "DEFAULT_TITLE_COL",
    "FISHBONE_BRANCH_ANGLE_DEG",
    "FISHBONE_DEFAULT_CATEGORIES",
    "FIXTURE_KIND_DOOR",
    "FIXTURE_KIND_WINDOW",
    "FIXTURE_KINDS",
    "FIXTURE_WALL_SIDES",
    "FURNITURE_DEFAULT_SIZES",
    "FURNITURE_KIND_BED",
    "FURNITURE_KIND_BOOKSHELF",
    "FURNITURE_KIND_CHAIR",
    "FURNITURE_KIND_DESK",
    "FURNITURE_KIND_SOFA",
    "FURNITURE_KIND_TABLE",
    "FURNITURE_KINDS",
    "METERS_PER_FOOT",
    "PROCESS_KIND_DECISION",
    "PROCESS_KIND_END",
    "PROCESS_KIND_START",
    "PROCESS_KIND_TASK",
    "PROCESS_STEP_KINDS",
    "SIPOC_COLUMN_ORDER",
    "SWIM_LANE_KIND_DECISION",
    "SWIM_LANE_KIND_DEFAULT",
    "SWIM_LANE_KIND_END",
    "SWIM_LANE_KIND_START",
    "SWIM_LANE_STEP_KINDS",
    "UNIT_FEET",
    "UNIT_METERS",
    "UNIT_TOKENS",
    "build_fishbone",
    "build_floor_plan",
    "build_org_chart",
    "build_org_chart_from_csv",
    "build_process_map",
    "build_sipoc",
    "build_swim_lane_diagram",
]
