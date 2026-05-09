"""Base classes for the vsdx shape hierarchy.

``Shape`` wraps the generic Visio ``<Shape>`` element. Named-cell
access (``.pin_x``, ``.width``, ``.line_weight``, ...) is implemented
here as lookups into the shape's direct ``<Cell N="…">`` children
because, unlike DrawingML's one-element-per-property model, Visio
stores everything on a generic cell element distinguished by its
``@N`` attribute.

``TextShape`` adds ``.text`` / ``.text_frame`` accessors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from vsdx.enum.cells import ST_Unit
from vsdx.shared import ParentedElementProxy
from vsdx.text import TextFrame
from vsdx.util import Inches, Length

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_Shape  # TODO(vsdx/track-1)
    from vsdx.shapes.shapetree import ShapeTree


# Named-cell accessor helpers ------------------------------------------------


def _cell_float(shape_el: "CT_Shape", name: str) -> Optional[float]:
    """Return the float value of ``<Cell N=name>`` or ``None`` if absent."""
    for cell in shape_el.findall("Cell"):
        if cell.get("N") == name:
            v = cell.get("V")
            if v is None or v == "":
                return None
            try:
                return float(v)
            except ValueError:
                return None
    return None


def _set_cell_float(
    shape_el: "CT_Shape", name: str, value: Optional[float], unit: str = "IN"
) -> None:
    """Create-or-update ``<Cell N=name V=value U=unit>`` on *shape_el*."""
    cell = shape_el.get_or_add_cell(name)
    if value is None:
        cell.attrib.pop("V", None)
        cell.attrib.pop("U", None)
        return
    cell.set("V", _fmt_num(value))
    cell.set("U", unit)


def _fmt_num(v: float) -> str:
    """Format a float the way Visio emits it — trim trailing zeros."""
    if v == int(v):
        return str(int(v))
    return ("%f" % v).rstrip("0").rstrip(".")


class Shape(ParentedElementProxy):
    """Base class for every shape on a page.

    Carries the named-cell convenience accessors that every concrete
    shape subclass inherits unchanged. Geometry cells (``PinX``,
    ``PinY``, ``Width``, ``Height``, ``Angle``) default to inches; line
    / fill cells carry unit-less values because they're colour indexes
    or weights.
    """

    _element: "CT_Shape"

    def __init__(self, shape_element: "CT_Shape", parent: "ShapeTree") -> None:
        super().__init__(shape_element, parent)

    # -- identity -------------------------------------------------------

    @property
    def shape_id(self) -> int:
        """The shape's unique ID within its page."""
        raw = self._element.shape_id
        return int(raw) if raw is not None else 0

    @property
    def name(self) -> Optional[str]:
        """The shape's display name (``@Name`` attribute)."""
        return self._element.get("Name") or self._element.get("NameU")

    @name.setter
    def name(self, value: str) -> None:
        self._element.set("Name", value)
        self._element.set("NameU", value)

    @property
    def master_name_u(self) -> Optional[str]:
        """The NameU of the master this shape was instantiated from, or None."""
        return self._element.get("Master") or self._element.get("MasterShape")

    @property
    def shape_type(self) -> Optional[str]:
        return self._element.get("Type")

    # -- position & size (all in inches via Length) ---------------------

    @property
    def pin_x(self) -> Length:
        """Pin X — horizontal location of the shape's pin, in inches."""
        return Inches(_cell_float(self._element, "PinX") or 0.0)

    @pin_x.setter
    def pin_x(self, value: Any) -> None:
        _set_cell_float(self._element, "PinX", float(value), ST_Unit.INCHES.value)

    @property
    def pin_y(self) -> Length:
        return Inches(_cell_float(self._element, "PinY") or 0.0)

    @pin_y.setter
    def pin_y(self, value: Any) -> None:
        _set_cell_float(self._element, "PinY", float(value), ST_Unit.INCHES.value)

    @property
    def width(self) -> Length:
        return Inches(_cell_float(self._element, "Width") or 0.0)

    @width.setter
    def width(self, value: Any) -> None:
        _set_cell_float(self._element, "Width", float(value), ST_Unit.INCHES.value)

    @property
    def height(self) -> Length:
        return Inches(_cell_float(self._element, "Height") or 0.0)

    @height.setter
    def height(self, value: Any) -> None:
        _set_cell_float(self._element, "Height", float(value), ST_Unit.INCHES.value)

    @property
    def angle(self) -> float:
        """Rotation angle in radians (Visio's native unit for Angle)."""
        return _cell_float(self._element, "Angle") or 0.0

    @angle.setter
    def angle(self, value: float) -> None:
        _set_cell_float(self._element, "Angle", float(value), ST_Unit.RADIANS.value)

    # -- line / fill (unit-less cells) ----------------------------------

    @property
    def line_weight(self) -> Optional[float]:
        return _cell_float(self._element, "LineWeight")

    @line_weight.setter
    def line_weight(self, value: Optional[float]) -> None:
        if value is None:
            return
        _set_cell_float(self._element, "LineWeight", float(value), ST_Unit.POINTS.value)

    @property
    def line_color(self) -> Optional[str]:
        """Raw LineColor cell value (typically a theme color index or RGB)."""
        cell = self._get_cell("LineColor")
        return cell.get("V") if cell is not None else None

    @line_color.setter
    def line_color(self, value: Optional[str]) -> None:
        cell = self._element.get_or_add_cell("LineColor")
        if value is None:
            cell.attrib.pop("V", None)
        else:
            cell.set("V", str(value))

    @property
    def fill_foregnd(self) -> Optional[str]:
        cell = self._get_cell("FillForegnd")
        return cell.get("V") if cell is not None else None

    @fill_foregnd.setter
    def fill_foregnd(self, value: Optional[str]) -> None:
        cell = self._element.get_or_add_cell("FillForegnd")
        if value is None:
            cell.attrib.pop("V", None)
        else:
            cell.set("V", str(value))

    # -- bulk geometry setter -------------------------------------------

    def set_geometry(self, pin_x: float, pin_y: float, width: float, height: float) -> None:
        """Set PinX / PinY / Width / Height in one call. Values in inches."""
        self.pin_x = pin_x
        self.pin_y = pin_y
        self.width = width
        self.height = height

    # -- helpers --------------------------------------------------------

    def _get_cell(self, name: str) -> Optional["CT_Cell"]:
        """Return the ``<Cell N=name>`` child, or ``None`` if absent."""
        for cell in self._element.findall("Cell"):
            if cell.get("N") == name:
                return cell  # type: ignore[return-value]
        return None


class TextShape(Shape):
    """Shape that carries in-shape text.

    Every 0.1.0 autoshape is a ``TextShape`` — the ``.text_frame`` /
    ``.text`` convenience surface is inherited via this class rather
    than defined on every concrete subclass.
    """

    @property
    def has_text_frame(self) -> bool:
        """True — every 0.1.0 shape has a text frame on demand."""
        return True

    @property
    def text_frame(self) -> TextFrame:
        """:class:`TextFrame` wrapping the ``<Text>`` child of this shape."""
        text_el = self._element.get_or_add_text()
        return TextFrame(text_el)

    @property
    def text(self) -> str:
        """Shortcut: ``shape.text`` <=> ``shape.text_frame.text``."""
        return self.text_frame.text

    @text.setter
    def text(self, value: str) -> None:
        self.text_frame.text = value


__all__ = ["Shape", "TextShape"]
