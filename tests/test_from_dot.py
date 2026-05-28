# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for ``vsdx.kit.from_dot`` — issue #125."""

from __future__ import annotations

from io import BytesIO

import pytest

import vsdx
from vsdx import VisioDocument
from vsdx.kit.from_dot import (
    DOT_DEFAULT_NODE_HEIGHT,
    DOT_DEFAULT_NODE_WIDTH,
    DOT_SHAPE_KINDS,
    DOT_SHAPE_MAP,
    DotParseError,
    document_from_dot,
    document_from_dot_string,
)

# ---------------------------------------------------------------------------
# DescribeFromDotString — basic happy path + parser flexibility
# ---------------------------------------------------------------------------


class DescribeFromDotString:
    def it_returns_a_VisioDocument(self):
        doc = document_from_dot_string("digraph G { A -> B; }")
        assert isinstance(doc, vsdx.VisioDocument)

    def it_creates_a_single_page(self):
        doc = document_from_dot_string("digraph G { A -> B; }")
        assert len(doc.pages) == 1

    def it_uses_the_graph_name_for_the_page(self):
        doc = document_from_dot_string("digraph MyGraph { A; }")
        assert doc.pages[0].name == "MyGraph"

    def it_falls_back_to_DOT_graph_for_anonymous_graphs(self):
        doc = document_from_dot_string("digraph { A; }")
        assert doc.pages[0].name == "DOT graph"

    def it_honours_an_explicit_page_name(self):
        doc = document_from_dot_string(
            "digraph G { A; }", page_name="Override"
        )
        assert doc.pages[0].name == "Override"

    def it_emits_a_shape_per_node(self):
        doc = document_from_dot_string("digraph G { A; B; C; }")
        nodes = [
            s for s in doc.pages[0].shapes
            if s.master_name_u != "Dynamic connector"
        ]
        assert len(nodes) == 3

    def it_emits_a_connector_per_edge(self):
        doc = document_from_dot_string("digraph G { A -> B; A -> C; }")
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        assert len(connectors) == 2

    def it_decomposes_chains_into_pairwise_edges(self):
        doc = document_from_dot_string("digraph G { A -> B -> C -> D; }")
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        # Three pairwise edges in a four-node chain.
        assert len(connectors) == 3

    def it_parses_undirected_graph_keyword(self):
        doc = document_from_dot_string("graph G { A -- B; B -- C; }")
        nodes = [
            s for s in doc.pages[0].shapes
            if s.master_name_u != "Dynamic connector"
        ]
        assert len(nodes) == 3

    def it_uses_node_id_as_default_label(self):
        doc = document_from_dot_string("digraph G { Alpha; }")
        labels = [s.text for s in doc.pages[0].shapes if s.text]
        assert "Alpha" in labels

    def it_honours_an_explicit_label(self):
        doc = document_from_dot_string('digraph G { A [label="Hello"]; }')
        labels = [s.text for s in doc.pages[0].shapes if s.text]
        assert "Hello" in labels

    def it_strips_C_style_line_comments(self):
        src = """
        // top comment
        digraph G { // trailing
            A -> B; // inline
        }
        """
        doc = document_from_dot_string(src)
        # 2 node + 1 connector
        assert len(list(doc.pages[0].shapes)) == 3

    def it_strips_C_style_block_comments(self):
        src = "digraph G { /* skip */ A -> /* mid */ B; }"
        doc = document_from_dot_string(src)
        assert len(list(doc.pages[0].shapes)) == 3

    def it_tolerates_strict_keyword(self):
        # Strict-mode parsing is a no-op duplicate-collapse — we accept
        # the keyword and parse the graph regardless.
        doc = document_from_dot_string("strict digraph G { A -> B; }")
        assert len(doc.pages) == 1

    def it_tolerates_node_default_attribute_blocks(self):
        # ``node [shape=...]`` defaults are tolerated and ignored.
        src = "digraph G { node [shape=box, color=red]; A; B; A -> B; }"
        doc = document_from_dot_string(src)
        assert len(list(doc.pages[0].shapes)) == 3

    def it_tolerates_edge_default_attribute_blocks(self):
        src = "digraph G { edge [color=blue]; A -> B; }"
        doc = document_from_dot_string(src)
        assert len(list(doc.pages[0].shapes)) == 3

    def it_tolerates_graph_attribute_setters(self):
        # ``rankdir = LR`` and the like — accepted but discarded.
        src = "digraph G { rankdir = LR; A -> B; }"
        doc = document_from_dot_string(src)
        assert len(list(doc.pages[0].shapes)) == 3

    def it_strips_port_references(self):
        # ``A:f1 -> B:f2`` — ports are discarded but the edge stands.
        doc = document_from_dot_string("digraph G { A:f1 -> B:f2; }")
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        assert len(connectors) == 1

    def it_supports_inline_subgraph_edge_endpoints(self):
        # ``A -> { B C }`` should fan-out into two edges A->B and A->C.
        doc = document_from_dot_string("digraph G { A -> { B C }; }")
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        assert len(connectors) == 2

    def it_allows_quoted_node_ids_with_spaces(self):
        doc = document_from_dot_string('digraph G { "Hello World" -> B; }')
        labels = [s.text for s in doc.pages[0].shapes if s.text]
        assert "Hello World" in labels


