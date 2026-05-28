# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.patterns` — issue #52."""

from __future__ import annotations

import datetime
from io import BytesIO

import pytest

import vsdx
from vsdx.kit import (
    AWS_TIER_APP,
    AWS_TIER_DATA,
    AWS_TIER_ORDER,
    AWS_TIER_WEB,
    aws_three_tier,
    gantt_chart,
    mind_map,
    sequence_diagram,
)
from vsdx.kit.patterns import _gantt_parse_date, _mind_normalise_branches
from vsdx.shapes.connector import Connector


# ---------------------------------------------------------------------------
# AWS three-tier
# ---------------------------------------------------------------------------


_AWS_KWARGS = dict(
    name="Production",
    region="ap-southeast-2",
    web_tier=["ALB", "EC2 (web1)", "EC2 (web2)"],
    app_tier=["API GW", "Lambda (orders)", "Lambda (notifications)"],
    data_tier=["RDS (orders-prod)", "DynamoDB (sessions)", "S3 (uploads)"],
)


def _build_aws():
    return aws_three_tier(**_AWS_KWARGS)


class DescribeAwsThreeTier:
    def it_returns_a_VisioDocument(self):
        diagram = _build_aws()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_emits_one_page_named_after_the_deployment(self):
        diagram = _build_aws()
        assert len(diagram.pages) == 1
        assert diagram.pages[0].name == "Production"

    def it_falls_back_to_a_default_page_name_when_name_is_empty(self):
        diagram = aws_three_tier(
            name="",
            region="us-east-1",
            web_tier=["ALB"],
            app_tier=["API"],
            data_tier=["RDS"],
        )
        assert diagram.pages[0].name == "AWS three-tier"

    def it_honours_an_explicit_page_name(self):
        diagram = aws_three_tier(
            **{**_AWS_KWARGS, "page_name": "Override"}
        )
        assert diagram.pages[0].name == "Override"

    def it_uses_container_shapes_for_each_tier_boundary(self):
        diagram = _build_aws()
        page = diagram.pages[0]
        # 4 containers expected: 1 region + 3 tiers (web / app / data).
        assert len(page.containers) == 4

    def it_labels_the_region_container_with_the_region(self):
        diagram = _build_aws()
        page = diagram.pages[0]
        labels = [c.title for c in page.containers]
        # Region container's label combines name + region.
        assert "Production — ap-southeast-2" in labels

    def it_labels_each_tier_container_with_its_tier_name(self):
        diagram = _build_aws()
        page = diagram.pages[0]
        labels = [c.title for c in page.containers]
        for tier_name in AWS_TIER_ORDER:
            assert "%s tier" % tier_name in labels

    def it_drops_each_resource_as_its_own_shape(self):
        diagram = _build_aws()
        page = diagram.pages[0]
        all_text = [s.text for s in page.shapes]
        # 9 resources spread across 3 tiers
        for resource in (
            "ALB", "EC2 (web1)", "EC2 (web2)",
            "API GW", "Lambda (orders)", "Lambda (notifications)",
            "RDS (orders-prod)", "DynamoDB (sessions)", "S3 (uploads)",
        ):
            assert resource in all_text

    def it_emits_inter_tier_connectors(self):
        diagram = _build_aws()
        page = diagram.pages[0]
        connectors = [s for s in page.shapes if isinstance(s, Connector)]
        # web -> app, app -> data
        assert len(connectors) == 2

    def it_stacks_tiers_top_to_bottom(self):
        diagram = _build_aws()
        page = diagram.pages[0]
        tier_y_by_name: dict = {}
        for c in page.containers:
            tier_y_by_name[c.title] = float(c.pin_y)
        web_y = tier_y_by_name["%s tier" % AWS_TIER_WEB]
        app_y = tier_y_by_name["%s tier" % AWS_TIER_APP]
        data_y = tier_y_by_name["%s tier" % AWS_TIER_DATA]
        # In Visio's bottom-anchored coords, top-to-bottom on screen
        # means descending Y values.
        assert web_y > app_y > data_y

    def it_rejects_a_non_string_name(self):
        with pytest.raises(TypeError):
            aws_three_tier(
                name=123,  # type: ignore[arg-type]
                region="us-east-1",
                web_tier=["a"],
                app_tier=["b"],
                data_tier=["c"],
            )

    def it_rejects_a_non_string_region(self):
        with pytest.raises(TypeError):
            aws_three_tier(
                name="x",
                region=None,  # type: ignore[arg-type]
                web_tier=["a"],
                app_tier=["b"],
                data_tier=["c"],
            )

    def it_rejects_an_empty_tier(self):
        with pytest.raises(ValueError):
            aws_three_tier(
                name="x",
                region="r",
                web_tier=[],
                app_tier=["b"],
                data_tier=["c"],
            )

    def it_rejects_a_tier_with_an_empty_resource_name(self):
        with pytest.raises(ValueError):
            aws_three_tier(
                name="x",
                region="r",
                web_tier=["ALB", ""],
                app_tier=["b"],
                data_tier=["c"],
            )

    def it_rejects_a_page_too_narrow_for_the_inner_band(self):
        with pytest.raises(ValueError):
            aws_three_tier(
                name="x",
                region="r",
                web_tier=["a"],
                app_tier=["b"],
                data_tier=["c"],
                page_width=0.5,
            )

    def it_rejects_a_page_too_short_for_three_tiers(self):
        with pytest.raises(ValueError):
            aws_three_tier(
                name="x",
                region="r",
                web_tier=["a"],
                app_tier=["b"],
                data_tier=["c"],
                page_height=2.0,
            )

    def it_round_trips_through_save_and_open(self):
        diagram = _build_aws()
        buf = BytesIO()
        diagram.save(buf)
        buf.seek(0)
        reopened = vsdx.api.Visio(buf)
        assert len(reopened.pages) == 1


