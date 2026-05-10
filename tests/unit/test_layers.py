"""Unit tests for the 0.2.0 ``Layers`` / ``Layer`` proxy.

BDD-style per the project's test conventions. Tests assert both the
proxy surface (``page.layers.add(...)``, ``layer.visible``, etc.) and
the round-trip invariants on the underlying XML — LayerMember cell
ordering, monotonic @IX assignment, delete-renumber semantics.

.. versionadded:: 0.2.0
"""

from __future__ import annotations

import pytest

import vsdx
from vsdx.layers import (
    Layer,
    _set_shape_layer_indices,
    _shape_layer_indices,
)


def _fresh_page():
    """Return a ``(doc, page)`` pair with one autoshape on the page."""
    doc = vsdx.Visio()
    page = doc.pages.add_page(name="Page-1")
    page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
    return doc, page


class DescribeLayersCollection:
    def it_exposes_no_layers_on_a_fresh_page(self) -> None:
        _, page = _fresh_page()
        assert list(page.layers) == []
        assert len(page.layers) == 0

    def it_materialises_a_layer_section_on_first_add(self) -> None:
        _, page = _fresh_page()
        layer = page.layers.add("Background")
        assert isinstance(layer, Layer)
        assert layer.name == "Background"
        assert layer.index == 0
        assert len(page.layers) == 1

    def it_assigns_monotonic_indices(self) -> None:
        _, page = _fresh_page()
        first = page.layers.add("Draft")
        second = page.layers.add("Final")
        third = page.layers.add("Archive")
        assert [first.index, second.index, third.index] == [0, 1, 2]

    def it_defaults_new_layers_to_visible_and_printable(self) -> None:
        _, page = _fresh_page()
        layer = page.layers.add("Decor")
        assert layer.visible is True
        assert layer.print is True
        assert layer.color == "Themed"

    def it_accepts_visibility_kwargs_at_creation(self) -> None:
        _, page = _fresh_page()
        hidden = page.layers.add(
            "Guides", visible=False, print=False, color="Red"
        )
        assert hidden.visible is False
        assert hidden.print is False
        assert hidden.color == "Red"

    def it_looks_up_layers_by_name(self) -> None:
        _, page = _fresh_page()
        page.layers.add("Alpha")
        beta = page.layers.add("Beta")
        assert page.layers.get("Beta") is not None
        assert page.layers.get("Beta").index == beta.index
        assert page.layers.get("Gamma") is None


class DescribeLayerProperties:
    def it_exposes_name_visible_print_lock_color(self) -> None:
        _, page = _fresh_page()
        layer = page.layers.add("X")
        layer.visible = False
        layer.print = False
        layer.locked = True
        layer.color = "Blue"
        assert layer.visible is False
        assert layer.print is False
        assert layer.locked is True
        assert layer.color == "Blue"

    def it_syncs_nameuniv_on_name_assignment(self) -> None:
        _, page = _fresh_page()
        layer = page.layers.add("Draft")
        assert layer.name_univ == "Draft"

    def it_permits_divergent_nameuniv_override(self) -> None:
        _, page = _fresh_page()
        layer = page.layers.add("Brouillon")
        layer.name_univ = "Draft"  # universal English name
        assert layer.name == "Brouillon"
        assert layer.name_univ == "Draft"


