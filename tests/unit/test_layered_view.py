# Copyright 2026 the python-vsdx authors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Unit tests for :mod:`vsdx.layered_view` — LayeredView builder + renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsdx import (
    DEFAULT_KIND_MASTERS,
    LayeredView,
    LayeredViewRenderer,
    Visio,
    load_layered_view,
)
from vsdx.layered_view import (
    LAYERED_VIEW_SCHEMA,
    _master_for_kind,
    _parse_layered_view_blob,
    _size_for_kind,
)


class DescribeLayeredView:
    def it_requires_at_least_one_layer(self):
        with pytest.raises(ValueError, match="at least one layer"):
            LayeredView(layers=[])

    def it_rejects_blank_layer_names(self):
        with pytest.raises(ValueError, match="non-empty"):
            LayeredView(layers=["", "physical"])

    def it_rejects_duplicate_layers(self):
        with pytest.raises(ValueError, match="duplicate layer"):
            LayeredView(layers=["x", "x"])

    def it_exposes_layers_in_declaration_order(self):
        view = LayeredView(layers=["logical", "physical", "network"])
        assert view.layers == ["logical", "physical", "network"]

    def it_accepts_an_optional_name(self):
        view = LayeredView(layers=["a"], name="aws-prod")
        assert view.name == "aws-prod"

    def it_repr_includes_counts(self):
        view = LayeredView(layers=["a", "b"], name="demo")
        view.add_entity("e1", a={"kind": "service", "name": "S"})
        text = repr(view)
        assert "demo" in text
        assert "entities=1" in text
        assert "relationships=0" in text


class DescribeLayeredViewAddEntity:
    def it_records_per_layer_descriptors(self):
        view = LayeredView(layers=["logical", "physical"])
        view.add_entity(
            "app",
            logical={"kind": "service", "name": "App"},
            physical={"kind": "ec2", "name": "i-xxx"},
        )
        assert view.entity_ids == ["app"]
        descriptor = view.entity("app")
        assert descriptor["logical"]["kind"] == "service"
        assert descriptor["physical"]["name"] == "i-xxx"

    def it_rejects_unknown_layer_keywords(self):
        view = LayeredView(layers=["logical"])
        with pytest.raises(ValueError, match="unknown layer"):
            view.add_entity("e1", physical={"kind": "ec2"})

    def it_rejects_re_used_entity_ids(self):
        view = LayeredView(layers=["logical"])
        view.add_entity("e1", logical={"kind": "service"})
        with pytest.raises(ValueError, match="already declared"):
            view.add_entity("e1", logical={"kind": "service"})

    def it_rejects_empty_entity_ids(self):
        view = LayeredView(layers=["a"])
        with pytest.raises(ValueError, match="non-empty string"):
            view.add_entity("", a={"kind": "service"})

    def it_rejects_non_mapping_descriptors(self):
        view = LayeredView(layers=["a"])
        with pytest.raises(ValueError, match="must be a mapping"):
            view.add_entity("e", a="not-a-dict")  # type: ignore[arg-type]

    def it_isolates_caller_dicts(self):
        view = LayeredView(layers=["a"])
        original = {"kind": "service", "name": "x"}
        view.add_entity("e", a=original)
        # Mutating the original after add must not bleed into the view.
        original["name"] = "changed"
        assert view.entity("e")["a"]["name"] == "x"

    def it_supports_partial_layer_descriptors(self):
        view = LayeredView(layers=["logical", "physical", "network"])
        # `database` exists only in two of three layers.
        view.add_entity(
            "database",
            logical={"kind": "datastore", "name": "DB"},
            network={"kind": "eni", "name": "eni-002"},
        )
        descriptor = view.entity("database")
        assert "physical" not in descriptor


class DescribeLayeredViewAddRelationship:
    def it_records_relationships(self):
        view = LayeredView(layers=["logical"])
        view.add_entity("a", logical={"kind": "service"})
        view.add_entity("b", logical={"kind": "service"})
        view.add_relationship("a", "b", kind="depends-on")
        rels = view.relationships
        assert rels == [{"from": "a", "to": "b", "kind": "depends-on"}]

    def it_carries_arbitrary_metadata(self):
        view = LayeredView(layers=["logical"])
        view.add_entity("a", logical={"kind": "service"})
        view.add_entity("b", logical={"kind": "service"})
        view.add_relationship("a", "b", kind="reads", latency_ms=12)
        rel = view.relationships[0]
        assert rel["metadata"]["latency_ms"] == 12

    def it_rejects_unknown_endpoints(self):
        view = LayeredView(layers=["logical"])
        view.add_entity("a", logical={"kind": "service"})
        with pytest.raises(ValueError, match="from_id .* not a known"):
            view.add_relationship("ghost", "a")
        with pytest.raises(ValueError, match="to_id .* not a known"):
            view.add_relationship("a", "ghost")


