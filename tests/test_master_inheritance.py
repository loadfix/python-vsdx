"""Behavioural tests for the master-chain inheritance resolver.

Covers :attr:`Shape.master`, :attr:`Shape.master_chain`,
:meth:`Shape.effective_prop`, :attr:`Shape.effective_text`, and the
fallthrough behaviour of the geometry convenience accessors (pin_x,
pin_y, width, height, angle) when the instance shape omits its own
cells.

The suite builds each scenario programmatically with
:func:`vsdx.Visio()` and :meth:`Masters.add_master` — it doesn't
need fixture ``.vsdx`` files, which keeps the suite runnable in CI
without the reference corpus volume.
"""

from __future__ import annotations

import pytest

from vsdx import Visio
from vsdx.master import Master


# -- helpers ---------------------------------------------------------


def _set_cell(element, name: str, value: str, unit: str = "IN") -> None:
    """Set or add ``<Cell N=name V=value U=unit>`` on an oxml element.

    Shape, PageSheet, and MasterContents' first shape all expose
    ``get_or_add_cell`` via the CT_Shape / CT_PageSheet descriptors.
    """
    cell = element.get_or_add_cell(name)
    cell.set("V", value)
    cell.set("U", unit)


def _master_shape_element(master: Master):
    """First ``<Shape>`` inside the master's ``<MasterContents>``.

    Materialises the master-contents ``<Shapes>`` + one ``<Shape>`` if
    the master part is still empty — matches what the ensure-style
    authoring path will do when real master authoring lands. The test
    helper keeps each test's setup tight and self-contained.
    """
    contents = master.part.element
    shapes_el = contents.get_or_add_shapes()
    if not shapes_el.shape_lst:
        shapes_el.add_shape()
    return shapes_el.shape_lst[0]


@pytest.fixture
def doc_with_two_masters():
    """Build a doc: grandparent 'Base' → parent 'Box' → instance shape.

    - ``Base`` carries PinX=1, PinY=2, Width=4, Height=3, and text
      'base-text'.
    - ``Box`` chains to ``Base`` via ``<Master Master="Base">`` and
      overrides Width=5 only.
    - The instance shape references ``Box`` and overrides PinX=9 only.

    Resolution expectation: PinX=9 (own), PinY=2 (grandparent),
    Width=5 (parent override), Height=3 (grandparent), text
    'base-text' (grandparent).
    """
    doc = Visio()

    base = doc.masters.add_master("Base")
    base_sh = _master_shape_element(base)
    _set_cell(base_sh, "PinX", "1")
    _set_cell(base_sh, "PinY", "2")
    _set_cell(base_sh, "Width", "4")
    _set_cell(base_sh, "Height", "3")
    _set_cell(base_sh, "Angle", "0.5", unit="RAD")
    text_el = base_sh.get_or_add_text()
    text_el.text = "base-text"

    box = doc.masters.add_master("Box")
    # Chain Box → Base.
    box._element.set("Master", "Base")
    box_sh = _master_shape_element(box)
    _set_cell(box_sh, "Width", "5")

    page = doc.pages.add_page("Page-1")
    shape = page.shapes.add_shape_from_master("Box", at=(0, 0))
    # Wipe the auto-set pin / width / height so inheritance is visible,
    # then override PinX only.
    el = shape._element
    for cell in list(el.cell_lst):
        if cell.get("N") in {"PinX", "PinY", "Width", "Height"}:
            el.remove(cell)
    _set_cell(el, "PinX", "9")

    return doc, base, box, shape


# -- Shape.master ----------------------------------------------------


class DescribeShapeMaster:
    def it_returns_the_direct_master(self, doc_with_two_masters):
        _, _, box, shape = doc_with_two_masters
        assert shape.master is box

    def it_returns_None_for_a_shape_without_a_master(self):
        doc = Visio()
        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape("Rectangle")
        # Rectangle IS a built-in master reference, so this resolves.
        # Strip the attribute to exercise the None path.
        shape._element.attrib.pop("Master", None)
        assert shape.master is None

    def it_returns_None_for_an_unknown_master_ref(self):
        doc = Visio()
        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape("Rectangle")
        shape._element.set("Master", "DoesNotExist")
        assert shape.master is None

    def it_resolves_by_numeric_id_too(self):
        """Spec-literal ``@Master="1"`` refs resolve via ID fallback."""
        doc = Visio()
        m = doc.masters.add_master("Alpha")
        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape("Rectangle")
        shape._element.set("Master", m.master_id)
        assert shape.master is m


