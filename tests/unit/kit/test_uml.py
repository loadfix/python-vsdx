# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`vsdx.kit.uml` — issue #131."""

from __future__ import annotations

import textwrap
from io import BytesIO
from pathlib import Path

import pytest

import vsdx
from vsdx.kit import (
    UML_RELATION_ASSOCIATION,
    UML_RELATION_COMPOSITION,
    UML_RELATION_INHERITANCE,
    UML_RELATIONS,
    uml_from_json_schema,
    uml_from_python_module,
    uml_from_typescript,
)
from vsdx.kit.uml import _json_class_specs, _ts_parse_source
from vsdx.shapes.connector import Connector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connectors(diagram: vsdx.VisioDocument):
    return [s for s in diagram.pages[0].shapes if isinstance(s, Connector)]


def _box_texts(diagram: vsdx.VisioDocument):
    return [
        getattr(s, "text", "")
        for s in diagram.pages[0].shapes
        if not isinstance(s, Connector)
    ]


def _connector_relationship(conn: Connector) -> str:
    for field in conn.data.fields():
        if field.name == "Relationship":
            return field.value
    return ""


# ---------------------------------------------------------------------------
# DescribeUmlConstants
# ---------------------------------------------------------------------------


class DescribeUmlConstants:
    def it_exposes_relation_tokens(self):
        assert UML_RELATION_INHERITANCE in UML_RELATIONS
        assert UML_RELATION_COMPOSITION in UML_RELATIONS
        assert UML_RELATION_ASSOCIATION in UML_RELATIONS

    def it_distinguishes_the_three_kinds(self):
        assert len({
            UML_RELATION_INHERITANCE,
            UML_RELATION_COMPOSITION,
            UML_RELATION_ASSOCIATION,
        }) == 3


# ---------------------------------------------------------------------------
# Python-module introspection
# ---------------------------------------------------------------------------


_PYTHON_FIXTURE = textwrap.dedent(
    """
    from __future__ import annotations
    from dataclasses import dataclass
    from typing import List, Optional


    @dataclass
    class Address:
        street: str
        city: str

        def format(self) -> str:
            return self.street + ', ' + self.city


    class Person:
        name: str
        address: Address

        def greet(self, other: str) -> str:
            return 'hi ' + other


    class Employee(Person):
        salary: float
        manager: Optional['Employee']

        def raise_salary(self, by: float) -> None:
            self.salary += by


    class Team:
        members: List[Employee]
        lead: Employee
    """
).strip()


@pytest.fixture
def python_module(tmp_path: Path):
    path = tmp_path / "uml_fixture_module.py"
    path.write_text(_PYTHON_FIXTURE, encoding="utf-8")
    return path