class DescribeLayeredViewShow:
    def it_returns_a_renderer_for_each_layer(self):
        view = LayeredView(layers=["logical", "physical"])
        renderer = view.show("logical")
        assert isinstance(renderer, LayeredViewRenderer)
        assert renderer.layer == "logical"
        assert renderer.view is view

    def it_rejects_unknown_layer_names(self):
        view = LayeredView(layers=["logical"])
        with pytest.raises(ValueError, match="not configured"):
            view.show("network")

    def it_filters_entities_to_the_layer(self):
        view = LayeredView(layers=["logical", "physical"])
        view.add_entity(
            "shared",
            logical={"kind": "service", "name": "shared"},
            physical={"kind": "ec2", "name": "i-shared"},
        )
        view.add_entity("logical-only", logical={"kind": "service"})
        view.add_entity("physical-only", physical={"kind": "ec2"})
        ids = {eid for eid, _ in view.show("logical").visible_entities()}
        assert ids == {"shared", "logical-only"}
        ids = {eid for eid, _ in view.show("physical").visible_entities()}
        assert ids == {"shared", "physical-only"}

    def it_drops_relationships_with_a_missing_endpoint(self):
        view = LayeredView(layers=["logical", "physical"])
        view.add_entity(
            "app",
            logical={"kind": "service", "name": "app"},
            physical={"kind": "ec2", "name": "i-001"},
        )
        view.add_entity("logical-only-db", logical={"kind": "datastore"})
        view.add_relationship("app", "logical-only-db", kind="reads")
        # Visible in logical (both endpoints present) …
        assert len(view.show("logical").visible_relationships()) == 1
        # … but missing from physical (db is logical-only).
        assert view.show("physical").visible_relationships() == []


class DescribeKindMasterMapping:
    def it_maps_known_kinds_falls_back_and_is_case_insensitive(self):
        assert _master_for_kind("service") == "Rectangle"
        assert _master_for_kind("datastore") == "Ellipse"
        assert _master_for_kind("rds") == "Ellipse"
        assert _master_for_kind("brand-new-kind") == "Rectangle"
        assert _master_for_kind("EC2") == _master_for_kind("ec2")
        assert _master_for_kind(123) == "Rectangle"  # type: ignore[arg-type]

    def its_eni_uses_a_smaller_default_size(self):
        assert _size_for_kind("eni") < _size_for_kind("service")
        assert "service" in DEFAULT_KIND_MASTERS
        assert DEFAULT_KIND_MASTERS["datastore"] == "Ellipse"


class DescribeLayeredViewSerialisation:
    def it_round_trips_via_json(self):
        view = LayeredView(layers=["logical", "physical"], name="demo")
        view.add_entity(
            "a",
            logical={"kind": "service", "name": "A"},
            physical={"kind": "ec2", "name": "i-A"},
        )
        view.add_entity("b", logical={"kind": "datastore", "name": "B"})
        view.add_relationship("a", "b", kind="reads", note="ro")
        payload = view.to_json()

        recovered = LayeredView.from_json(payload)
        assert recovered.layers == view.layers
        assert recovered.name == view.name
        assert recovered.entity_ids == view.entity_ids
        assert recovered.relationships == view.relationships

    def it_emits_the_schema_marker(self):
        view = LayeredView(layers=["a"])
        data = view.to_dict()
        assert data["schema"] == LAYERED_VIEW_SCHEMA

    def it_rejects_payloads_with_a_wrong_schema(self):
        with pytest.raises(ValueError, match="unrecognised"):
            LayeredView.from_dict(
                {"schema": "vsdx.something-else/1", "layers": ["a"]}
            )

    def it_silently_drops_descriptors_for_unknown_layers(self):
        # Hand-crafted payload — pretend a downstream tool added a
        # rogue 'audit' layer descriptor that the loader should
        # filter out rather than crash on.
        payload = {
            "schema": LAYERED_VIEW_SCHEMA,
            "layers": ["logical", "physical"],
            "entities": [
                {
                    "id": "a",
                    "descriptors": {
                        "logical": {"kind": "service"},
                        "audit": {"kind": "ghost"},
                    },
                },
            ],
            "relationships": [],
        }
        recovered = LayeredView.from_dict(payload)
        assert "audit" not in recovered.entity("a")
        assert "logical" in recovered.entity("a")

    def it_drops_relationships_with_unknown_endpoints(self):
        payload = {
            "schema": LAYERED_VIEW_SCHEMA,
            "layers": ["logical"],
            "entities": [{"id": "a", "descriptors": {"logical": {"kind": "service"}}}],
            "relationships": [{"from": "a", "to": "ghost"}],
        }
        recovered = LayeredView.from_dict(payload)
        assert recovered.relationships == []

    def it_parses_blob_envelope(self):
        view = LayeredView(layers=["a"])
        view.add_entity("e1", a={"kind": "service"})
        json_payload = view.to_json()
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<layeredView xmlns="urn:loadfix:python-vsdx:layered-view:1">\n'
            "<![CDATA[%s]]>\n"
            "</layeredView>\n"
        ) % json_payload
        recovered = _parse_layered_view_blob(envelope.encode("utf-8"))
        assert recovered is not None
        assert recovered.entity_ids == ["e1"]

    def it_returns_none_for_unrelated_blobs(self):
        assert _parse_layered_view_blob(b"") is None
        assert _parse_layered_view_blob(b"<?xml?><other/>") is None