# -- Shape.master_chain ----------------------------------------------


class DescribeShapeMasterChain:
    def it_walks_from_most_specific_to_root(self, doc_with_two_masters):
        _, base, box, shape = doc_with_two_masters
        chain = shape.master_chain
        assert [m.name_u for m in chain] == ["Box", "Base"]
        assert chain[0] is box
        assert chain[1] is base

    def it_is_empty_for_a_shape_with_no_master(self):
        doc = Visio()
        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape("Rectangle")
        shape._element.attrib.pop("Master", None)
        assert shape.master_chain == []

    def it_handles_a_direct_master_without_a_parent(self):
        doc = Visio()
        doc.masters.add_master("Solo")
        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape_from_master("Solo", at=(0, 0))
        assert [m.name_u for m in shape.master_chain] == ["Solo"]

    def it_breaks_cycles_with_a_log_warning(self, caplog):
        doc = Visio()
        a = doc.masters.add_master("A")
        b = doc.masters.add_master("B")
        # A -> B -> A — a cycle.
        a._element.set("Master", "B")
        b._element.set("Master", "A")

        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape_from_master("A", at=(0, 0))

        import logging
        caplog.set_level(logging.WARNING, logger="vsdx.shapes.base")
        chain = shape.master_chain

        # Chain is truncated — each master appears once, no infinite loop.
        assert [m.name_u for m in chain] == ["A", "B"]
        assert any("cycle" in r.message for r in caplog.records)


# -- Shape.effective_prop --------------------------------------------


class DescribeShapeEffectiveProp:
    def it_returns_the_shapes_own_cell_first(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        cell = shape.effective_prop("PinX")
        assert cell is not None
        assert cell.get("V") == "9"

    def it_falls_through_to_the_direct_master(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        cell = shape.effective_prop("Width")
        assert cell is not None
        # Box overrode Width=5 — that's the match.
        assert cell.get("V") == "5"

    def it_falls_through_to_the_grandparent(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        cell = shape.effective_prop("Height")
        assert cell is not None
        # Height is only defined on Base (grandparent).
        assert cell.get("V") == "3"

    def it_returns_None_when_no_one_defines_the_cell(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        assert shape.effective_prop("NonExistentCell") is None


# -- Shape.effective_text ---------------------------------------------


class DescribeShapeEffectiveText:
    def it_returns_the_instances_own_text(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        shape._element.get_or_add_text().text = "instance-text"
        assert shape.effective_text == "instance-text"

    def it_falls_back_to_the_master_text(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        # instance has no own text — resolver should surface 'base-text'.
        assert shape.effective_text == "base-text"

    def it_returns_empty_when_no_text_anywhere(self):
        doc = Visio()
        doc.masters.add_master("Empty")
        page = doc.pages.add_page("P")
        shape = page.shapes.add_shape_from_master("Empty", at=(0, 0))
        assert shape.effective_text == ""


# -- geometry accessors walk the chain --------------------------------


class DescribeGeometryPropertyInheritance:
    def it_pin_x_uses_the_instance_value_when_present(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        assert float(shape.pin_x) == 9.0

    def it_pin_y_inherits_from_grandparent(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        assert float(shape.pin_y) == 2.0

    def it_width_inherits_from_parent_override(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        assert float(shape.width) == 5.0

    def it_height_inherits_from_grandparent(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        assert float(shape.height) == 3.0

    def it_angle_inherits_from_grandparent(self, doc_with_two_masters):
        _, _, _, shape = doc_with_two_masters
        assert float(shape.angle) == pytest.approx(0.5)