class DescribeShapeLayerMembership:
    def it_starts_with_no_layer_memberships(self) -> None:
        _, page = _fresh_page()
        shape = page.shapes[0]
        assert shape.layers == []

    def it_joins_a_shape_to_layers(self) -> None:
        _, page = _fresh_page()
        draft = page.layers.add("Draft")
        shape = page.shapes[0]
        shape.set_layers([draft])
        assert [L.index for L in shape.layers] == [0]

    def it_handles_multi_layer_membership(self) -> None:
        _, page = _fresh_page()
        draft = page.layers.add("Draft")
        final = page.layers.add("Final")
        shape = page.shapes[0]
        shape.set_layers([draft, final])
        assert _shape_layer_indices(shape._element) == [0, 1]

    def it_preserves_supplied_order_for_round_trip(self) -> None:
        # Invariant #3 from scoping doc §2.5: LayerMember ordering must
        # round-trip verbatim — never re-sort.
        _, page = _fresh_page()
        shape = page.shapes[0]
        _set_shape_layer_indices(shape._element, [5, 0, 2])
        assert _shape_layer_indices(shape._element) == [5, 0, 2]

    def it_resolves_shapes_on_a_layer(self) -> None:
        _, page = _fresh_page()
        layer = page.layers.add("Decor")
        shape = page.shapes[0]
        shape.set_layers([layer])
        resolved = list(page.layers.shapes_on(layer))
        assert len(resolved) == 1


class DescribePageLayerConvenience:
    def it_adds_a_layer_via_page_add_layer(self) -> None:
        _, page = _fresh_page()
        layer = page.add_layer("Draft")
        assert isinstance(layer, Layer)
        assert layer.name == "Draft"
        assert layer.visible is True
        assert layer.print is True

    def it_routes_print_underscore_through_add_layer(self) -> None:
        _, page = _fresh_page()
        hidden = page.add_layer("Guides", visible=False, print_=False)
        assert hidden.visible is False
        assert hidden.print is False
        assert hidden.print_ is False  # alias agrees with ``print``

    def it_looks_up_a_layer_via_page_layer(self) -> None:
        _, page = _fresh_page()
        page.add_layer("Alpha")
        assert page.layer("Alpha") is not None
        assert page.layer("Alpha").name == "Alpha"
        assert page.layer("Missing") is None


class DescribeLayerFluentSetters:
    def it_supports_set_visible_chain(self) -> None:
        _, page = _fresh_page()
        layer = page.add_layer("Guides")
        returned = layer.set_visible(False)
        assert returned is layer  # fluent return
        assert layer.visible is False

    def it_supports_set_printable_chain(self) -> None:
        _, page = _fresh_page()
        layer = page.add_layer("Guides")
        returned = layer.set_printable(False)
        assert returned is layer
        assert layer.print is False

    def it_exposes_lock_as_an_alias_of_locked(self) -> None:
        _, page = _fresh_page()
        layer = page.add_layer("Guides")
        layer.lock = True
        assert layer.locked is True
        assert layer.lock is True


class DescribeShapeAddRemoveFromLayer:
    def it_adds_a_shape_to_a_layer(self) -> None:
        _, page = _fresh_page()
        layer = page.add_layer("Draft")
        shape = page.shapes[0]
        shape.add_to_layer(layer)
        assert [L.index for L in shape.layers] == [0]

    def it_is_idempotent_on_double_add(self) -> None:
        _, page = _fresh_page()
        layer = page.add_layer("Draft")
        shape = page.shapes[0]
        shape.add_to_layer(layer)
        shape.add_to_layer(layer)  # duplicate no-op
        assert _shape_layer_indices(shape._element) == [0]

    def it_appends_to_existing_memberships_preserving_order(self) -> None:
        _, page = _fresh_page()
        first = page.add_layer("First")
        second = page.add_layer("Second")
        third = page.add_layer("Third")
        shape = page.shapes[0]
        shape.add_to_layer(second)  # [1]
        shape.add_to_layer(first)  # [1, 0]
        shape.add_to_layer(third)  # [1, 0, 2]
        assert _shape_layer_indices(shape._element) == [1, 0, 2]

    def it_removes_a_shape_from_a_layer(self) -> None:
        _, page = _fresh_page()
        a = page.add_layer("A")
        b = page.add_layer("B")
        shape = page.shapes[0]
        shape.set_layers([a, b])
        shape.remove_from_layer(a)
        assert _shape_layer_indices(shape._element) == [1]

    def it_is_idempotent_on_remove_when_not_a_member(self) -> None:
        _, page = _fresh_page()
        a = page.add_layer("A")
        b = page.add_layer("B")
        shape = page.shapes[0]
        shape.set_layers([a])
        shape.remove_from_layer(b)  # b is not a member; no-op
        assert _shape_layer_indices(shape._element) == [0]

    def it_clears_the_cell_when_last_membership_removed(self) -> None:
        _, page = _fresh_page()
        solo = page.add_layer("Solo")
        shape = page.shapes[0]
        shape.add_to_layer(solo)
        shape.remove_from_layer(solo)
        assert _shape_layer_indices(shape._element) == []
        # The cell itself should be gone.
        assert not any(
            cell.get("N") == "LayerMember"
            for cell in shape._element.cell_lst
        )