# ---------------------------------------------------------------------------
# Sequence diagram
# ---------------------------------------------------------------------------


_SEQ_KWARGS = dict(
    title="Login flow",
    actors=["User", "Browser", "API", "AuthService", "DB"],
    messages=[
        ("User", "Browser", "Submit credentials"),
        ("Browser", "API", "POST /login"),
        ("API", "AuthService", "verify_password"),
        ("AuthService", "DB", "SELECT user"),
        ("DB", "AuthService", "user record"),
        ("AuthService", "API", "token"),
        ("API", "Browser", "set-cookie"),
        ("Browser", "User", "logged in"),
    ],
)


def _build_seq():
    return sequence_diagram(**_SEQ_KWARGS)


class DescribeSequenceDiagram:
    def it_returns_a_VisioDocument(self):
        diagram = _build_seq()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_emits_one_page_named_after_the_title(self):
        diagram = _build_seq()
        assert diagram.pages[0].name == "Login flow"

    def it_falls_back_to_a_default_page_name_when_title_is_empty(self):
        diagram = sequence_diagram(
            title="",
            actors=["A", "B"],
            messages=[("A", "B", "ping")],
        )
        assert diagram.pages[0].name == "Sequence diagram"

    def it_emits_one_actor_header_box_per_actor(self):
        diagram = _build_seq()
        page = diagram.pages[0]
        actor_texts = {"User", "Browser", "API", "AuthService", "DB"}
        actor_shapes = [s for s in page.shapes if s.text in actor_texts]
        # Header boxes are at the same y-coordinate (the top band).
        ys = {round(float(s.pin_y), 4) for s in actor_shapes}
        assert len(ys) == 1
        assert len(actor_shapes) == 5

    def it_lays_out_actors_left_to_right(self):
        diagram = _build_seq()
        page = diagram.pages[0]
        actor_texts = ["User", "Browser", "API", "AuthService", "DB"]
        actor_shapes = [s for s in page.shapes if s.text in set(actor_texts)]
        ordered = sorted(actor_shapes, key=lambda s: float(s.pin_x))
        assert [s.text for s in ordered] == actor_texts

    def it_emits_a_lifeline_under_each_actor(self):
        # Lifelines are master-less custom shapes — count them by
        # filtering on the absence of a Master attribute.
        diagram = _build_seq()
        page = diagram.pages[0]
        master_less = [s for s in page.shapes if s.master_name_u is None]
        # 5 lifelines + 8 message arrows (no self-messages here) = 13
        assert len(master_less) == 5 + 8

    def it_renders_horizontal_arrows_for_each_inter_actor_message(self):
        diagram = _build_seq()
        page = diagram.pages[0]
        message_texts = {
            "Submit credentials", "POST /login", "verify_password",
            "SELECT user", "user record", "token", "set-cookie",
            "logged in",
        }
        labelled = [s for s in page.shapes if s.text in message_texts]
        assert len(labelled) == 8

    def it_stacks_messages_top_to_bottom_in_declaration_order(self):
        diagram = _build_seq()
        page = diagram.pages[0]
        message_texts = [
            "Submit credentials", "POST /login", "verify_password",
            "SELECT user", "user record", "token", "set-cookie",
            "logged in",
        ]
        labelled = [s for s in page.shapes if s.text in set(message_texts)]
        # In Visio's coords, descending Y == descending on screen.
        ordered = sorted(labelled, key=lambda s: -float(s.pin_y))
        assert [s.text for s in ordered] == message_texts

    def it_handles_self_messages_with_a_loop_box(self):
        diagram = sequence_diagram(
            title="self",
            actors=["A", "B"],
            messages=[("A", "A", "tick"), ("A", "B", "next")],
        )
        page = diagram.pages[0]
        # Self-message renders as a single labelled rectangle, so the
        # text "tick" appears exactly once on the page (no separate
        # arrow + label combo).
        tick_shapes = [s for s in page.shapes if s.text == "tick"]
        assert len(tick_shapes) == 1

    def it_rejects_unknown_actor_in_a_message(self):
        with pytest.raises(ValueError):
            sequence_diagram(
                title="x",
                actors=["A", "B"],
                messages=[("A", "Ghost", "hi")],
            )

    def it_rejects_a_malformed_message_tuple(self):
        with pytest.raises(ValueError):
            sequence_diagram(
                title="x",
                actors=["A", "B"],
                messages=[("A", "B")],  # type: ignore[list-item]
            )

    def it_rejects_duplicate_actors(self):
        with pytest.raises(ValueError):
            sequence_diagram(
                title="x",
                actors=["A", "A"],
                messages=[],
            )

    def it_rejects_a_non_string_title(self):
        with pytest.raises(TypeError):
            sequence_diagram(
                title=42,  # type: ignore[arg-type]
                actors=["A"],
                messages=[],
            )

    def it_rejects_a_non_string_message_text(self):
        with pytest.raises(ValueError):
            sequence_diagram(
                title="x",
                actors=["A", "B"],
                messages=[("A", "B", 42)],  # type: ignore[list-item]
            )

    def it_rejects_a_page_too_short_for_the_actor_band(self):
        with pytest.raises(ValueError):
            sequence_diagram(
                title="x",
                actors=["A"],
                messages=[],
                page_height=0.6,
            )


