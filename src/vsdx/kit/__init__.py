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
* :func:`vsdx.kit.erd.erd_from_sql` /
  :func:`vsdx.kit.erd.erd_from_models` — entity-relationship
  diagrams authored from a SQL DDL file or a programmatic
  ``{table: {columns: [...]}}`` mapping (issue #130).
* :func:`vsdx.kit.uml.uml_from_python_module` /
  :func:`vsdx.kit.uml.uml_from_json_schema` /
  :func:`vsdx.kit.uml.uml_from_typescript` — UML class diagrams
  authored by introspecting a Python module, walking a JSON Schema
  document, or regex-parsing TypeScript source (issue #131).
* :func:`vsdx.kit.from_workbook.diagram_from_xlsx` — workbook →
  diagram dispatcher: read an ``.xlsx`` data table and delegate to
  the matching kit builder (issue #136). Wraps the builders above;
  no new diagram logic.
* :func:`vsdx.kit.patterns.aws_three_tier` /
  :func:`vsdx.kit.patterns.sequence_diagram` /
  :func:`vsdx.kit.patterns.gantt_chart` /
  :func:`vsdx.kit.patterns.mind_map` — high-level diagram patterns
  for cloud architectures, UML sequence diagrams, project schedules,
  and brainstorming radial maps (issue #52). The AWS pattern uses
  container shapes (#120, Wave 5) for tier boundaries; the mind map
  delegates to the radial layout helper (#50, Wave 8).

The kit modules avoid third-party runtime deps so they remain
import-light. The ``[kit]`` extra in ``pyproject.toml`` is reserved
as a stable opt-in marker — at this writing it is empty, but pinning
it now means downstream consumers can write ``pip install
'python-vsdx[kit]'`` and that install command keeps working as future
kits grow optional dependencies.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

from vsdx.kit.erd import (
    ERD_CONSTRAINT_FK_PREFIX,
    ERD_CONSTRAINT_NOT_NULL,
    ERD_CONSTRAINT_PK,
    ERD_CONSTRAINT_UNIQUE,
    erd_from_models,
    erd_from_sql,
)
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
from vsdx.kit.from_plantuml import (
    PLANTUML_DIAGRAM_KINDS,
    PLANTUML_KIND_ACTIVITY,
    PLANTUML_KIND_COMPONENT,
    PLANTUML_KIND_EMPTY,
    from_plantuml,
    from_plantuml_string,
)
from vsdx.kit.from_workbook import (
    DEFAULT_FLOWS_SHEET,
    DEFAULT_LANES_SHEET,
    DEFAULT_STEPS_SHEET,
    DIAGRAM_KINDS,
    ERD_DEFAULT_COLUMN_COL,
    ERD_DEFAULT_CONSTRAINT_COL,
    ERD_DEFAULT_TABLE_COL,
    ERD_DEFAULT_TYPE_COL,
    KIND_ERD,
    KIND_ORG_CHART,
    KIND_PROCESS_MAP,
    KIND_SWIM_LANE,
    ORG_CHART_DEFAULT_MANAGER_COL,
    ORG_CHART_DEFAULT_NAME_COL,
    ORG_CHART_DEFAULT_PHOTO_COL,
    ORG_CHART_DEFAULT_TEAM_COL,
    ORG_CHART_DEFAULT_TITLE_COL,
    PROCESS_DEFAULT_FROM_COL,
    PROCESS_DEFAULT_KIND_COL,
    PROCESS_DEFAULT_LANE_COL,
    PROCESS_DEFAULT_ON_COL,
    PROCESS_DEFAULT_TEXT_COL,
    PROCESS_DEFAULT_TO_COL,
    diagram_from_xlsx,
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
from vsdx.kit.patterns import (
    AWS_TIER_APP,
    AWS_TIER_DATA,
    AWS_TIER_ORDER,
    AWS_TIER_WEB,
    aws_three_tier,
    gantt_chart,
    mind_map,
    sequence_diagram,
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
    SWIM_LANE_KIND_DECISION,
    SWIM_LANE_KIND_DEFAULT,
    SWIM_LANE_KIND_END,
    SWIM_LANE_KIND_START,
    SWIM_LANE_STEP_KINDS,
    build_swim_lane_diagram,
)
from vsdx.kit.uml import (
    UML_RELATION_ASSOCIATION,
    UML_RELATION_COMPOSITION,
    UML_RELATION_INHERITANCE,
    UML_RELATIONS,
    uml_from_json_schema,
    uml_from_python_module,
    uml_from_typescript,
)

__all__ = [
    "AWS_TIER_APP",
    "AWS_TIER_DATA",
    "AWS_TIER_ORDER",
    "AWS_TIER_WEB",
    "DEFAULT_FLOWS_SHEET",
    "DEFAULT_LANES_SHEET",
    "DEFAULT_MANAGER_COL",
    "DEFAULT_NAME_COL",
    "DEFAULT_PHOTO_COL",
    "DEFAULT_STEPS_SHEET",
    "DEFAULT_TEAM_COL",
    "DEFAULT_TITLE_COL",
    "DIAGRAM_KINDS",
    "ERD_CONSTRAINT_FK_PREFIX",
    "ERD_CONSTRAINT_NOT_NULL",
    "ERD_CONSTRAINT_PK",
    "ERD_CONSTRAINT_UNIQUE",
    "ERD_DEFAULT_COLUMN_COL",
    "ERD_DEFAULT_CONSTRAINT_COL",
    "ERD_DEFAULT_TABLE_COL",
    "ERD_DEFAULT_TYPE_COL",
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
    "KIND_ERD",
    "KIND_ORG_CHART",
    "KIND_PROCESS_MAP",
    "KIND_SWIM_LANE",
    "METERS_PER_FOOT",
    "ORG_CHART_DEFAULT_MANAGER_COL",
    "ORG_CHART_DEFAULT_NAME_COL",
    "ORG_CHART_DEFAULT_PHOTO_COL",
    "ORG_CHART_DEFAULT_TEAM_COL",
    "ORG_CHART_DEFAULT_TITLE_COL",
    "PLANTUML_DIAGRAM_KINDS",
    "PLANTUML_KIND_ACTIVITY",
    "PLANTUML_KIND_COMPONENT",
    "PLANTUML_KIND_EMPTY",
    "PROCESS_DEFAULT_FROM_COL",
    "PROCESS_DEFAULT_KIND_COL",
    "PROCESS_DEFAULT_LANE_COL",
    "PROCESS_DEFAULT_ON_COL",
    "PROCESS_DEFAULT_TEXT_COL",
    "PROCESS_DEFAULT_TO_COL",
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
    "UML_RELATIONS",
    "UML_RELATION_ASSOCIATION",
    "UML_RELATION_COMPOSITION",
    "UML_RELATION_INHERITANCE",
    "UNIT_FEET",
    "UNIT_METERS",
    "UNIT_TOKENS",
    "aws_three_tier",
    "build_fishbone",
    "build_floor_plan",
    "build_org_chart",
    "build_org_chart_from_csv",
    "build_process_map",
    "build_sipoc",
    "build_swim_lane_diagram",
    "diagram_from_xlsx",
    "from_plantuml",
    "from_plantuml_string",
    "erd_from_models",
    "erd_from_sql",
    "gantt_chart",
    "mind_map",
    "sequence_diagram",
    "uml_from_json_schema",
    "uml_from_python_module",
    "uml_from_typescript",
]