class DescribeLayerPersistence:
    """End-to-end: 3 shapes on 2 layers, toggle, save/reload, assert."""

    def it_round_trips_layers_and_membership_through_save_reload(self) -> None:
        import io

        # -- build: 3 shapes on 2 layers --
        doc = vsdx.Visio()
        page = doc.pages.add_page(name="P1")
        draft = page.add_layer("Draft", visible=True, print_=True)
        final = page.add_layer("Final", visible=True, print_=True)
        s1 = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(1, 1))
        s2 = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(2, 2))
        s3 = page.shapes.add_shape(vsdx.VS_SHAPE_TYPE.RECTANGLE, at=(3, 3))
        s1.add_to_layer(draft)
        s2.add_to_layer(final)
        s3.add_to_layer(draft)
        s3.add_to_layer(final)
        # -- toggle: Final layer goes invisible + non-printing via fluent form
        final.set_visible(False).set_printable(False)

        # -- save to a BytesIO, then open it again --
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        reloaded = vsdx.Visio(buf)
        rp = reloaded.pages[0]

        # -- layer metadata survives --
        rdraft = rp.layer("Draft")
        rfinal = rp.layer("Final")
        assert rdraft is not None and rfinal is not None
        assert rdraft.visible is True
        assert rdraft.print is True
        assert rfinal.visible is False
        assert rfinal.print is False
        assert [L.name for L in rp.layers] == ["Draft", "Final"]

        # -- shape membership survives --
        memberships = [
            sorted(L.index for L in shape.layers) for shape in rp.shapes
        ]
        # s1 -> [Draft], s2 -> [Final], s3 -> [Draft, Final]
        assert memberships == [
            [rdraft.index],
            [rfinal.index],
            sorted([rdraft.index, rfinal.index]),
        ]


class DescribeLayerDeleteRenumber:
    def it_renumbers_layers_on_delete(self) -> None:
        _, page = _fresh_page()
        a = page.layers.add("A")
        b = page.layers.add("B")
        c = page.layers.add("C")
        assert [a.index, b.index, c.index] == [0, 1, 2]
        page.layers.remove(b)
        # After removing B, C should now be at index 1.
        remaining = list(page.layers)
        assert [L.name for L in remaining] == ["A", "C"]
        assert [L.index for L in remaining] == [0, 1]

    def it_rewrites_layer_member_cells_on_delete(self) -> None:
        _, page = _fresh_page()
        a = page.layers.add("A")
        b = page.layers.add("B")
        c = page.layers.add("C")
        shape = page.shapes[0]
        shape.set_layers([a, b, c])  # indices [0, 1, 2]
        page.layers.remove(b)
        # b (index 1) is dropped, c's index 2 shifts to 1.
        assert _shape_layer_indices(shape._element) == [0, 1]

    def it_clears_layer_member_cell_when_all_memberships_gone(self) -> None:
        _, page = _fresh_page()
        solo = page.layers.add("Solo")
        shape = page.shapes[0]
        shape.set_layers([solo])
        page.layers.remove(solo)
        # Cell should be gone entirely; a shape with no layers has no cell.
        from vsdx.layers import _shape_layer_indices
        assert _shape_layer_indices(shape._element) == []