class DescribePageAddLayeredView:
    def it_returns_a_layered_view_defaulting_name_to_page(self):
        doc = Visio()
        page = doc.pages.add_page(name="Service map")
        view = page.add_layered_view(layers=["logical", "physical"])
        assert isinstance(view, LayeredView)
        assert view.layers == ["logical", "physical"]
        assert view.name == "Service map"

    def it_accepts_an_explicit_name(self):
        doc = Visio()
        page = doc.pages.add_page(name="Service map")
        view = page.add_layered_view(layers=["a"], name="override")
        assert view.name == "override"


class DescribeLayeredViewRenderer:
    def _build_aws_view(self) -> LayeredView:
        view = LayeredView(
            layers=["logical", "physical", "network"],
            name="aws-prod",
        )
        view.add_entity(
            "app-server",
            logical={"kind": "service", "name": "Order Service"},
            physical={
                "kind": "ec2",
                "name": "i-abc123",
                "instance_type": "m5.large",
            },
            network={"kind": "eni", "name": "eni-001", "ip": "10.0.1.5"},
        )
        view.add_entity(
            "database",
            logical={"kind": "datastore", "name": "Orders DB"},
            physical={"kind": "rds", "name": "orders-prod", "engine": "postgres"},
            network={"kind": "eni", "name": "eni-002", "ip": "10.0.2.10"},
        )
        view.add_relationship("app-server", "database", kind="reads-writes")
        return view

    def it_writes_three_distinct_files_for_three_layers(self, tmp_path):
        view = self._build_aws_view()
        files = []
        for layer in view.layers:
            target = tmp_path / ("%s.vsdx" % layer)
            view.show(layer).save_to_page(str(target))
            assert target.exists()
            assert target.stat().st_size > 0
            files.append(target.read_bytes())
        # Files differ — distinct labels per layer guarantee distinct
        # blobs even after lxml's serialisation pass.
        assert len({hash(b) for b in files}) == 3

    def it_round_trips_a_3_layer_2_entity_1_relationship_view(self, tmp_path):
        view = self._build_aws_view()
        target = tmp_path / "logical.vsdx"
        view.show("logical").save_to_page(str(target))

        recovered = load_layered_view(str(target))
        assert recovered.layers == ["logical", "physical", "network"]
        assert recovered.entity_ids == ["app-server", "database"]
        assert recovered.relationships[0]["kind"] == "reads-writes"
        # Per-layer descriptors round-tripped:
        assert (
            recovered.entity("app-server")["physical"]["instance_type"]
            == "m5.large"
        )
        assert (
            recovered.entity("database")["network"]["ip"] == "10.0.2.10"
        )

    def it_emits_one_shape_per_visible_entity(self, tmp_path):
        view = self._build_aws_view()
        target = tmp_path / "physical.vsdx"
        view.show("physical").save_to_page(str(target))

        # Reload and walk the page's shape tree.
        doc = Visio(str(target))
        pages = list(doc.pages)
        assert len(pages) == 1
        shapes = list(pages[0].shapes)
        # Two entity shapes plus one connector.
        assert len(shapes) >= 3

    def it_omits_entities_missing_a_descriptor_for_the_layer(self, tmp_path):
        view = LayeredView(layers=["logical", "physical"])
        view.add_entity(
            "shared",
            logical={"kind": "service", "name": "shared"},
            physical={"kind": "ec2", "name": "i-shared"},
        )
        view.add_entity(
            "logical-only", logical={"kind": "datastore", "name": "lo"}
        )
        target = tmp_path / "physical.vsdx"
        view.show("physical").save_to_page(str(target))

        doc = Visio(str(target))
        page = list(doc.pages)[0]
        labels = [s.text or "" for s in page.shapes]
        # 'shared' label appears, 'lo' (logical-only) does not.
        assert any("shared" in lbl for lbl in labels)
        assert not any("lo" == lbl.strip() for lbl in labels)

    def it_skips_relationships_when_one_endpoint_is_missing(self, tmp_path):
        view = LayeredView(layers=["logical", "physical"])
        view.add_entity(
            "app",
            logical={"kind": "service", "name": "app"},
            physical={"kind": "ec2", "name": "i-app"},
        )
        view.add_entity("logical-only", logical={"kind": "datastore"})
        view.add_relationship("app", "logical-only", kind="reads")

        target = tmp_path / "physical.vsdx"
        view.show("physical").save_to_page(str(target))

        # Reload and confirm just the one entity shape (no connector).
        doc = Visio(str(target))
        page = list(doc.pages)[0]
        # No connectors exist — only the one app shape lives here.
        assert len(list(page.shapes)) == 1

    def it_returns_the_path_for_chaining(self, tmp_path):
        view = LayeredView(layers=["a"])
        view.add_entity("e1", a={"kind": "service", "name": "E1"})
        target = tmp_path / "a.vsdx"
        result = view.show("a").save_to_page(str(target))
        assert result == str(target)


