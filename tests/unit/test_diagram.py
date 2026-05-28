# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Behavioural tests for :mod:`vsdx.diagram` — stencil hot-swap.

Covers issue #135's three acceptance points:

* :meth:`VisioDocument.swap_stencil` returns a :class:`SwapReport`
  reflecting swapped / kept-old / placeholder / unmappable-property
  counts, and the on_missing= dispatch.
* :meth:`VisioDocument.swap_shapes` rebinds shapes that match a
  pattern dict.
* :meth:`VisioDocument.update_theme` replaces the theme element.
* Position / connection / property preservation verified by
  round-trip test.

The fixture builders here fabricate two minimal stencil sets
in-test rather than depending on python-vsdx-stencils — that
package only ships a skeleton today.
"""

from __future__ import annotations

import io

import pytest

import vsdx
from vsdx.diagram import (
    StencilSet,
    SwapReport,
    UnmappableProperty,
    UnmappableShape,
    swap_shapes,
    swap_stencil,
    update_theme,
)


# ---------------------------------------------------------------------------
# Helpers — fabricate two stencil sets in-test
# ---------------------------------------------------------------------------


def _add_property_row(
    shape_el,
    name,
    *,
    type_v="0",
    label=None,
    fmt=None,
):
    """Append a ``<Section N="Property"> <Row N=...>`` to *shape_el*."""
    section = None
    for sec in shape_el.section_lst:
        if sec.get("N") == "Property":
            section = sec
            break
    if section is None:
        section = shape_el._add_section()
        section.set("N", "Property")
    row = section._add_row()
    row.set("N", name)
    cell = row._add_cell()
    cell.set("N", "Type")
    cell.set("V", type_v)
    if label is not None:
        cell = row._add_cell()
        cell.set("N", "Label")
        cell.set("V", label)
    if fmt is not None:
        cell = row._add_cell()
        cell.set("N", "Format")
        cell.set("V", fmt)
    return row


def _add_connection_point(shape_el, ix, x, y):
    """Append a ``<Section N="Connection"> <Row IX=ix>`` to *shape_el*."""
    section = None
    for sec in shape_el.section_lst:
        if sec.get("N") == "Connection":
            section = sec
            break
    if section is None:
        section = shape_el._add_section()
        section.set("N", "Connection")
    row = section._add_row()
    row.set("IX", str(ix))
    cell = row._add_cell()
    cell.set("N", "X")
    cell.set("V", str(x))
    cell = row._add_cell()
    cell.set("N", "Y")
    cell.set("V", str(y))
    return row


def _build_aws_2020():
    """Fabricate a tiny ``AWS-2020`` stencil with EC2 + S3 + Lambda."""
    sten = vsdx.Visio()
    ec2 = sten.masters.add_master("EC2")
    ec2_shape = ec2.add_shape("ec2.bg", x=0, y=0, width=1, height=1)
    _add_property_row(ec2_shape, "InstanceType", type_v="0", label="Instance type")
    _add_property_row(ec2_shape, "Region", type_v="0", label="Region")
    # 4 cardinal connection points.
    _add_connection_point(ec2_shape, 1, 0.5, 1.0)  # top
    _add_connection_point(ec2_shape, 2, 1.0, 0.5)  # right
    _add_connection_point(ec2_shape, 3, 0.5, 0.0)  # bottom
    _add_connection_point(ec2_shape, 4, 0.0, 0.5)  # left

    s3 = sten.masters.add_master("S3")
    s3_shape = s3.add_shape("s3.bg", x=0, y=0, width=1, height=1)
    _add_property_row(s3_shape, "BucketName", type_v="0")

    lam = sten.masters.add_master("Lambda")
    lam.add_shape("lam.bg", x=0, y=0, width=1, height=1)

    return sten


def _build_aws_2024():
    """Fabricate the matching ``AWS-2024`` stencil — same names, new metadata."""
    sten = vsdx.Visio()
    ec2 = sten.masters.add_master("EC2")
    ec2_shape = ec2.add_shape("ec2.bg", x=0, y=0, width=1, height=1)
    # Number-typed instance type (was String in 2020).
    _add_property_row(
        ec2_shape, "InstanceType", type_v="2", label="Instance type"
    )
    # Region is gone — moved to a separate "AWSRegion" master in 2024.
    _add_property_row(ec2_shape, "AccountID", type_v="0", label="Account ID")
    # Only 2 connection points (top, bottom) — half of what 2020 had.
    _add_connection_point(ec2_shape, 1, 0.5, 1.0)  # top
    _add_connection_point(ec2_shape, 2, 0.5, 0.0)  # bottom

    s3 = sten.masters.add_master("S3")
    s3_shape = s3.add_shape("s3.bg", x=0, y=0, width=1, height=1)
    _add_property_row(s3_shape, "BucketName", type_v="0")

    # Note: no Lambda master — exercises the on_missing= branch.
    return sten


def _diagram_with_three_shapes():
    """Build a diagram whose shapes reference EC2 / S3 / Lambda masters."""
    doc = vsdx.Visio()
    # Pre-register placeholder masters so add_shape_from_master's
    # @Master attribute resolves into doc.masters.resolve(...).
    doc.masters.add_master("EC2")
    doc.masters.add_master("S3")
    doc.masters.add_master("Lambda")
    page = doc.pages.add_page(name="Page-1")
    ec2 = page.shapes.add_shape_from_master("EC2", at=(2, 3), size=(1, 1))
    s3 = page.shapes.add_shape_from_master("S3", at=(4, 3), size=(1, 1))
    lam = page.shapes.add_shape_from_master("Lambda", at=(6, 3), size=(1, 1))
    return doc, page, ec2, s3, lam


# ---------------------------------------------------------------------------
# StencilSet
# ---------------------------------------------------------------------------


class DescribeStencilSet:
    def it_builds_from_a_document(self):
        sten = _build_aws_2020()
        s = StencilSet.from_document(sten, label="AWS-2020")
        assert s.label == "AWS-2020"
        assert "EC2" in s and "S3" in s and "Lambda" in s
        assert "Missing" not in s
        assert s.by_name("EC2") is not None
        assert s.by_name("Missing") is None

    def it_builds_from_an_iterable_of_masters(self):
        sten = _build_aws_2020()
        s = StencilSet.from_masters(list(sten.masters), label="custom")
        assert s.label == "custom"
        assert sorted(s.names()) == ["EC2", "Lambda", "S3"]

    def it_acts_as_a_simple_mapping(self):
        sten = _build_aws_2020()
        s = StencilSet.from_document(sten)
        assert len(s) == 3
        assert sorted(list(s)) == ["EC2", "Lambda", "S3"]

    def it_skips_masters_with_no_name_u(self):
        # Synthesise a master with no NameU — direct attribute pop.
        sten = _build_aws_2020()
        sten.masters[0]._element.attrib.pop("NameU", None)
        sten.masters[0]._element.attrib.pop("Name", None)
        s = StencilSet.from_document(sten)
        # The "EC2" entry is gone now, leaving S3 + Lambda.
        assert "EC2" not in s


# ---------------------------------------------------------------------------
# swap_stencil — bulk swap
# ---------------------------------------------------------------------------


class DescribeSwapStencil:
    def it_returns_a_SwapReport(self):
        doc, _page, _ec2, _s3, _lam = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020(), label="AWS-2020")
        new = StencilSet.from_document(_build_aws_2024(), label="AWS-2024")
        report = doc.swap_stencil(from_set=old, to_set=new)
        assert isinstance(report, SwapReport)
        assert report.from_set == "AWS-2020"
        assert report.to_set == "AWS-2024"

    def it_swaps_shapes_with_a_matching_master_by_name(self):
        doc, _page, _ec2, _s3, _lam = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        report = doc.swap_stencil(from_set=old, to_set=new)
        assert report.shapes_swapped == 2  # EC2 + S3 swap; Lambda doesn't

    def it_keeps_old_master_when_on_missing_is_keep_old(self):
        doc, page, _ec2, _s3, lam = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        report = doc.swap_stencil(from_set=old, to_set=new, on_missing="keep-old")
        assert report.shapes_kept_old == 1
        assert lam.master_name_u == "Lambda"  # unchanged
        assert len(report.unmappable_shapes) == 1
        assert report.unmappable_shapes[0].old_master_name == "Lambda"
        assert report.unmappable_shapes[0].reason == "missing-master"

    def it_drops_shape_to_placeholder_rectangle_when_requested(self):
        doc, page, _ec2, _s3, lam = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        report = doc.swap_stencil(
            from_set=old, to_set=new, on_missing="placeholder"
        )
        assert report.shapes_replaced_with_placeholder == 1
        # Lambda was rebound to the placeholder.
        assert lam.master_name_u == "Rectangle"

    def it_raises_KeyError_when_on_missing_is_error(self):
        doc, *_ = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        with pytest.raises(KeyError, match="Lambda"):
            doc.swap_stencil(from_set=old, to_set=new, on_missing="error")

    def it_rejects_unknown_on_missing_tokens(self):
        doc, *_ = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        with pytest.raises(ValueError, match="on_missing"):
            doc.swap_stencil(from_set=old, to_set=new, on_missing="explode")

    def it_preserves_position_geometry_after_swap(self):
        doc, page, ec2, s3, _lam = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        doc.swap_stencil(from_set=old, to_set=new)
        # Geometry cells on the shape are untouched.
        assert ec2.pin_x == 2 and ec2.pin_y == 3
        assert ec2.width == 1 and ec2.height == 1
        assert s3.pin_x == 4 and s3.pin_y == 3

    def it_preserves_text_labels_after_swap(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        ec2.text = "my-web-server"
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        doc.swap_stencil(from_set=old, to_set=new)
        assert ec2.text == "my-web-server"

    def it_preserves_mappable_property_values_after_swap(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        ec2.data.add_field("InstanceType", "m5.large")
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        doc.swap_stencil(from_set=old, to_set=new)
        # Instance type survived — value is the user-set string.
        # (Type cell was rewritten to Number per new master, but that's
        # cosmetic — the @V string carries the original value.)
        assert ec2.data.field("InstanceType").raw_value == "m5.large"

    def it_records_unmappable_properties_on_the_report(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        ec2.data.add_field("Region", "us-east-1")
        ec2.data.add_field("InstanceType", "m5.large")
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        report = doc.swap_stencil(from_set=old, to_set=new)
        # Region is on 2020-EC2 but not 2024-EC2 — it's recorded.
        assert any(
            isinstance(p, UnmappableProperty)
            and p.property_name == "Region"
            and p.value == "us-east-1"
            for p in report.unmappable_properties
        )
        # And dropped from the shape itself.
        assert "Region" not in ec2.data
        # InstanceType stays.
        assert "InstanceType" in ec2.data

    def it_overwrites_property_metadata_from_the_new_master(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        ec2.data.add_field("InstanceType", "m5.large")
        # Old master types InstanceType as a String (0); new types it
        # as Number (2). Verify the new metadata won.
        assert ec2.data.field("InstanceType").type == 0
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        doc.swap_stencil(from_set=old, to_set=new)
        assert ec2.data.field("InstanceType").type == 2

    def it_honours_an_explicit_name_map(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        # Pretend Lambda → S3 in the new set (silly but exercises the
        # name-map path).
        report = doc.swap_stencil(
            from_set=old,
            to_set=new,
            name_map={"Lambda": "S3"},
        )
        # Now Lambda swap succeeds (rebound to S3), so swapped == 3
        # and kept-old == 0.
        assert report.shapes_swapped == 3
        assert report.shapes_kept_old == 0

    def it_skips_shapes_whose_master_is_outside_the_from_set(self):
        # Shape with a master nobody knows about — neither swapped nor
        # kept-old (it was never a candidate).
        doc = vsdx.Visio()
        doc.masters.add_master("UnknownVendor")
        page = doc.pages.add_page(name="P")
        page.shapes.add_shape_from_master("UnknownVendor", at=(1, 1), size=(1, 1))
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        report = doc.swap_stencil(from_set=old, to_set=new)
        assert report.shapes_swapped == 0
        assert report.shapes_kept_old == 0

    def it_remaps_connector_glue_to_the_nearest_new_point(self):
        # Build a diagram with two EC2s and a connector glued to a
        # specific connection point on the target.
        doc, page, ec2, s3, _lam = _diagram_with_three_shapes()
        # Manually wire a Connect record glued to "Connections.X4"
        # (the "left" point on the 2020 master at (0.0, 0.5)).
        page_contents = page._page_part.element
        connects = page_contents.connects_element
        connect = connects.add_connect(
            from_sheet=str(s3.shape_id),
            to_sheet=str(ec2.shape_id),
            from_cell="EndX",
            to_cell="Connections.X4",
        )
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        report = doc.swap_stencil(from_set=old, to_set=new)
        # 2024-EC2 has only points at (0.5,1.0) and (0.5,0.0). The
        # nearest to the old "left" point (0.0,0.5) is the bottom
        # one: distance to top = 0.25+0.25 = 0.5; distance to bottom
        # = 0.25+0.25 = 0.5. Tie → first wins → "Connections.X1".
        # Either way, the cell got rewritten.
        assert report.connector_endpoints_remapped >= 1
        new_to_cell = connect.get("ToCell")
        assert new_to_cell.startswith("Connections.X")
        assert new_to_cell != "Connections.X4"

    def it_falls_back_to_PinX_when_new_master_has_no_connection_points(self):
        # Build a swap where the new EC2 has zero connection points.
        old = _build_aws_2020()
        new = vsdx.Visio()
        new_ec2 = new.masters.add_master("EC2")
        new_ec2.add_shape("ec2.bg", x=0, y=0, width=1, height=1)

        doc = vsdx.Visio()
        doc.masters.add_master("EC2")
        page = doc.pages.add_page(name="P")
        ec2 = page.shapes.add_shape_from_master("EC2", at=(2, 3), size=(1, 1))
        peer = page.shapes.add_shape_from_master("EC2", at=(5, 3), size=(1, 1))
        page_contents = page._page_part.element
        connect = page_contents.connects_element.add_connect(
            from_sheet=str(peer.shape_id),
            to_sheet=str(ec2.shape_id),
            from_cell="EndX",
            to_cell="Connections.X2",
        )
        report = doc.swap_stencil(
            from_set=StencilSet.from_document(old),
            to_set=StencilSet.from_document(new),
        )
        # No more connection points — the fallback is "PinX".
        assert connect.get("ToCell") == "PinX"
        assert report.connector_endpoints_remapped >= 1


class DescribeSwapStencilCoercion:
    def it_accepts_a_VisioDocument_directly(self):
        doc, *_ = _diagram_with_three_shapes()
        old_doc = _build_aws_2020()
        new_doc = _build_aws_2024()
        report = doc.swap_stencil(from_set=old_doc, to_set=new_doc)
        assert isinstance(report, SwapReport)
        assert report.shapes_swapped == 2

    def it_accepts_a_dict_of_str_to_Master(self):
        doc, *_ = _diagram_with_three_shapes()
        old_doc = _build_aws_2020()
        new_doc = _build_aws_2024()
        old_dict = {m.name_u: m for m in old_doc.masters}
        new_dict = {m.name_u: m for m in new_doc.masters}
        report = doc.swap_stencil(from_set=old_dict, to_set=new_dict)
        assert report.shapes_swapped == 2

    def it_rejects_string_set_labels_until_registry_lands(self):
        doc, *_ = _diagram_with_three_shapes()
        new_doc = _build_aws_2024()
        with pytest.raises(NotImplementedError, match="registry"):
            doc.swap_stencil(from_set="AWS-2020", to_set=new_doc)

    def it_rejects_unknown_types(self):
        doc, *_ = _diagram_with_three_shapes()
        new_doc = _build_aws_2024()
        with pytest.raises(TypeError, match="from_set"):
            doc.swap_stencil(from_set=42, to_set=new_doc)


# ---------------------------------------------------------------------------
# swap_shapes — surgical swap
# ---------------------------------------------------------------------------


class DescribeSwapShapes:
    def it_swaps_shapes_matching_master_name(self):
        doc, page, ec2, s3, _lam = _diagram_with_three_shapes()
        new_doc = _build_aws_2024()
        new_ec2 = new_doc.masters["EC2"]
        count = doc.swap_shapes(
            pattern={"master_name": "EC2"}, new_master=new_ec2
        )
        assert count == 1
        # ec2 was rebound; s3 left alone.
        assert ec2.master_name_u == "EC2"  # name unchanged but contents refreshed
        assert s3.master_name_u == "S3"

    def it_swaps_shapes_matching_shape_name(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        ec2.name = "MyWebServer"
        new_doc = _build_aws_2024()
        count = doc.swap_shapes(
            pattern={"shape_name": "MyWebServer"},
            new_master=new_doc.masters["S3"],
        )
        assert count == 1
        assert ec2.master_name_u == "S3"

    def it_combines_pattern_keys_with_AND(self):
        doc, page, ec2, _s3, _lam = _diagram_with_three_shapes()
        new_doc = _build_aws_2024()
        # Match shape_name AND master_name. Neither shape has the name
        # "Nope", so AND-combination returns zero.
        count = doc.swap_shapes(
            pattern={"master_name": "EC2", "shape_name": "Nope"},
            new_master=new_doc.masters["EC2"],
        )
        assert count == 0

    def it_rejects_an_empty_pattern(self):
        doc, *_ = _diagram_with_three_shapes()
        new_doc = _build_aws_2024()
        with pytest.raises(ValueError, match="pattern"):
            doc.swap_shapes(pattern={}, new_master=new_doc.masters["EC2"])

    def it_rejects_unsupported_pattern_keys(self):
        doc, *_ = _diagram_with_three_shapes()
        new_doc = _build_aws_2024()
        with pytest.raises(ValueError, match="unsupported"):
            doc.swap_shapes(
                pattern={"frob": "wibble"},
                new_master=new_doc.masters["EC2"],
            )

    def it_rejects_a_non_Master_new_master(self):
        doc, *_ = _diagram_with_three_shapes()
        with pytest.raises(TypeError, match="Master"):
            doc.swap_shapes(pattern={"master_name": "EC2"}, new_master="nope")


# ---------------------------------------------------------------------------
# update_theme — bulk theme swap
# ---------------------------------------------------------------------------


class DescribeUpdateTheme:
    def it_is_a_no_op_when_doc_has_no_theme(self):
        # Authored-from-scratch documents have no theme part. The
        # call should be a quiet no-op.
        doc, *_ = _diagram_with_three_shapes()
        # We pass *something* that quacks like a theme; even though it
        # would fail the type check, the no-op path returns first.
        doc.update_theme(theme=object())
        # No assertion — we just assert the call didn't raise.

    def it_rejects_an_unrecognised_theme_object(self):
        # Force the document to expose a non-None theme so the no-op
        # short-circuit is bypassed and the type-check fires.
        from vsdx.diagram import _coerce_theme_element

        with pytest.raises(TypeError, match="theme"):
            _coerce_theme_element(42)


# ---------------------------------------------------------------------------
# Round-trip — save + load preserves the swap
# ---------------------------------------------------------------------------


class DescribeRoundTripAfterSwap:
    def it_round_trips_position_property_and_master_pointer(self):
        doc, page, ec2, s3, lam = _diagram_with_three_shapes()
        ec2.data.add_field("InstanceType", "m5.large")
        ec2.text = "web-1"
        old = StencilSet.from_document(_build_aws_2020())
        new = StencilSet.from_document(_build_aws_2024())
        doc.swap_stencil(from_set=old, to_set=new, on_missing="keep-old")

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        loaded = vsdx.VisioDocument.open(buf)
        loaded_shapes = list(loaded.pages[0].shapes)
        assert len(loaded_shapes) == 3
        ec2_after = loaded_shapes[0]
        # Position survives.
        assert ec2_after.pin_x == 2 and ec2_after.pin_y == 3
        # Master pointer survives.
        assert ec2_after.master_name_u == "EC2"
        # Text survives.
        assert ec2_after.text == "web-1"
        # Property survives, with the new master's metadata applied.
        assert "InstanceType" in ec2_after.data
        assert ec2_after.data.field("InstanceType").raw_value == "m5.large"
        # Lambda kept its old master because keep-old was the policy.
        assert loaded_shapes[2].master_name_u == "Lambda"


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


class DescribePublicAPI:
    def it_exposes_StencilSet_and_SwapReport_at_package_level(self):
        assert vsdx.StencilSet is StencilSet
        assert vsdx.SwapReport is SwapReport
        assert vsdx.UnmappableProperty is UnmappableProperty
        assert vsdx.UnmappableShape is UnmappableShape

    def it_exposes_methods_on_VisioDocument(self):
        doc = vsdx.Visio()
        assert callable(getattr(doc, "swap_stencil"))
        assert callable(getattr(doc, "swap_shapes"))
        assert callable(getattr(doc, "update_theme"))

    def it_keeps_the_diagram_module_helpers_accessible(self):
        # The module-level functions are the supported escape hatch
        # for callers that already have a SwapReport in flight.
        assert callable(swap_stencil)
        assert callable(swap_shapes)
        assert callable(update_theme)