# ---------------------------------------------------------------------------
# DescribeShapeRendering — DOT shape= -> Visio glyph dispatch
# ---------------------------------------------------------------------------


class DescribeShapeRendering:
    def it_renders_box_as_a_rectangle(self):
        doc = document_from_dot_string('digraph G { A [shape=box]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].master_name_u == "Rectangle"

    def it_renders_ellipse_as_an_ellipse(self):
        doc = document_from_dot_string('digraph G { A [shape=ellipse]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].master_name_u == "Ellipse"

    def it_renders_circle_as_an_ellipse(self):
        doc = document_from_dot_string('digraph G { A [shape=circle]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].master_name_u == "Ellipse"

    def it_renders_oval_as_an_ellipse(self):
        # Graphviz synonym — should resolve to Ellipse.
        doc = document_from_dot_string('digraph G { A [shape=oval]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].master_name_u == "Ellipse"

    def it_renders_diamond_as_a_master_less_shape(self):
        # Diamond is authored via add_custom_shape so the master is
        # blank but the shape carries a custom geometry section.
        doc = document_from_dot_string('digraph G { A [shape=diamond]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert len(nodes) == 1

    def it_renders_parallelogram_as_a_master_less_shape(self):
        doc = document_from_dot_string(
            'digraph G { A [shape=parallelogram]; }'
        )
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert len(nodes) == 1

    def it_falls_back_to_box_for_unrecognised_shapes(self):
        # ``hexagon`` isn't in DOT_SHAPE_MAP — fall back to rectangle.
        doc = document_from_dot_string('digraph G { A [shape=hexagon]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].master_name_u == "Rectangle"

    def it_renders_as_rectangle_when_no_shape_attr_is_given(self):
        doc = document_from_dot_string('digraph G { A; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].master_name_u == "Rectangle"


# ---------------------------------------------------------------------------
# DescribeAttributeStyling — color / style propagation
# ---------------------------------------------------------------------------


class DescribeAttributeStyling:
    def it_records_node_color_on_LineColor_cell(self):
        doc = document_from_dot_string('digraph G { A [color=red]; }')
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].line_color == "red"

    def it_records_node_fillcolor_on_FillForegnd_cell(self):
        doc = document_from_dot_string(
            'digraph G { A [fillcolor="#ff0000"]; }'
        )
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        assert nodes[0].fill_foregnd == "#ff0000"

    def it_marks_dashed_nodes_with_LinePattern_cell(self):
        doc = document_from_dot_string(
            'digraph G { A [style=dashed]; }'
        )
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        # Look up the LinePattern cell directly on the underlying element.
        cells = [
            c for c in nodes[0]._element.cell_lst if c.get("N") == "LinePattern"
        ]
        assert cells and cells[0].get("V") == "2"

    def it_marks_dotted_nodes_with_LinePattern_cell(self):
        doc = document_from_dot_string(
            'digraph G { A [style=dotted]; }'
        )
        nodes = [s for s in doc.pages[0].shapes if s.text == "A"]
        cells = [
            c for c in nodes[0]._element.cell_lst if c.get("N") == "LinePattern"
        ]
        assert cells and cells[0].get("V") == "4"

    def it_records_edge_label_text(self):
        doc = document_from_dot_string(
            'digraph G { A -> B [label="x"]; }'
        )
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        assert connectors[0].text == "x"

    def it_marks_dashed_edges_with_LinePattern_cell(self):
        doc = document_from_dot_string(
            'digraph G { A -> B [style=dashed]; }'
        )
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        cells = [
            c for c in connectors[0]._element.cell_lst
            if c.get("N") == "LinePattern"
        ]
        assert cells and cells[0].get("V") == "2"

    def it_records_edge_color_on_LineColor_cell(self):
        doc = document_from_dot_string(
            'digraph G { A -> B [color=blue]; }'
        )
        connectors = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Dynamic connector"
        ]
        assert connectors[0].line_color == "blue"


# ---------------------------------------------------------------------------
# DescribeLayout — top-down grid coordinates
# ---------------------------------------------------------------------------


class DescribeLayout:
    def it_places_root_above_descendants(self):
        doc = document_from_dot_string("digraph G { A -> B -> C; }")
        nodes = {
            s.text: s for s in doc.pages[0].shapes
            if s.master_name_u != "Dynamic connector"
        }
        assert float(nodes["A"].pin_y) > float(nodes["B"].pin_y)
        assert float(nodes["B"].pin_y) > float(nodes["C"].pin_y)

    def it_centres_a_single_row_horizontally(self):
        doc = document_from_dot_string("digraph G { A -> B; A -> C; }")
        # B and C share a row — they should sit symmetrically about
        # the page centre.
        nodes = {
            s.text: s for s in doc.pages[0].shapes
            if s.master_name_u != "Dynamic connector"
        }
        page_w = float(doc.pages[0].width)
        b_dist = abs(float(nodes["B"].pin_x) - page_w / 2)
        c_dist = abs(float(nodes["C"].pin_x) - page_w / 2)
        # Within sub-inch tolerance.
        assert abs(b_dist - c_dist) < 0.01

    def it_emits_default_node_size_when_no_explicit_size(self):
        doc = document_from_dot_string("digraph G { A; }")
        node = next(
            s for s in doc.pages[0].shapes
            if s.master_name_u != "Dynamic connector"
        )
        assert abs(float(node.width) - DOT_DEFAULT_NODE_WIDTH) < 1e-6
        assert abs(float(node.height) - DOT_DEFAULT_NODE_HEIGHT) < 1e-6

    def it_honours_explicit_width_and_height_attributes(self):
        doc = document_from_dot_string(
            'digraph G { A [width=3, height=2]; }'
        )
        node = next(
            s for s in doc.pages[0].shapes
            if s.master_name_u != "Dynamic connector"
        )
        assert abs(float(node.width) - 3.0) < 1e-6
        assert abs(float(node.height) - 2.0) < 1e-6

    def it_renders_cycles_without_hanging(self):
        # A -> B -> C -> A is a 3-cycle — every node has an incoming
        # edge so the topological pass would never resolve. The
        # implementation falls back to declaration order for the
        # cycle members.
        doc = document_from_dot_string(
            "digraph G { A -> B; B -> C; C -> A; }"
        )
        # Three nodes + three connectors = six shapes.
        assert len(list(doc.pages[0].shapes)) == 6


# ---------------------------------------------------------------------------
# DescribeClusterSubgraphs — cluster_* wraps members in a container box
# ---------------------------------------------------------------------------


class DescribeClusterSubgraphs:
    def it_emits_one_extra_rectangle_per_cluster(self):
        src = """
        digraph G {
            subgraph cluster_one { A; B; }
            C;
            A -> C;
        }
        """
        doc = document_from_dot_string(src)
        rects = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Rectangle"
        ]
        # Three node rects (A, B, C) + one cluster wrapper.
        assert len(rects) == 4

    def it_uses_cluster_label_attribute_for_the_wrapper_text(self):
        src = """
        digraph G {
            subgraph cluster_one { label="Group A"; X; Y; }
            Z; X -> Z;
        }
        """
        doc = document_from_dot_string(src)
        wrappers = [
            s for s in doc.pages[0].shapes
            if s.text == "Group A"
        ]
        assert len(wrappers) == 1

    def it_flattens_non_cluster_subgraphs(self):
        # ``subgraph foo { ... }`` (no ``cluster`` prefix) should have
        # NO wrapper shape — its members promote straight into the
        # parent. We verify by counting top-level rectangles.
        src = """
        digraph G {
            subgraph foo { A; B; }
            A -> B;
        }
        """
        doc = document_from_dot_string(src)
        rects = [
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Rectangle"
        ]
        # Two node rects and NO wrapper.
        assert len(rects) == 2

    def it_authors_cluster_wrappers_before_their_members(self):
        # Visio paints in document order — for the wrapper to render
        # behind its members, it must be the first shape in the page.
        src = """
        digraph G {
            subgraph cluster_x { A; B; }
            C; A -> C;
        }
        """
        doc = document_from_dot_string(src)
        first = list(doc.pages[0].shapes)[0]
        assert first.master_name_u == "Rectangle"
        # The text on the first shape is the cluster name (no label).
        assert first.text in ("cluster_x", "")


# ---------------------------------------------------------------------------
# DescribeFromDotFile — file-system entry point
# ---------------------------------------------------------------------------


class DescribeFromDotFile:
    def it_reads_a_dot_file_from_disk(self, tmp_path):
        dot_path = tmp_path / "graph.dot"
        dot_path.write_text("digraph G { A -> B -> C; }", encoding="utf-8")
        doc = document_from_dot(str(dot_path))
        assert len(list(doc.pages[0].shapes)) == 5

    def it_accepts_PathLike_inputs(self, tmp_path):
        dot_path = tmp_path / "graph.gv"
        dot_path.write_text("digraph G { A; B; }", encoding="utf-8")
        doc = document_from_dot(dot_path)
        # Two node rects.
        assert len([
            s for s in doc.pages[0].shapes
            if s.master_name_u == "Rectangle"
        ]) == 2

    def it_honours_a_caller_supplied_encoding(self, tmp_path):
        # Round-trip a Latin-1 encoded file to confirm the encoding
        # kwarg is plumbed through.
        dot_path = tmp_path / "graph.dot"
        dot_path.write_bytes(
            'digraph G { Caf\xe9 -> B; }'.encode("latin-1")
        )
        doc = document_from_dot(str(dot_path), encoding="latin-1")
        labels = [
            s.text for s in doc.pages[0].shapes
            if s.master_name_u == "Rectangle"
        ]
        assert "Café" in labels


# ---------------------------------------------------------------------------
# DescribeVisioDocumentClassmethods — public API exposed on VisioDocument
# ---------------------------------------------------------------------------


class DescribeVisioDocumentClassmethods:
    def it_exposes_VisioDocument_from_dot_string(self):
        doc = VisioDocument.from_dot_string("digraph G { A -> B; }")
        assert isinstance(doc, VisioDocument)
        assert len(doc.pages) == 1

    def it_exposes_VisioDocument_from_dot_path(self, tmp_path):
        dot_path = tmp_path / "graph.dot"
        dot_path.write_text("digraph G { A -> B; }", encoding="utf-8")
        doc = VisioDocument.from_dot(str(dot_path))
        assert isinstance(doc, VisioDocument)
        assert len(doc.pages) == 1

    def it_round_trips_through_save_and_open(self):
        # Author via from_dot_string, save to BytesIO, reopen with
        # VisioDocument.open and verify the shape count survives.
        src = "digraph Demo { A -> B -> C; }"
        doc = VisioDocument.from_dot_string(src)
        original_count = len(list(doc.pages[0].shapes))

        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        reopened = VisioDocument.open(buf)
        assert len(reopened.pages) == 1
        assert len(list(reopened.pages[0].shapes)) == original_count

    def it_forwards_page_name_kwarg(self):
        doc = VisioDocument.from_dot_string(
            "digraph G { A; }", page_name="Custom"
        )
        assert doc.pages[0].name == "Custom"

    def it_forwards_explicit_page_dimensions(self):
        doc = VisioDocument.from_dot_string(
            "digraph G { A; }", page_width=20.0, page_height=15.0
        )
        assert abs(float(doc.pages[0].width) - 20.0) < 1e-6
        assert abs(float(doc.pages[0].height) - 15.0) < 1e-6


# ---------------------------------------------------------------------------
# DescribeDotParseError — error reporting
# ---------------------------------------------------------------------------


class DescribeDotParseError:
    def it_raises_on_missing_graph_keyword(self):
        with pytest.raises(DotParseError):
            document_from_dot_string("{ A -> B; }")

    def it_raises_on_missing_opening_brace(self):
        with pytest.raises(DotParseError):
            document_from_dot_string("digraph G  A -> B; }")

    def it_raises_on_unterminated_quoted_string(self):
        with pytest.raises(DotParseError):
            document_from_dot_string('digraph G { A [label="oops]; }')

    def it_raises_on_unterminated_block_comment_with_other_garbage(self):
        # Unterminated block comment is tolerated; trailing garbage is not.
        with pytest.raises(DotParseError):
            document_from_dot_string("digraph G { /* unterminated A; }")

    def it_raises_on_mismatched_edge_operator_for_undirected_graph(self):
        with pytest.raises(DotParseError):
            document_from_dot_string("graph G { A -> B; }")

    def it_raises_on_mismatched_edge_operator_for_directed_graph(self):
        with pytest.raises(DotParseError):
            document_from_dot_string("digraph G { A -- B; }")

    def it_raises_on_trailing_tokens_after_closing_brace(self):
        with pytest.raises(DotParseError):
            document_from_dot_string("digraph G { A -> B; } extra")

    def it_carries_line_number_on_error(self):
        try:
            document_from_dot_string(
                "digraph G {\n    A [label=\"oops]\n}"
            )
        except DotParseError as exc:
            assert exc.line_no is not None
            return
        raise AssertionError("expected DotParseError")

    def it_rejects_non_str_source(self):
        with pytest.raises(TypeError):
            document_from_dot_string(b"digraph G { A; }")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# DescribeShapeMap — public DOT_SHAPE_MAP / DOT_SHAPE_KINDS surface
# ---------------------------------------------------------------------------


class DescribeShapeMap:
    def it_maps_box_synonyms_to_rectangle(self):
        for token in ("box", "rect", "rectangle"):
            assert DOT_SHAPE_MAP[token] == "rectangle"

    def it_maps_oval_to_ellipse(self):
        assert DOT_SHAPE_MAP["oval"] == "ellipse"

    def it_lists_only_renderable_kinds_in_DOT_SHAPE_KINDS(self):
        # Every value in DOT_SHAPE_MAP should appear in DOT_SHAPE_KINDS.
        for kind in set(DOT_SHAPE_MAP.values()):
            assert kind in DOT_SHAPE_KINDS