class DescribeLoadLayeredView:
    def it_recovers_a_view_written_by_save_to_page(self, tmp_path):
        view = LayeredView(layers=["logical", "physical"], name="demo")
        view.add_entity(
            "a",
            logical={"kind": "service", "name": "A"},
            physical={"kind": "ec2", "name": "i-A"},
        )
        view.add_entity("b", physical={"kind": "rds", "name": "rds-B"})
        view.add_relationship("a", "b")
        target = tmp_path / "demo.vsdx"
        view.show("physical").save_to_page(str(target))

        recovered = load_layered_view(str(target))
        assert recovered.layers == ["logical", "physical"]
        assert recovered.name == "demo"
        assert recovered.entity_ids == ["a", "b"]
        assert recovered.entity("a")["logical"]["name"] == "A"
        assert recovered.entity("b")["physical"]["name"] == "rds-B"

    def it_raises_when_no_payload_is_present(self, tmp_path):
        # Save a vanilla document with no LayeredView attached.
        doc = Visio()
        doc.pages.add_page("plain")
        target = tmp_path / "plain.vsdx"
        doc.save(str(target))

        with pytest.raises(ValueError, match="no LayeredView payload"):
            load_layered_view(str(target))


class DescribeFluentAuthoring:
    def it_chains_add_entity_calls(self):
        view = (
            LayeredView(layers=["a"])
            .add_entity("e1", a={"kind": "service", "name": "E1"})
            .add_entity("e2", a={"kind": "datastore", "name": "E2"})
            .add_relationship("e1", "e2", kind="reads")
        )
        assert view.entity_ids == ["e1", "e2"]
        assert view.relationships[0]["from"] == "e1"

    def it_supports_the_aws_three_view_walkthrough(self, tmp_path):
        # Mirrors the canonical example in the module docstring.
        doc = Visio()
        page = doc.pages.add_page(name="AWS Service Map")
        arch = page.add_layered_view(layers=["logical", "physical", "network"])
        arch.add_entity(
            "app-server",
            logical={"kind": "service", "name": "Order Service"},
            physical={
                "kind": "ec2",
                "name": "i-abc123",
                "instance_type": "m5.large",
            },
            network={"kind": "eni", "name": "eni-001", "ip": "10.0.1.5"},
        )
        arch.add_entity(
            "database",
            logical={"kind": "datastore", "name": "Orders DB"},
            physical={
                "kind": "rds",
                "name": "orders-prod",
                "engine": "postgres",
            },
            network={"kind": "eni", "name": "eni-002", "ip": "10.0.2.10"},
        )
        arch.add_relationship("app-server", "database", kind="reads-writes")
        outputs = []
        for layer in arch.layers:
            target = tmp_path / ("%s.vsdx" % layer)
            arch.show(layer).save_to_page(str(target))
            outputs.append(Path(target))
        assert all(p.exists() for p in outputs)
        # Reload one of them and confirm the JSON envelope survived.
        recovered = load_layered_view(str(outputs[0]))
        assert recovered.relationships[0]["kind"] == "reads-writes"