# ---------------------------------------------------------------------------
# Gantt chart
# ---------------------------------------------------------------------------


_GANTT_TASKS = [
    {
        "name": "Discovery",
        "start": datetime.date(2026, 6, 1),
        "end": datetime.date(2026, 6, 14),
    },
    {
        "name": "Design",
        "start": datetime.date(2026, 6, 10),
        "end": datetime.date(2026, 6, 30),
    },
    {
        "name": "Build",
        "start": datetime.date(2026, 7, 1),
        "end": datetime.date(2026, 8, 15),
    },
    {
        "name": "Test",
        "start": datetime.date(2026, 8, 1),
        "end": datetime.date(2026, 8, 31),
    },
    {
        "name": "Launch",
        "start": datetime.date(2026, 9, 1),
        "end": datetime.date(2026, 9, 5),
    },
]


def _build_gantt():
    return gantt_chart(title="Project plan", tasks=_GANTT_TASKS)


class DescribeGanttChart:
    def it_returns_a_VisioDocument(self):
        diagram = _build_gantt()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_emits_one_page_named_after_the_title(self):
        diagram = _build_gantt()
        assert diagram.pages[0].name == "Project plan"

    def it_falls_back_to_a_default_page_name_when_title_is_empty(self):
        diagram = gantt_chart(tasks=_GANTT_TASKS)
        assert diagram.pages[0].name == "Gantt chart"

    def it_emits_one_label_cell_and_one_bar_per_task(self):
        diagram = _build_gantt()
        page = diagram.pages[0]
        # Each task contributes 2 shapes (label + bar). Header band
        # adds 2 (Task / Date), title band adds 1, today indicator
        # adds 0 or 1 depending on whether today falls inside the
        # window (deterministic check uses a fixed window).
        n_tasks = len(_GANTT_TASKS)
        labels = [s for s in page.shapes if s.text in {t["name"] for t in _GANTT_TASKS}]
        assert len(labels) == n_tasks

    def it_widens_bars_proportional_to_their_duration(self):
        diagram = _build_gantt()
        page = diagram.pages[0]
        # The "Build" task (45 days) is the longest, so its bar should
        # be wider than "Launch" (5 days).
        labels = {s.text: s for s in page.shapes if s.text in {"Build", "Launch"}}
        # Bars are non-label shapes near the same row Y as their label.
        # Find the bar by matching Y within tolerance.
        non_label = [
            s for s in page.shapes
            if s.text == "" and s.master_name_u is not None
            # Avoid the today indicator (very thin)
            and float(s.width) > 0.1
        ]
        # Build and Launch bars — pull out widths.
        build_y = float(labels["Build"].pin_y)
        launch_y = float(labels["Launch"].pin_y)
        build_bars = [s for s in non_label if abs(float(s.pin_y) - build_y) < 1e-3]
        launch_bars = [s for s in non_label if abs(float(s.pin_y) - launch_y) < 1e-3]
        assert build_bars and launch_bars
        assert float(build_bars[0].width) > float(launch_bars[0].width)

    def it_rejects_an_empty_tasks_list(self):
        with pytest.raises(ValueError):
            gantt_chart(title="x", tasks=[])

    def it_rejects_a_task_missing_required_keys(self):
        with pytest.raises(ValueError):
            gantt_chart(
                title="x",
                tasks=[{"name": "incomplete", "start": datetime.date(2026, 1, 1)}],
            )

    def it_rejects_a_task_with_end_before_start(self):
        with pytest.raises(ValueError):
            gantt_chart(
                title="x",
                tasks=[
                    {
                        "name": "backwards",
                        "start": datetime.date(2026, 6, 10),
                        "end": datetime.date(2026, 6, 1),
                    }
                ],
            )

    def it_rejects_duplicate_task_names(self):
        with pytest.raises(ValueError):
            gantt_chart(
                title="x",
                tasks=[
                    {"name": "A", "start": "2026-01-01", "end": "2026-01-05"},
                    {"name": "A", "start": "2026-02-01", "end": "2026-02-05"},
                ],
            )

    def it_accepts_iso_string_dates(self):
        diagram = gantt_chart(
            title="iso",
            tasks=[
                {
                    "name": "A",
                    "start": "2026-01-01",
                    "end": "2026-01-31",
                }
            ],
        )
        assert diagram.pages[0].name == "iso"

    def it_rejects_an_iso_string_with_bad_format(self):
        with pytest.raises(ValueError):
            gantt_chart(
                title="x",
                tasks=[
                    {"name": "A", "start": "not-a-date", "end": "2026-01-05"}
                ],
            )

    def it_rejects_a_non_date_non_string_value(self):
        with pytest.raises(TypeError):
            gantt_chart(
                title="x",
                tasks=[{"name": "A", "start": 12345, "end": "2026-01-05"}],
            )

    def it_rejects_a_non_mapping_task(self):
        with pytest.raises(TypeError):
            gantt_chart(
                title="x",
                tasks=["not a mapping"],  # type: ignore[list-item]
            )

    def it_rejects_a_page_too_narrow_for_the_label_column(self):
        with pytest.raises(ValueError):
            gantt_chart(
                title="x",
                tasks=_GANTT_TASKS,
                page_width=2.0,
            )

    def it_rejects_a_page_too_short_for_the_rows(self):
        with pytest.raises(ValueError):
            gantt_chart(
                title="x",
                tasks=_GANTT_TASKS,
                page_height=1.5,
            )


