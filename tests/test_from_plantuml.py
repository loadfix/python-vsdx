# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Tests for :mod:`vsdx.kit.from_plantuml` — issue #124.

PlantUML import: parses ``@startuml`` / ``@enduml`` source strings (or
``.puml`` / ``.plantuml`` files) into :class:`~vsdx.document.VisioDocument`
instances. The covered subset is activity / component / use-case
diagrams; sequence / class / deployment / state are documented as
out-of-scope (issue #124).
"""

from __future__ import annotations

from io import BytesIO

import pytest

import vsdx
from vsdx import VisioDocument
from vsdx.kit import (
    PLANTUML_DIAGRAM_KINDS,
    PLANTUML_KIND_ACTIVITY,
    PLANTUML_KIND_COMPONENT,
    PLANTUML_KIND_EMPTY,
    from_plantuml,
    from_plantuml_string,
)
from vsdx.kit.from_plantuml import _parse  # noqa: PLC2701
from vsdx.shapes.connector import Connector


# ---------------------------------------------------------------------------
# Sample PlantUML sources — one per supported diagram kind
# ---------------------------------------------------------------------------


_ACTIVITY_SRC = """
@startuml
title Order processing
start
:Validate request;
if (valid?) then (yes)
  :Charge card;
  :Send email;
else (no)
  :Reject order;
endif
stop
@enduml
""".strip()


_COMPONENT_SRC = """
@startuml
[Web Frontend]
[Application Server] as app
() "REST API" as api
[Database] as db
Web Frontend --> api
api --> app
app ..> db
@enduml
""".strip()


_USECASE_SRC = """
@startuml
actor Customer
actor "Bank Officer" as Officer
usecase "Withdraw cash" as UC1
usecase Login
Customer --> UC1
Customer --> Login
Officer --> UC1
@enduml
""".strip()


_FENCELESS_SRC = """
[A]
[B]
A --> B
""".strip()


# ---------------------------------------------------------------------------
# DescribeFromPlantumlString — basic dispatch & return type
# ---------------------------------------------------------------------------


class DescribeFromPlantumlString:
    def it_returns_a_VisioDocument(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        assert isinstance(doc, vsdx.VisioDocument)

    def it_creates_one_page_per_diagram(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        assert len(doc.pages) == 1

    def it_uses_the_title_directive_as_default_page_name(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        assert doc.pages[0].name == "Order processing"

    def it_honours_an_explicit_page_name_kwarg(self):
        doc = from_plantuml_string(_ACTIVITY_SRC, page_name="Custom")
        assert doc.pages[0].name == "Custom"

    def it_falls_back_to_a_kind_specific_page_name_when_no_title(self):
        doc = from_plantuml_string(_COMPONENT_SRC)
        assert doc.pages[0].name == "Component diagram"

    def it_rejects_a_non_str_text(self):
        with pytest.raises(TypeError):
            from_plantuml_string(123)  # type: ignore[arg-type]

    def it_returns_a_one_page_doc_for_an_empty_source(self):
        doc = from_plantuml_string("@startuml\n@enduml")
        assert len(doc.pages) == 1
        assert len(list(doc.pages[0].shapes)) == 0

    def it_tolerates_a_source_without_the_fence(self):
        doc = from_plantuml_string(_FENCELESS_SRC)
        # [A] and [B] both parsed, plus one connector.
        shapes = list(doc.pages[0].shapes)
        assert any(getattr(s, "text", "") == "A" for s in shapes)
        assert any(getattr(s, "text", "") == "B" for s in shapes)


# ---------------------------------------------------------------------------
# DescribeActivityImport — activity-diagram subset
# ---------------------------------------------------------------------------


class DescribeActivityImport:
    def it_emits_an_ellipse_for_start(self):
        doc = from_plantuml_string("@startuml\nstart\nstop\n@enduml")
        shapes = list(doc.pages[0].shapes)
        # start + stop both rendered as ellipses.
        from vsdx import Ellipse

        ellipses = [s for s in shapes if isinstance(s, Ellipse)]
        assert len(ellipses) == 2

    def it_emits_a_rectangle_for_each_action(self):
        src = "@startuml\nstart\n:Step1;\n:Step2;\n:Step3;\nstop\n@enduml"
        doc = from_plantuml_string(src)
        shapes = list(doc.pages[0].shapes)
        labels = sorted(getattr(s, "text", "") for s in shapes)
        for expected in ("Step1", "Step2", "Step3"):
            assert expected in labels

    def it_renders_the_if_condition_as_a_diamond_label(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        labels = [getattr(s, "text", "") for s in doc.pages[0].shapes]
        assert "valid?" in labels

    def it_renders_both_then_and_else_branch_actions(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        labels = [getattr(s, "text", "") for s in doc.pages[0].shapes]
        assert "Charge card" in labels
        assert "Send email" in labels
        assert "Reject order" in labels

    def it_chains_consecutive_steps_with_connectors(self):
        src = "@startuml\nstart\n:A;\n:B;\nstop\n@enduml"
        doc = from_plantuml_string(src)
        connectors = [
            s for s in doc.pages[0].shapes if isinstance(s, Connector)
        ]
        # start->A, A->B, B->stop = 3 connectors.
        assert len(connectors) == 3

    def it_uses_a_portrait_default_page_size_for_activity(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        page = doc.pages[0]
        assert page.height > page.width

    def it_treats_the_legacy_end_keyword_as_stop(self):
        # ``end`` is a synonym for ``stop`` in the line-oriented dialect.
        src = "@startuml\nstart\n:Action;\nend\n@enduml"
        doc = from_plantuml_string(src)
        # No exception, single-page doc with at least three shapes
        # (start, action, end ellipse).
        assert len(list(doc.pages[0].shapes)) >= 3

    def it_handles_an_if_without_an_explicit_else(self):
        src = (
            "@startuml\nstart\n:A;\nif (cond?) then (yes)\n"
            ":B;\nendif\nstop\n@enduml"
        )
        doc = from_plantuml_string(src)
        labels = [getattr(s, "text", "") for s in doc.pages[0].shapes]
        assert "cond?" in labels
        assert "B" in labels


# ---------------------------------------------------------------------------
# DescribeComponentImport — component-diagram subset
# ---------------------------------------------------------------------------


class DescribeComponentImport:
    def it_renders_bracketed_components_as_rectangles(self):
        doc = from_plantuml_string(_COMPONENT_SRC)
        from vsdx import Rectangle

        rectangles = [
            s for s in doc.pages[0].shapes if isinstance(s, Rectangle)
        ]
        labels = {getattr(r, "text", "") for r in rectangles}
        assert "Web Frontend" in labels
        assert "Application Server" in labels
        assert "Database" in labels

    def it_renders_paren_interfaces_as_ellipses(self):
        doc = from_plantuml_string(_COMPONENT_SRC)
        from vsdx import Ellipse

        ellipses = [s for s in doc.pages[0].shapes if isinstance(s, Ellipse)]
        labels = {getattr(e, "text", "") for e in ellipses}
        assert "REST API" in labels

    def it_emits_one_connector_per_arrow(self):
        doc = from_plantuml_string(_COMPONENT_SRC)
        connectors = [
            s for s in doc.pages[0].shapes if isinstance(s, Connector)
        ]
        # Three arrows in the source.
        assert len(connectors) == 3

    def it_auto_creates_endpoints_referenced_only_by_arrow(self):
        # No declarations — just a single arrow line.
        src = "@startuml\nFoo --> Bar\n@enduml"
        doc = from_plantuml_string(src)
        labels = {getattr(s, "text", "") for s in doc.pages[0].shapes}
        assert "Foo" in labels
        assert "Bar" in labels

    def it_supports_dashed_dependency_arrows(self):
        # ``..>`` is a dashed dependency arrow; structurally identical
        # to ``-->`` at the rendered Visio level (both connectors).
        src = "@startuml\n[A]\n[B]\nA ..> B\n@enduml"
        doc = from_plantuml_string(src)
        connectors = [
            s for s in doc.pages[0].shapes if isinstance(s, Connector)
        ]
        assert len(connectors) == 1

    def it_reverses_left_pointing_arrows(self):
        # ``A <-- B`` should produce the same edge as ``B --> A``.
        src = "@startuml\n[A]\n[B]\nA <-- B\n@enduml"
        doc = from_plantuml_string(src)
        connectors = [
            s for s in doc.pages[0].shapes if isinstance(s, Connector)
        ]
        assert len(connectors) == 1

    def it_re_uses_a_node_alias_redeclared_in_the_same_source(self):
        src = "@startuml\n[A]\n[A]\n@enduml"
        doc = from_plantuml_string(src)
        # Single A box, not a duplicate.
        labels = [
            getattr(s, "text", "") for s in doc.pages[0].shapes
            if getattr(s, "text", "") == "A"
        ]
        assert len(labels) == 1


# ---------------------------------------------------------------------------
# DescribeUsecaseImport — actor + usecase declarations
# ---------------------------------------------------------------------------


class DescribeUsecaseImport:
    def it_renders_actors_as_ellipses(self):
        doc = from_plantuml_string(_USECASE_SRC)
        from vsdx import Ellipse

        ellipse_labels = {
            getattr(s, "text", "")
            for s in doc.pages[0].shapes
            if isinstance(s, Ellipse)
        }
        assert "Customer" in ellipse_labels
        assert "Bank Officer" in ellipse_labels

    def it_renders_usecases_as_ellipses(self):
        doc = from_plantuml_string(_USECASE_SRC)
        from vsdx import Ellipse

        ellipse_labels = {
            getattr(s, "text", "")
            for s in doc.pages[0].shapes
            if isinstance(s, Ellipse)
        }
        assert "Withdraw cash" in ellipse_labels
        assert "Login" in ellipse_labels

    def it_emits_one_connector_per_actor_to_usecase_arrow(self):
        doc = from_plantuml_string(_USECASE_SRC)
        connectors = [
            s for s in doc.pages[0].shapes if isinstance(s, Connector)
        ]
        assert len(connectors) == 3

    def it_supports_actor_alias_declarations(self):
        src = '@startuml\nactor "Long Name" as ln\n@enduml'
        doc = from_plantuml_string(src)
        from vsdx import Ellipse

        ellipses = [s for s in doc.pages[0].shapes if isinstance(s, Ellipse)]
        assert any(getattr(s, "text", "") == "Long Name" for s in ellipses)


# ---------------------------------------------------------------------------
# DescribeFromPlantumlFile — file-backed entry point
# ---------------------------------------------------------------------------


class DescribeFromPlantumlFile:
    def it_reads_a_dot_puml_file(self, tmp_path):
        path = tmp_path / "diagram.puml"
        path.write_text(_COMPONENT_SRC, encoding="utf-8")
        doc = from_plantuml(str(path))
        assert isinstance(doc, vsdx.VisioDocument)
        assert len(doc.pages) == 1

    def it_reads_a_dot_plantuml_file(self, tmp_path):
        path = tmp_path / "diagram.plantuml"
        path.write_text(_ACTIVITY_SRC, encoding="utf-8")
        doc = from_plantuml(str(path))
        assert isinstance(doc, vsdx.VisioDocument)

    def it_raises_FileNotFoundError_for_a_missing_file(self, tmp_path):
        missing = tmp_path / "nope.puml"
        with pytest.raises(FileNotFoundError):
            from_plantuml(str(missing))


# ---------------------------------------------------------------------------
# DescribeVisioDocumentClassmethods — public-API shim
# ---------------------------------------------------------------------------


class DescribeVisioDocumentClassmethods:
    def it_exposes_from_plantuml_string_on_VisioDocument(self):
        doc = VisioDocument.from_plantuml_string(_ACTIVITY_SRC)
        assert isinstance(doc, vsdx.VisioDocument)
        assert doc.pages[0].name == "Order processing"

    def it_exposes_from_plantuml_on_VisioDocument(self, tmp_path):
        path = tmp_path / "diagram.puml"
        path.write_text(_COMPONENT_SRC, encoding="utf-8")
        doc = VisioDocument.from_plantuml(str(path))
        assert isinstance(doc, vsdx.VisioDocument)


# ---------------------------------------------------------------------------
# DescribeAstParse — internal AST shape (regression-guard, not contract)
# ---------------------------------------------------------------------------


class DescribeAstParse:
    def it_classifies_an_activity_source(self):
        ast = _parse(_ACTIVITY_SRC)
        assert ast.kind == PLANTUML_KIND_ACTIVITY

    def it_classifies_a_component_source(self):
        ast = _parse(_COMPONENT_SRC)
        assert ast.kind == PLANTUML_KIND_COMPONENT

    def it_classifies_an_empty_source_as_empty(self):
        ast = _parse("@startuml\n@enduml")
        assert ast.kind == PLANTUML_KIND_EMPTY

    def it_captures_the_title_directive(self):
        ast = _parse(_ACTIVITY_SRC)
        assert ast.title == "Order processing"

    def it_freezes_the_kind_token_set(self):
        assert PLANTUML_KIND_ACTIVITY in PLANTUML_DIAGRAM_KINDS
        assert PLANTUML_KIND_COMPONENT in PLANTUML_DIAGRAM_KINDS
        assert PLANTUML_KIND_EMPTY in PLANTUML_DIAGRAM_KINDS

    def it_skips_unrecognised_lines_silently(self):
        # ``skinparam`` is unsupported — the parser should ignore it
        # rather than fail closed.
        src = (
            "@startuml\n"
            "skinparam backgroundColor #EEEBDC\n"
            "[A]\n"
            "[B]\n"
            "A --> B\n"
            "@enduml"
        )
        ast = _parse(src)
        assert ast.kind == PLANTUML_KIND_COMPONENT
        # Both nodes still parsed.
        aliases = {n["alias"] for n in ast.nodes}
        assert {"A", "B"}.issubset(aliases)


# ---------------------------------------------------------------------------
# DescribeRoundTrip — saved file is a valid .vsdx (re-openable)
# ---------------------------------------------------------------------------


class DescribeRoundTrip:
    def it_saves_a_parsed_activity_doc_as_a_valid_vsdx(self):
        doc = from_plantuml_string(_ACTIVITY_SRC)
        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        # Re-open and verify the page survives the round-trip.
        reopened = vsdx.Visio(buf)
        assert len(reopened.pages) == 1

    def it_saves_a_parsed_component_doc_as_a_valid_vsdx(self):
        doc = from_plantuml_string(_COMPONENT_SRC)
        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        reopened = vsdx.Visio(buf)
        assert len(reopened.pages) == 1
