# Copyright 2026 loadfix contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for the 0.3.0 :class:`~vsdx.container.Container` proxy.

The acceptance criteria for issue #120 cover:

- ``Page.add_container(title, ...)`` API.
- Nested containers via :meth:`Container.add_container`.
- ``auto_resize`` flag — at save time the container expands to fit.
- Title-position vocabulary: top-left / top / top-right / bottom / banner.
- Theme integration — theme refs resolve to colour values.
- Round-trip safety — shape relationships and container metadata
  survive save/load.
- AWS-VPC fixture — VPC > public-subnet > ALB nested round-trip.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import io

import pytest

import vsdx
from vsdx.container import (
    CONTAINER_LABEL_STYLES,
    CONTAINER_STYLES,
    CONTAINER_TITLE_POSITIONS,
    Container,
    _resolve_color,
)


# ---------------------------------------------------------------------------
# Page.add_container — top-level authoring
# ---------------------------------------------------------------------------


class DescribePageAddContainer:
    def it_returns_a_container_proxy(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="VPC")
        assert isinstance(c, Container)

    def it_records_the_title(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="Production VPC")
        assert c.title == "Production VPC"

    def it_uses_default_title_position_top_left(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V")
        assert c.title_position == "top-left"

    def it_accepts_every_legal_title_position(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        for pos in CONTAINER_TITLE_POSITIONS:
            c = page.add_container(title="V", title_position=pos)
            assert c.title_position == pos

    def it_rejects_an_unknown_title_position(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(ValueError):
            page.add_container(title="V", title_position="middle")

    def it_accepts_every_legal_style(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        for style in CONTAINER_STYLES:
            c = page.add_container(title="V", style=style)
            assert c.style == style

    def it_rejects_an_unknown_style(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(ValueError):
            page.add_container(title="V", style="oval")

    def it_accepts_every_legal_label_style(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        for ls in CONTAINER_LABEL_STYLES:
            c = page.add_container(title="V", label_style=ls)
            assert c.label_style == ls

    def it_rejects_an_unknown_label_style(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(ValueError):
            page.add_container(title="V", label_style="halo")

    def it_resolves_a_hex_border_color_to_canonical_form(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V", border_color="ff8800")
        assert c.border_color == "#FF8800"

    def it_resolves_an_rgb_tuple_fill_color(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V", fill_color=(255, 136, 0))
        assert c.fill_color == "#FF8800"

    def it_passes_through_named_colour_strings(self) -> None:
        # "Themed" is a Visio sentinel — the proxy should not mangle it.
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V", border_color="Themed")
        assert c.border_color == "Themed"

    def it_appears_under_pages_top_level_shape_tree(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V")
        top = list(page.shapes)
        assert len(top) == 1
        assert top[0].shape_id == c.shape_id

    def it_lists_via_page_containers(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c1 = page.add_container(title="A")
        c2 = page.add_container(title="B")
        ids = [c.shape_id for c in page.containers]
        assert ids == [c1.shape_id, c2.shape_id]

    def it_does_not_list_grouped_shapes_as_containers(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.shapes.add_group(at=(1, 1), size=(2, 2))
        page.add_container(title="V")
        assert len(page.containers) == 1


# ---------------------------------------------------------------------------
# Containment via add_shape(container=...)
# ---------------------------------------------------------------------------


class DescribeShapeWithContainerKwarg:
    def it_drops_the_shape_inside_the_container(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC", at=(2, 2), size=(6, 4))
        ec2 = page.shapes.add_shape("rectangle", label="EC2", container=vpc)
        # Container should now own one member.
        assert len(vpc.member_shapes) == 1
        assert vpc.member_shapes[0].shape_id == ec2.shape_id

    def it_removes_the_shape_from_top_level(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC", at=(2, 2), size=(6, 4))
        before_top = {s.shape_id for s in page.shapes}
        ec2 = page.shapes.add_shape("rectangle", container=vpc)
        after_top = {s.shape_id for s in page.shapes}
        # ec2 should not appear at top level after adoption.
        assert ec2.shape_id not in after_top
        # The container itself is still top-level.
        assert vpc.shape_id in after_top
        # No surprise removals.
        assert before_top.issubset(after_top | {ec2.shape_id})

    def it_uses_label_kwarg_as_text(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC")
        ec2 = page.shapes.add_shape("rectangle", label="EC2", container=vpc)
        assert ec2.text == "EC2"

    def it_resolves_lowercase_master_names(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC")
        rect = page.shapes.add_shape("rectangle", container=vpc)
        # Should resolve to the Rectangle master.
        assert isinstance(rect, vsdx.Rectangle)

    def it_rejects_a_non_container_value(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        with pytest.raises(TypeError):
            page.shapes.add_shape("rectangle", container="not-a-container")


# ---------------------------------------------------------------------------
# Nested containers
# ---------------------------------------------------------------------------


class DescribeNestedContainers:
    def it_authors_a_child_container_inside_a_parent(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC", at=(2, 2), size=(8, 6))
        subnet = vpc.add_container(
            title="Public Subnet", at=(0, 0), size=(4, 3)
        )
        assert isinstance(subnet, Container)
        # Subnet appears in VPC's membership.
        assert any(
            s.shape_id == subnet.shape_id for s in vpc.member_shapes
        )

    def it_does_not_appear_at_page_top_level(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC", at=(2, 2), size=(8, 6))
        subnet = vpc.add_container(
            title="Public Subnet", at=(0, 0), size=(4, 3)
        )
        top_ids = {s.shape_id for s in page.shapes}
        assert subnet.shape_id not in top_ids

    def it_supports_grandchild_authoring(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        vpc = page.add_container(title="VPC", at=(2, 2), size=(8, 6))
        subnet = vpc.add_container(
            title="Public Subnet", at=(0, 0), size=(4, 3)
        )
        alb = page.shapes.add_shape(
            "rectangle", label="ALB", container=subnet
        )
        # The grandchild lives inside subnet, not vpc directly.
        assert any(s.shape_id == alb.shape_id for s in subnet.member_shapes)


# ---------------------------------------------------------------------------
# Auto-resize
# ---------------------------------------------------------------------------


class DescribeAutoResize:
    def it_defaults_to_false(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V")
        assert c.auto_resize is False

    def it_round_trips_when_set(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(title="V", auto_resize=True)
        assert c.auto_resize is True
        c.auto_resize = False
        assert c.auto_resize is False

    def it_expands_to_fit_members_on_save(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(
            title="VPC", at=(3, 3), size=(2, 2), auto_resize=True
        )
        # Drop two shapes wider than the initial bounding box.
        page.shapes.add_shape(
            "rectangle", at=(0, 0), size=(1, 1), container=c
        )
        page.shapes.add_shape(
            "rectangle", at=(4, 0), size=(1, 1), container=c
        )
        buf = io.BytesIO()
        doc.save(buf)
        # The container should have grown to enclose both children
        # plus the standard padding (>= 5.5 inches wide).
        assert float(c.width) > 5.0

    def it_no_ops_on_an_empty_container(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        c = page.add_container(
            title="V", at=(2, 2), size=(3, 3), auto_resize=True
        )
        original_w = float(c.width)
        original_h = float(c.height)
        c.fit_to_members()
        assert abs(float(c.width) - original_w) < 1e-6
        assert abs(float(c.height) - original_h) < 1e-6


# ---------------------------------------------------------------------------
# Theme-ref resolution
# ---------------------------------------------------------------------------


class DescribeThemeRefResolution:
    def it_resolves_an_accent_slot_against_a_color_scheme(self) -> None:
        # Stub theme that mimics ``ColorScheme`` via attribute access.
        class _StubTheme:
            accent1 = "1F77B4"

        out = _resolve_color("accent1", theme=_StubTheme())
        assert out == "#1F77B4"

    def it_returns_slot_name_when_theme_lacks_resolution(self) -> None:
        # No theme supplied — the slot name passes through verbatim
        # (Visio interprets it as the literal text).
        out = _resolve_color("accent1", theme=None)
        # No theme: pass-through string.
        assert out == "accent1"

    def it_uppercases_hex_strings_with_hash(self) -> None:
        assert _resolve_color("#abcdef") == "#ABCDEF"

    def it_uppercases_hex_strings_without_hash(self) -> None:
        assert _resolve_color("abcdef") == "#ABCDEF"

    def it_returns_none_for_none(self) -> None:
        assert _resolve_color(None) is None


# ---------------------------------------------------------------------------
# Round-trip — save / reload preserves container metadata
# ---------------------------------------------------------------------------


class DescribeContainerRoundTrip:
    def it_preserves_title_through_save_reload(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_container(title="Production VPC")
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        rp = reloaded.pages[0]
        containers = rp.containers
        assert len(containers) == 1
        assert containers[0].title == "Production VPC"

    def it_preserves_kwargs_through_save_reload(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_container(
            title="X",
            title_position="banner",
            style="rounded",
            label_style="banner",
            border_color="ff0000",
            fill_color=(0, 255, 128),
            auto_resize=True,
        )
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        c = reloaded.pages[0].containers[0]
        assert c.title == "X"
        assert c.title_position == "banner"
        assert c.style == "rounded"
        assert c.label_style == "banner"
        assert c.border_color == "#FF0000"
        assert c.fill_color == "#00FF80"
        assert c.auto_resize is True

    def it_dispatches_to_a_container_proxy_on_reload(self) -> None:
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        page.add_container(title="V")
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        top = list(reloaded.pages[0].shapes)
        assert len(top) == 1
        assert isinstance(top[0], Container)


# ---------------------------------------------------------------------------
# AWS VPC pattern fixture — the issue's headline example
# ---------------------------------------------------------------------------


class DescribeAWSVPCFixture:
    def _build(self):
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="VPC Diagram")
        vpc = page.add_container(
            title="Production VPC (10.0.0.0/16)",
            title_position="top-left",
            style="rounded",
            label_style="banner",
            at=(4, 4),
            size=(8, 6),
        )
        ec2 = page.shapes.add_shape(
            "rectangle", at=(0, 0), label="EC2", container=vpc
        )
        rds = page.shapes.add_shape(
            "rectangle", at=(2, 0), label="RDS", container=vpc
        )
        public_subnet = vpc.add_container(
            title="Public Subnet (10.0.1.0/24)",
            at=(0, 1),
            size=(4, 2),
        )
        alb = page.shapes.add_shape(
            "rectangle", at=(0, 0), label="ALB", container=public_subnet
        )
        return doc, page, vpc, ec2, rds, public_subnet, alb

    def it_authors_the_full_pattern_without_error(self) -> None:
        doc, page, vpc, ec2, rds, subnet, alb = self._build()
        assert isinstance(vpc, Container)
        assert isinstance(subnet, Container)
        # VPC contains EC2, RDS, plus the subnet.
        member_ids = {s.shape_id for s in vpc.member_shapes}
        assert ec2.shape_id in member_ids
        assert rds.shape_id in member_ids
        assert subnet.shape_id in member_ids
        # Subnet contains ALB.
        sub_ids = {s.shape_id for s in subnet.member_shapes}
        assert alb.shape_id in sub_ids

    def it_round_trips_the_full_pattern(self) -> None:
        doc, *_ = self._build()
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        rp = reloaded.pages[0]
        # One top-level container after reload (VPC); subnet is nested.
        top_containers = rp.containers
        assert len(top_containers) == 1
        rvpc = top_containers[0]
        assert rvpc.title == "Production VPC (10.0.0.0/16)"
        # VPC has three direct members: EC2, RDS, subnet.
        assert len(rvpc.member_shapes) == 3
        # Find the subnet via its title.
        nested_containers = [
            m for m in rvpc.member_shapes if isinstance(m, Container)
        ]
        assert len(nested_containers) == 1
        rsubnet = nested_containers[0]
        assert rsubnet.title == "Public Subnet (10.0.1.0/24)"
        # Subnet has one member: ALB.
        assert len(rsubnet.member_shapes) == 1
        assert rsubnet.member_shapes[0].text == "ALB"

    def it_preserves_parent_child_relationships(self) -> None:
        doc, _, vpc, ec2, rds, subnet, alb = self._build()
        # Pre-save: ALB is inside subnet, not vpc directly, not page top.
        assert alb.shape_id in {s.shape_id for s in subnet.member_shapes}
        assert alb.shape_id not in {s.shape_id for s in vpc.member_shapes}
        # Round-trip and verify the same.
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        rvpc = reloaded.pages[0].containers[0]
        rsubnet = next(
            m for m in rvpc.member_shapes if isinstance(m, Container)
        )
        rvpc_direct_ids = {s.shape_id for s in rvpc.member_shapes}
        rsubnet_ids = {s.shape_id for s in rsubnet.member_shapes}
        # ALB is in subnet only — not directly in VPC.
        alb_id = rsubnet.member_shapes[0].shape_id
        assert alb_id in rsubnet_ids
        assert alb_id not in (rvpc_direct_ids - {rsubnet.shape_id})