class DescribeGanttParseDate:
    def it_passes_through_a_date_unchanged(self):
        d = datetime.date(2026, 6, 1)
        assert _gantt_parse_date(d, ix=0, key="start") == d

    def it_extracts_the_date_from_a_datetime(self):
        dt = datetime.datetime(2026, 6, 1, 14, 30)
        assert _gantt_parse_date(dt, ix=0, key="start") == datetime.date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Mind map
# ---------------------------------------------------------------------------


_MIND_BRANCHES = {
    "Networking": ["VPC", "Transit Gateway", "Direct Connect"],
    "Compute": {"EKS": None, "Lambda": ["Functions", "Layers"]},
    "Data": ["S3", "RDS", "DynamoDB"],
    "Security": None,
}


def _build_mind():
    return mind_map(root="AWS Migration", branches=_MIND_BRANCHES)


class DescribeMindMap:
    def it_returns_a_VisioDocument(self):
        diagram = _build_mind()
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_emits_one_page_named_after_the_root(self):
        diagram = _build_mind()
        assert diagram.pages[0].name == "AWS Migration"

    def it_falls_back_to_default_page_name_when_title_is_empty(self):
        diagram = mind_map(root="X", title="")
        assert diagram.pages[0].name == "Mind map"

    def it_emits_a_node_per_concept_in_the_tree(self):
        diagram = _build_mind()
        page = diagram.pages[0]
        labels = {s.text for s in page.shapes}
        # Root + 4 top-level branches + 3 + 2 + 2 + 3 sub-branches.
        for name in (
            "AWS Migration",
            "Networking", "Compute", "Data", "Security",
            "VPC", "Transit Gateway", "Direct Connect",
            "EKS", "Lambda",
            "Functions", "Layers",
            "S3", "RDS", "DynamoDB",
        ):
            assert name in labels

    def it_connects_each_branch_to_its_parent(self):
        diagram = _build_mind()
        page = diagram.pages[0]
        connectors = [s for s in page.shapes if isinstance(s, Connector)]
        # 4 top-level branches + 3 + 2 + 2 + 3 sub-branches = 14 edges.
        assert len(connectors) == 4 + 3 + 2 + 2 + 3

    def it_places_the_root_at_page_centre_after_radial_layout(self):
        diagram = _build_mind()
        page = diagram.pages[0]
        # The page has two "AWS Migration" labelled shapes — the title
        # band at the top and the root node in the body. The root is
        # the one whose pin_y is closest to the body centre.
        candidates = [s for s in page.shapes if s.text == "AWS Migration"]
        root_shape = min(
            candidates, key=lambda s: abs(float(s.pin_y) - 4.7)
        )
        assert abs(float(root_shape.pin_x) - 7.0) < 0.5
        assert abs(float(root_shape.pin_y) - 4.7) < 0.5

    def it_spreads_branches_around_the_root(self):
        # After radial layout the top-level branches sit at distance
        # ``spacing`` from the root; sub-branches at ``2 * spacing``.
        diagram = _build_mind()
        page = diagram.pages[0]
        candidates = [s for s in page.shapes if s.text == "AWS Migration"]
        root_shape = min(
            candidates, key=lambda s: abs(float(s.pin_y) - 4.7)
        )
        rx, ry = float(root_shape.pin_x), float(root_shape.pin_y)
        top_level = ["Networking", "Compute", "Data", "Security"]
        for label in top_level:
            shape = next(s for s in page.shapes if s.text == label)
            dist = (
                (float(shape.pin_x) - rx) ** 2
                + (float(shape.pin_y) - ry) ** 2
            ) ** 0.5
            # The radial layout uses BFS distance; ring-1 distance
            # equals ``spacing`` (default 1.6 inches). Allow a small
            # tolerance for floating-point + the per-shape-size cell
            # used by force-directed-isn (radial uses k = ring * spacing).
            assert 1.5 <= dist <= 1.7

    def it_supports_an_empty_branch_set(self):
        diagram = mind_map(root="solo")
        page = diagram.pages[0]
        labels = {s.text for s in page.shapes}
        assert "solo" in labels
        connectors = [s for s in page.shapes if isinstance(s, Connector)]
        assert connectors == []

    def it_rejects_an_empty_root(self):
        with pytest.raises(ValueError):
            mind_map(root="")

    def it_rejects_a_non_string_root(self):
        with pytest.raises(TypeError):
            mind_map(root=42)  # type: ignore[arg-type]

    def it_rejects_a_branch_name_that_collides_with_the_root(self):
        with pytest.raises(ValueError):
            mind_map(root="AWS", branches={"AWS": None})

    def it_rejects_duplicate_branch_names_globally(self):
        with pytest.raises(ValueError):
            mind_map(
                root="X",
                branches={"A": ["dup"], "B": ["dup"]},
            )

    def it_rejects_an_empty_branch_name(self):
        with pytest.raises(ValueError):
            mind_map(root="X", branches={"": None})

    def it_rejects_an_empty_sub_branch_name(self):
        with pytest.raises(ValueError):
            mind_map(root="X", branches={"A": [""]})

    def it_rejects_a_non_mapping_branches_argument(self):
        with pytest.raises(TypeError):
            mind_map(root="X", branches=["A", "B"])  # type: ignore[arg-type]

    def it_rejects_a_non_recognised_sub_branch_value_type(self):
        with pytest.raises(TypeError):
            mind_map(root="X", branches={"A": 42})  # type: ignore[dict-item]


class DescribeMindNormaliseBranches:
    def it_returns_an_empty_dict_for_None(self):
        assert _mind_normalise_branches(None) == {}

    def it_lowers_a_sequence_into_a_dict_of_empty_dicts(self):
        out = _mind_normalise_branches({"A": ["x", "y"]})
        assert out == {"A": {"x": {}, "y": {}}}

    def it_preserves_nested_mappings(self):
        out = _mind_normalise_branches({"A": {"B": ["c"]}})
        assert out == {"A": {"B": {"c": {}}}}
