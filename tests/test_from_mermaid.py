# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Behavioural tests for the Mermaid → vsdx import surface (issue #123).

Covers the three layers in turn:

* :func:`vsdx.mermaid.parse_mermaid` — pure parser → AST.
* :func:`vsdx.mermaid.build_from_mermaid` — AST → :class:`VisioDocument`.
* :meth:`VisioDocument.from_mermaid` /
  :meth:`VisioDocument.from_mermaid_string` — the public classmethod
  surface.

Test naming follows the loadfix family convention (``Describe*`` /
``it_*`` / ``they_*``); no docstrings on test methods.
"""

from __future__ import annotations

import textwrap

import pytest

from vsdx import VisioDocument
from vsdx.mermaid import (
    DEFAULT_GRID_COLUMNS,
    DIRECTION_LEFT_RIGHT,
    DIRECTION_TOP_DOWN,
    EDGE_STYLE_DASHED,
    EDGE_STYLE_PLAIN,
    EDGE_STYLE_SOLID,
    NODE_SHAPE_CIRCLE,
    NODE_SHAPE_DIAMOND,
    NODE_SHAPE_RECTANGLE,
    NODE_SHAPE_ROUNDED,
    MermaidEdge,
    MermaidFlowchart,
    MermaidNode,
    MermaidParseError,
    build_from_mermaid,
    parse_mermaid,
)


SAMPLE_FLOWCHART = textwrap.dedent(
    """\
    flowchart TD
        A[Start]
        A --> B(Process)
        B --> C{Decide}
        C -->|yes| D((End))
        C -.->|no| E[Other]
        E --- A
    """
)


class DescribeParseMermaid:
    def it_parses_the_direction_header(self):
        chart = parse_mermaid("flowchart TD\nA --> B\n")
        assert chart.direction == DIRECTION_TOP_DOWN

    def it_treats_TB_as_a_synonym_for_TD(self):
        chart = parse_mermaid("graph TB\nA --> B\n")
        assert chart.direction == DIRECTION_TOP_DOWN

    def it_accepts_LR_as_left_to_right(self):
        chart = parse_mermaid("flowchart LR\nA --> B\n")
        assert chart.direction == DIRECTION_LEFT_RIGHT

    def it_defaults_direction_to_top_down_when_unspecified(self):
        chart = parse_mermaid("flowchart\nA --> B\n")
        assert chart.direction == DIRECTION_TOP_DOWN

    def it_accepts_graph_as_a_header_keyword(self):
        chart = parse_mermaid("graph LR\nA --> B\n")
        assert chart.direction == DIRECTION_LEFT_RIGHT
        assert len(chart.edges) == 1

    def it_raises_when_no_header_is_present(self):
        with pytest.raises(MermaidParseError):
            parse_mermaid("A --> B\n")

    def it_skips_blank_lines_and_comments(self):
        src = textwrap.dedent(
            """\
            %% leading comment
            flowchart TD

                %% inline comment
                A --> B
            """
        )
        chart = parse_mermaid(src)
        assert len(chart.nodes) == 2
        assert len(chart.edges) == 1

    def it_strips_a_markdown_mermaid_fence(self):
        src = "```mermaid\nflowchart TD\nA --> B\n```\n"
        chart = parse_mermaid(src)
        assert len(chart.edges) == 1

    def it_silently_skips_style_directives(self):
        src = textwrap.dedent(
            """\
            flowchart TD
                A --> B
                style A fill:#f9f,stroke:#333,stroke-width:4px
                classDef big font-size:18px
                click A "https://example.com"
                linkStyle 0 stroke:red
            """
        )
        chart = parse_mermaid(src)
        assert len(chart.edges) == 1
        assert {n.id for n in chart.nodes} == {"A", "B"}


class DescribeNodeShapes:
    def it_parses_a_rectangle_node(self):
        chart = parse_mermaid("flowchart TD\nA[Rect Label]\n")
        assert chart.nodes[0].shape == NODE_SHAPE_RECTANGLE
        assert chart.nodes[0].label == "Rect Label"

    def it_parses_a_rounded_node(self):
        chart = parse_mermaid("flowchart TD\nA(Rounded)\n")
        assert chart.nodes[0].shape == NODE_SHAPE_ROUNDED
        assert chart.nodes[0].label == "Rounded"

    def it_parses_a_circle_node(self):
        chart = parse_mermaid("flowchart TD\nA((Circle))\n")
        assert chart.nodes[0].shape == NODE_SHAPE_CIRCLE
        assert chart.nodes[0].label == "Circle"

    def it_parses_a_diamond_node(self):
        chart = parse_mermaid("flowchart TD\nA{Diamond}\n")
        assert chart.nodes[0].shape == NODE_SHAPE_DIAMOND
        assert chart.nodes[0].label == "Diamond"

    def it_strips_optional_quotes_around_a_label(self):
        chart = parse_mermaid('flowchart TD\nA["Quoted"]\n')
        assert chart.nodes[0].label == "Quoted"

    def it_falls_back_to_the_id_when_no_label_is_given(self):
        chart = parse_mermaid("flowchart TD\nFooBar\n")
        assert chart.nodes[0].label == "FooBar"

    def it_upgrades_a_naked_node_when_a_later_appearance_is_richer(self):
        chart = parse_mermaid(
            "flowchart TD\nA --> B\nA[Anchor]\n"
        )
        node_a = chart.node_by_id("A")
        assert node_a is not None
        assert node_a.label == "Anchor"

    def it_raises_when_a_bracket_is_not_closed(self):
        with pytest.raises(MermaidParseError):
            parse_mermaid("flowchart TD\nA[Open\n")

    def it_raises_when_trailing_text_is_not_a_known_bracket(self):
        with pytest.raises(MermaidParseError):
            parse_mermaid("flowchart TD\nA<<\n")


class DescribeEdges:
    def it_parses_a_solid_arrow(self):
        chart = parse_mermaid("flowchart TD\nA --> B\n")
        assert chart.edges == [MermaidEdge("A", "B", EDGE_STYLE_SOLID)]

    def it_parses_a_plain_line(self):
        chart = parse_mermaid("flowchart TD\nA --- B\n")
        assert chart.edges[0].style == EDGE_STYLE_PLAIN

    def it_parses_a_dashed_arrow(self):
        chart = parse_mermaid("flowchart TD\nA -.-> B\n")
        assert chart.edges[0].style == EDGE_STYLE_DASHED

    def it_parses_an_inline_label(self):
        chart = parse_mermaid("flowchart TD\nA -->|hello world| B\n")
        assert chart.edges[0].label == "hello world"

    def it_parses_a_chained_edge(self):
        chart = parse_mermaid("flowchart TD\nA --> B --> C\n")
        assert [(e.source, e.target) for e in chart.edges] == [
            ("A", "B"),
            ("B", "C"),
        ]

    def it_carries_a_per_hop_label(self):
        chart = parse_mermaid(
            "flowchart TD\nA -->|first| B -->|second| C\n"
        )
        assert [e.label for e in chart.edges] == ["first", "second"]

    def it_raises_on_an_unclosed_pipe_label(self):
        with pytest.raises(MermaidParseError):
            parse_mermaid("flowchart TD\nA -->|broken B\n")

    def it_raises_when_an_edge_is_missing_a_side(self):
        with pytest.raises(MermaidParseError):
            parse_mermaid("flowchart TD\n--> B\n")


class DescribeSubgraphs:
    def it_records_subgraph_membership(self):
        src = textwrap.dedent(
            """\
            flowchart TD
                subgraph Tier
                    A --> B
                end
            """
        )
        chart = parse_mermaid(src)
        assert len(chart.subgraphs) == 1
        sg = chart.subgraphs[0]
        assert sg.title == "Tier"
        assert sorted(sg.node_ids) == ["A", "B"]

    def it_extracts_a_bracketed_subgraph_title(self):
        src = textwrap.dedent(
            """\
            flowchart TD
                subgraph t1 [Display Title]
                    A
                end
            """
        )
        chart = parse_mermaid(src)
        assert chart.subgraphs[0].title == "Display Title"

    def it_keeps_a_node_with_its_first_subgraph(self):
        src = textwrap.dedent(
            """\
            flowchart TD
                subgraph First
                    A
                end
                subgraph Second
                    A
                    B
                end
            """
        )
        chart = parse_mermaid(src)
        first = chart.subgraphs[0].node_ids
        second = chart.subgraphs[1].node_ids
        assert first == ["A"]
        assert second == ["B"]


class DescribeBuildFromMermaid:
    def it_returns_a_VisioDocument(self):
        doc = build_from_mermaid(SAMPLE_FLOWCHART)
        assert isinstance(doc, VisioDocument)

    def it_creates_one_page(self):
        doc = build_from_mermaid(SAMPLE_FLOWCHART)
        assert len(doc.pages) == 1

    def it_renders_every_node_as_a_shape(self):
        doc = build_from_mermaid(SAMPLE_FLOWCHART)
        page = doc.pages[0]
        # 5 unique node ids declared.
        non_connector = [
            s for s in page.shapes
            if s.master_name_u != "Dynamic connector"
        ]
        assert len(non_connector) == 5

    def it_renders_every_edge_as_a_dynamic_connector(self):
        doc = build_from_mermaid(SAMPLE_FLOWCHART)
        page = doc.pages[0]
        connectors = [
            s for s in page.shapes
            if s.master_name_u == "Dynamic connector"
        ]
        assert len(connectors) == 5

    def it_writes_edge_labels_onto_the_connector_text(self):
        doc = build_from_mermaid(SAMPLE_FLOWCHART)
        page = doc.pages[0]
        labels = sorted(
            s.text for s in page.shapes
            if s.master_name_u == "Dynamic connector" and s.text
        )
        assert "yes" in labels
        assert "no" in labels

    def it_renders_a_circle_node_with_an_ellipse_master(self):
        chart_src = "flowchart TD\nA((End))\n"
        doc = build_from_mermaid(chart_src)
        shapes = list(doc.pages[0].shapes)
        ellipses = [
            s for s in shapes if s.master_name_u == "Ellipse"
        ]
        assert len(ellipses) == 1

    def it_grids_nodes_into_a_default_5_column_layout(self):
        # Six nodes — first row 5, second row 1.
        nodes = "\n".join(f"N{i}" for i in range(6))
        doc = build_from_mermaid("flowchart TD\n" + nodes + "\n")
        page = doc.pages[0]
        non_connector = [
            s for s in page.shapes
            if s.master_name_u != "Dynamic connector"
        ]
        # Row 1: N0..N4 share the same y; N5 sits one row below.
        ys = [round(float(s.pin_y), 3) for s in non_connector]
        assert ys[:DEFAULT_GRID_COLUMNS] == [ys[0]] * DEFAULT_GRID_COLUMNS
        assert ys[DEFAULT_GRID_COLUMNS] != ys[0]

    def it_grows_the_page_to_fit_a_wide_grid(self):
        # 30 nodes — wider than the 8.5-inch default page.
        nodes = "\n".join(f"N{i}" for i in range(30))
        doc = build_from_mermaid(
            "flowchart TD\n" + nodes + "\n", columns=10
        )
        page = doc.pages[0]
        # Default page width is 8.5"; 10 cols × 2.0" cell ≈ 22" plus
        # margins, so the page must be wider than the default to fit.
        assert float(page.width) > 8.5

    def it_honours_a_custom_columns_argument(self):
        # 4 nodes laid out in 2 columns yields a 2x2 grid.
        nodes = "\n".join(f"N{i}" for i in range(4))
        doc = build_from_mermaid(
            "flowchart TD\n" + nodes + "\n", columns=2
        )
        page = doc.pages[0]
        non_connector = [
            s for s in page.shapes
            if s.master_name_u != "Dynamic connector"
        ]
        # The first two nodes should share a y; the last two share a
        # different y.
        ys = [round(float(s.pin_y), 3) for s in non_connector]
        assert ys[0] == ys[1]
        assert ys[2] == ys[3]
        assert ys[0] != ys[2]

    def it_honours_a_custom_page_name(self):
        doc = build_from_mermaid(
            SAMPLE_FLOWCHART, page_name="Imported"
        )
        assert doc.pages[0].name == "Imported"

    def it_marks_a_dashed_edge_with_LinePattern_2(self):
        doc = build_from_mermaid("flowchart TD\nA -.-> B\n")
        connector = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ][0]
        cell = connector._get_cell("LinePattern")
        assert cell is not None
        assert cell.get("V") == "2"

    def it_marks_a_plain_edge_with_no_arrow(self):
        doc = build_from_mermaid("flowchart TD\nA --- B\n")
        connector = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ][0]
        cell = connector._get_cell("EndArrow")
        assert cell is not None
        assert cell.get("V") == "0"


class DescribeFromMermaidClassmethods:
    def it_reads_a_mermaid_file_via_from_mermaid(self, tmp_path):
        src = tmp_path / "flow.mmd"
        src.write_text(SAMPLE_FLOWCHART, encoding="utf-8")
        doc = VisioDocument.from_mermaid(str(src))
        assert isinstance(doc, VisioDocument)
        assert len(doc.pages) == 1

    def it_accepts_a_pathlib_path(self, tmp_path):
        src = tmp_path / "flow.mmd"
        src.write_text(SAMPLE_FLOWCHART, encoding="utf-8")
        doc = VisioDocument.from_mermaid(src)
        assert len(doc.pages) == 1

    def it_reads_an_inline_string_via_from_mermaid_string(self):
        doc = VisioDocument.from_mermaid_string(SAMPLE_FLOWCHART)
        assert len(doc.pages) == 1

    def it_round_trips_via_save_to_a_BytesIO(self, tmp_path):
        import io as _io

        doc = VisioDocument.from_mermaid_string(SAMPLE_FLOWCHART)
        buf = _io.BytesIO()
        doc.save(buf)
        # The saved zip must start with the standard PK header.
        assert buf.getvalue()[:2] == b"PK"

    def it_propagates_the_page_name_to_the_classmethod(self):
        doc = VisioDocument.from_mermaid_string(
            SAMPLE_FLOWCHART, page_name="Custom"
        )
        assert doc.pages[0].name == "Custom"

    def it_raises_MermaidParseError_on_a_non_flowchart_source(self):
        with pytest.raises(MermaidParseError):
            VisioDocument.from_mermaid_string("sequenceDiagram\nA->>B: ping\n")

    def it_renders_a_subgraph_as_a_container(self):
        src = textwrap.dedent(
            """\
            flowchart TD
                subgraph Tier
                    A --> B
                end
            """
        )
        doc = build_from_mermaid(src)
        # Container shapes carry the subgraph title in their text.
        titles = [s.text for s in doc.pages[0].shapes if s.text == "Tier"]
        assert titles == ["Tier"]


class DescribeMermaidFlowchart:
    def it_iterates_nodes_and_edges_in_declaration_order(self):
        chart = parse_mermaid(SAMPLE_FLOWCHART)
        ids = [n.id for n in chart.nodes]
        assert ids == ["A", "B", "C", "D", "E"]
        edge_pairs = [(e.source, e.target) for e in chart.edges]
        assert edge_pairs == [
            ("A", "B"), ("B", "C"), ("C", "D"), ("C", "E"), ("E", "A"),
        ]

    def it_node_by_id_returns_None_for_an_unknown_id(self):
        chart = MermaidFlowchart()
        chart.nodes.append(MermaidNode(id="A", label="A"))
        assert chart.node_by_id("A") is not None
        assert chart.node_by_id("Z") is None