class DescribeUmlFromPythonModule:
    def it_returns_a_VisioDocument(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_creates_one_page(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        assert len(diagram.pages) == 1

    def it_renders_one_box_per_class(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        # 4 classes + (no title band) = 4 boxes (no connectors counted).
        non_conn = [s for s in diagram.pages[0].shapes if not isinstance(s, Connector)]
        assert len(non_conn) == 4

    def it_includes_class_names_in_box_text(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        all_text = "\n".join(_box_texts(diagram))
        assert "Address" in all_text
        assert "Person" in all_text
        assert "Employee" in all_text
        assert "Team" in all_text

    def it_renders_three_section_box_with_separators(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        # Each box should contain at least two horizontal-rule separator
        # lines (made of dashes).
        for text in _box_texts(diagram):
            assert text.count("---") >= 2, "missing UML section separators in %r" % text

    def it_emits_inheritance_connector_for_subclass(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        assert UML_RELATION_INHERITANCE in rels

    def it_emits_composition_connector_for_typed_attribute(
        self, python_module: Path
    ):
        diagram = uml_from_python_module(str(python_module))
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        assert UML_RELATION_COMPOSITION in rels

    def it_can_filter_with_only(self, python_module: Path):
        diagram = uml_from_python_module(
            str(python_module), only=["Address", "Person"]
        )
        non_conn = [s for s in diagram.pages[0].shapes if not isinstance(s, Connector)]
        assert len(non_conn) == 2

    def it_renders_attribute_signatures_with_types(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        all_text = "\n".join(_box_texts(diagram))
        assert "salary" in all_text

    def it_records_class_name_on_box_data(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        names = []
        for shape in diagram.pages[0].shapes:
            if isinstance(shape, Connector):
                continue
            for f in shape.data.fields():
                if f.name == "ClassName":
                    names.append(f.value)
        assert "Person" in names

    def it_raises_when_module_has_no_classes(self, tmp_path: Path):
        empty = tmp_path / "empty.py"
        empty.write_text("# nothing here\n", encoding="utf-8")
        with pytest.raises(ValueError):
            uml_from_python_module(str(empty))

    def it_rejects_non_string_input(self):
        with pytest.raises(TypeError):
            uml_from_python_module(123)  # type: ignore[arg-type]

    def it_can_save_round_trip(self, python_module: Path):
        diagram = uml_from_python_module(str(python_module))
        buf = BytesIO()
        diagram.save(buf)
        assert buf.getvalue().startswith(b"PK")


# ---------------------------------------------------------------------------
# JSON Schema parsing
# ---------------------------------------------------------------------------


_JSON_FIXTURE = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Order",
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "buyer": {"$ref": "#/definitions/User"},
        "items": {
            "type": "array",
            "items": {"$ref": "#/definitions/LineItem"},
        },
    },
    "definitions": {
        "User": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "email": {"type": "string"},
            },
        },
        "LineItem": {
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "qty": {"type": "integer"},
            },
        },
        "WholesaleOrder": {
            "allOf": [
                {"$ref": "#/definitions/User"},
                {"properties": {"discount": {"type": "number"}}},
            ],
        },
    },
}


class DescribeUmlFromJsonSchema:
    def it_returns_a_VisioDocument(self):
        diagram = uml_from_json_schema(_JSON_FIXTURE)
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_renders_a_box_per_definition_plus_root(self):
        diagram = uml_from_json_schema(_JSON_FIXTURE)
        non_conn = [s for s in diagram.pages[0].shapes if not isinstance(s, Connector)]
        # 3 defs + 1 titled root = 4 boxes.
        assert len(non_conn) == 4

    def it_renders_property_names(self):
        diagram = uml_from_json_schema(_JSON_FIXTURE)
        all_text = "\n".join(_box_texts(diagram))
        assert "email" in all_text
        assert "sku" in all_text

    def it_emits_inheritance_for_allOf_ref(self):
        diagram = uml_from_json_schema(_JSON_FIXTURE)
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        assert UML_RELATION_INHERITANCE in rels

    def it_emits_composition_for_ref_property(self):
        diagram = uml_from_json_schema(_JSON_FIXTURE)
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        assert UML_RELATION_COMPOSITION in rels

    def it_can_load_from_disk(self, tmp_path: Path):
        import json

        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(_JSON_FIXTURE), encoding="utf-8")
        diagram = uml_from_json_schema(str(schema_path))
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_parses_inline_json_string(self):
        import json

        diagram = uml_from_json_schema(json.dumps(_JSON_FIXTURE))
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_supports_dollar_defs(self):
        schema = {
            "$defs": {
                "Foo": {"type": "object", "properties": {"x": {"type": "string"}}}
            }
        }
        specs = _json_class_specs(schema)
        names = [s.name for s in specs]
        assert "Foo" in names

    def it_rejects_non_mapping_root(self):
        with pytest.raises(ValueError):
            uml_from_json_schema("[1, 2, 3]")

    def it_raises_when_no_definitions(self):
        with pytest.raises(ValueError):
            uml_from_json_schema({"type": "object"})

    def it_rejects_unknown_input_type(self):
        with pytest.raises(TypeError):
            uml_from_json_schema(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TypeScript regex parsing
# ---------------------------------------------------------------------------


_TS_FIXTURE = textwrap.dedent(
    """
    /* The shopping module. */
    export interface User {
        id: number;
        email: string;
        // a method too
        rename(next: string): void;
    }

    export class Customer extends User {
        loyalty: number;
        favourite: Product;
        addItem(item: Product): boolean {
            return true;
        }
    }

    export class Product {
        sku: string;
        price: number;
    }

    type Cart = {
        owner: Customer;
        items: Product[];
    };
    """
).strip()


class DescribeUmlFromTypescript:
    def it_returns_a_VisioDocument(self):
        diagram = uml_from_typescript(_TS_FIXTURE)
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_parses_interface_class_and_type_blocks(self):
        specs = _ts_parse_source(_TS_FIXTURE)
        names = {s.name for s in specs}
        assert names == {"User", "Customer", "Product", "Cart"}

    def it_extracts_attributes_and_methods(self):
        specs = _ts_parse_source(_TS_FIXTURE)
        spec_by_name = {s.name: s for s in specs}
        attr_names = {a[0] for a in spec_by_name["User"].attributes}
        assert "id" in attr_names and "email" in attr_names
        method_names = {m[0] for m in spec_by_name["User"].methods}
        assert "rename" in method_names

    def it_emits_inheritance_for_extends(self):
        diagram = uml_from_typescript(_TS_FIXTURE)
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        assert UML_RELATION_INHERITANCE in rels

    def it_emits_composition_for_typed_property_referencing_in_scope_class(self):
        diagram = uml_from_typescript(_TS_FIXTURE)
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        assert UML_RELATION_COMPOSITION in rels

    def it_strips_comments_before_parsing(self):
        # The block comment contains a `}` that must NOT close the User
        # block.  If comment-stripping is broken the parser will lose
        # one of the trailing classes.
        sneaky = "/* } */\n" + _TS_FIXTURE
        specs = _ts_parse_source(sneaky)
        names = {s.name for s in specs}
        assert "Cart" in names

    def it_can_load_from_disk(self, tmp_path: Path):
        ts_path = tmp_path / "models.ts"
        ts_path.write_text(_TS_FIXTURE, encoding="utf-8")
        diagram = uml_from_typescript(str(ts_path))
        assert isinstance(diagram, vsdx.VisioDocument)

    def it_raises_when_source_has_no_classes(self):
        with pytest.raises(ValueError):
            uml_from_typescript("const x = 1;")

    def it_rejects_unknown_input_type(self):
        with pytest.raises(TypeError):
            uml_from_typescript(123)  # type: ignore[arg-type]

    def it_skips_self_referential_extends(self):
        src = "class Tree extends Tree { children: Tree[]; }"
        diagram = uml_from_typescript(src)
        rels = [_connector_relationship(c) for c in _connectors(diagram)]
        # No inheritance edge because target == source.
        assert UML_RELATION_INHERITANCE not in rels


# ---------------------------------------------------------------------------
# DescribeRendering — geometry / kwargs
# ---------------------------------------------------------------------------


class DescribeRendering:
    def it_honours_a_title(self):
        diagram = uml_from_typescript(_TS_FIXTURE, title="My Models")
        non_conn = [s for s in diagram.pages[0].shapes if not isinstance(s, Connector)]
        # title band + 4 classes = 5 rectangles.
        assert len(non_conn) == 5

    def it_uses_title_as_default_page_name(self):
        diagram = uml_from_typescript(_TS_FIXTURE, title="MyTitle")
        assert diagram.pages[0].name == "MyTitle"

    def it_falls_back_to_UML_when_no_title(self):
        diagram = uml_from_typescript(_TS_FIXTURE)
        assert diagram.pages[0].name == "UML"

    def it_rejects_unknown_layout(self):
        with pytest.raises(ValueError):
            uml_from_typescript(_TS_FIXTURE, layout="spiral")

    def it_rejects_non_string_title(self):
        with pytest.raises(TypeError):
            uml_from_typescript(_TS_FIXTURE, title=42)  # type: ignore[arg-type]

    def it_rejects_zero_inner_width(self):
        with pytest.raises(ValueError):
            uml_from_typescript(
                _TS_FIXTURE, page_width=0.5
            )

    def it_falls_back_to_force_directed_when_no_edges(self):
        # Single class with no parents / no in-scope composition targets.
        src = "class Lonely { id: number; }"
        diagram = uml_from_typescript(src)
        assert isinstance(diagram, vsdx.VisioDocument)
