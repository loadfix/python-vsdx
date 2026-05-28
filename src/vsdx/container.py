# Copyright 2026 loadfix contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""``Container`` — labelled rounded rectangle that encloses other shapes.

Container shapes are heavily used in cloud architecture diagrams to
mark logical boundaries (an AWS VPC, a subnet, a security group, an
on-prem zone, an application boundary). Visio's container shape is
fundamentally a :class:`~vsdx.shapes.group.GroupShape` carrying a
banner label and a styled outline; this proxy adds:

- the ``title`` / ``title_position`` / ``style`` / ``label_style``
  authoring kwargs;
- :attr:`auto_resize` so the container's PinX/PinY/Width/Height
  expand to fit its members at save time;
- nested-container authoring via :meth:`Container.add_container`;
- theme-or-hex colour resolution for *border_color* / *fill_color*.

Container metadata round-trips by riding on singleton ``<Cell>``
children with the ``User.Container*`` ``@N`` prefix — Visio's
ShapeSheet user-cell convention. That keeps the on-disk shape valid
in real Visio (the cells are simply user-defined rows the desktop
ignores) while letting the proxy reload its kwargs after a save.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, List, Optional, Sequence

from vsdx.enum.cells import ST_Unit
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shapes.base import _set_cell_float
from vsdx.shapes.group import GroupShape

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Shape  # TODO(vsdx/track-1)
    from vsdx.shapes.base import Shape
    from vsdx.shapes.shapetree import ShapeTree
    from vsdx.theme import ColorScheme


__all__ = [
    "CONTAINER_LABEL_STYLES",
    "CONTAINER_STYLES",
    "CONTAINER_TITLE_POSITIONS",
    "Container",
    "ContainerMembers",
]


# ---------------------------------------------------------------------------
# Public vocabulary — string-typed enums kept simple for round-trip
# ---------------------------------------------------------------------------

#: Permissible *title_position* values on :meth:`Page.add_container` /
#: :meth:`Container.add_container`. The position governs where the
#: title label is rendered relative to the container's outline.
CONTAINER_TITLE_POSITIONS: "tuple[str, ...]" = (
    "top-left",
    "top",
    "top-right",
    "bottom",
    "banner",
)

#: Permissible *style* values — outline geometry of the container.
CONTAINER_STYLES: "tuple[str, ...]" = ("rounded", "sharp")

#: Permissible *label_style* values — visual treatment of the title.
CONTAINER_LABEL_STYLES: "tuple[str, ...]" = ("plain", "banner", "tab")


# Cell-name prefix — Visio's "User-defined cells" namespace. Real Visio
# desktops display these in the User-Defined Cells section of the
# ShapeSheet but otherwise ignore them, so they round-trip cleanly.
_CELL_IS_CONTAINER = "User.IsContainer"
_CELL_TITLE = "User.ContainerTitle"
_CELL_TITLE_POSITION = "User.ContainerTitlePosition"
_CELL_STYLE = "User.ContainerStyle"
_CELL_LABEL_STYLE = "User.ContainerLabelStyle"
_CELL_AUTO_RESIZE = "User.ContainerAutoResize"
_CELL_BORDER_COLOR = "User.ContainerBorderColor"
_CELL_FILL_COLOR = "User.ContainerFillColor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_user_cell(shape_el: "CT_Shape", name: str, value: Optional[str]) -> None:
    """Create-or-update a string-valued ``<Cell N=name V=value>`` child.

    Passing ``value=None`` clears the cell entirely, matching how the
    rest of the proxy layer treats "absent" as the not-set sentinel.
    """
    if value is None:
        for cell in list(shape_el.cell_lst):
            if cell.get("N") == name:
                shape_el.remove(cell)
                return
        return
    cell = shape_el.get_or_add_cell(name)
    cell.set("V", str(value))


def _user_cell(shape_el: "CT_Shape", name: str) -> Optional[str]:
    """Return the ``@V`` of ``<Cell N=name>`` on *shape_el*, or ``None``."""
    for cell in shape_el.cell_lst:
        if cell.get("N") == name:
            return cell.get("V")
    return None


def _resolve_color(value, theme=None) -> Optional[str]:
    """Resolve *value* to an opaque RGB-hex string.

    Accepts:

    - ``None`` — returns ``None`` so the caller can leave the cell
      unset.
    - a 6-hex-digit string (with or without ``#`` prefix) — returned
      uppercased and ``#``-prefixed for canonical storage.
    - an ``(r, g, b)`` tuple of 0-255 ints — formatted to ``#RRGGBB``.
    - a string already prefixed with ``#`` — returned uppercased.
    - any other string — passed through verbatim. This lets callers
      lean on Visio's named-colour vocabulary (``"Themed"``,
      ``"BLACK"``, ``"RGB(255,0,0)"``) without the proxy second-guessing.

    Theme-reference resolution: when *value* is exactly one of the
    canonical scheme slot names (``"accent1"``…``"accent6"``,
    ``"dk1"``/``"lt1"``/``"dk2"``/``"lt2"``, ``"hlink"``/``"folHlink"``)
    *and* a :class:`~vsdx.theme.ColorScheme` is supplied, the slot's
    resolved RGB is returned. Unresolved slots fall back to the raw
    slot name (which Visio renders as a literal — the caller can spot
    the mismatch on first open).
    """
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 3:
        r, g, b = (int(c) & 0xFF for c in value)
        return f"#{r:02X}{g:02X}{b:02X}"
    if not isinstance(value, str):
        value = str(value)
    text = value.strip()
    if not text:
        return None
    # Theme slot reference?
    slots = (
        "dk1", "lt1", "dk2", "lt2",
        "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
        "hlink", "folHlink",
    )
    if theme is not None and text in slots:
        resolved = getattr(theme, text, None)
        if resolved:
            r = str(resolved).lstrip("#").upper()
            return f"#{r}"
        return text
    # 6-hex form (with or without hash).
    body = text.lstrip("#")
    if len(body) == 6 and all(c in "0123456789abcdefABCDEF" for c in body):
        return f"#{body.upper()}"
    return text


def _validate_choice(name: str, value: str, choices: "Sequence[str]") -> str:
    """Return *value* if it appears in *choices*; otherwise raise ValueError.

    Centralised so the ``add_container`` API and the property setters
    share one source of truth for the legal vocabulary.
    """
    if value not in choices:
        raise ValueError(
            f"invalid {name} {value!r}; expected one of: "
            + ", ".join(repr(c) for c in choices)
        )
    return value


def _shape_aabb(shape: "Shape") -> "tuple[float, float, float, float]":
    """Return ``(x0, y0, x1, y1)`` for *shape* in its current parent space.

    Centre-pin model: the shape's ``pin_x`` / ``pin_y`` is the centre
    and ``width`` / ``height`` cover full extent.
    """
    px = float(shape.pin_x)
    py = float(shape.pin_y)
    w = float(shape.width)
    h = float(shape.height)
    return (px - w / 2.0, py - h / 2.0, px + w / 2.0, py + h / 2.0)


# Padding (inches) added around the children's bounding box when
# auto-resize fits the container. Tracks Visio desktop's default
# container margin (~0.25 inch on each side).
_AUTO_RESIZE_PADDING = 0.25


# ---------------------------------------------------------------------------
# ContainerMembers — list-like view of contained shapes (mirrors GroupMembers)
# ---------------------------------------------------------------------------


class ContainerMembers:
    """Read view of the shapes that belong to a :class:`Container`.

    A container's *membership* is the set of shapes whose ``container=``
    kwarg was set to this container at add time, *or* that were
    nested via :meth:`Container.add_container`. The membership is
    stored verbatim in the container's nested ``<Shapes>`` child (the
    same machinery groups use), so iteration walks the underlying
    :class:`~vsdx.oxml.shapes.CT_Shapes` element.

    Construct indirectly via :attr:`Container.member_shapes` /
    :attr:`Container.shapes` — callers do not instantiate this class
    directly.

    .. versionadded:: 0.3.0
    """

    def __init__(self, container: "Container") -> None:
        self._container = container

    def __iter__(self) -> Iterator["Shape"]:
        shapes_el = self._container._element.shapes
        if shapes_el is None:
            return iter([])
        tree = self._container._parent
        return iter(tree._proxy_for(el) for el in shapes_el.shape_lst)

    def __len__(self) -> int:
        shapes_el = self._container._element.shapes
        return 0 if shapes_el is None else len(shapes_el.shape_lst)

    def __getitem__(self, idx: int) -> "Shape":
        shapes_el = self._container._element.shapes
        if shapes_el is None:
            raise IndexError(idx)
        tree = self._container._parent
        return tree._proxy_for(shapes_el.shape_lst[idx])

    def __contains__(self, item) -> bool:
        try:
            target_el = item._element
        except AttributeError:
            return False
        shapes_el = self._container._element.shapes
        if shapes_el is None:
            return False
        return any(el is target_el for el in shapes_el.shape_lst)


# ---------------------------------------------------------------------------
# Container proxy
# ---------------------------------------------------------------------------


class Container(GroupShape):
    """A labelled, optionally rounded rectangle that encloses other shapes.

    Authored via :meth:`Page.add_container` (top-level) or
    :meth:`Container.add_container` (nested). The container is
    serialised as ``<Shape Type="Group">`` carrying a small set of
    user-defined cells that record the title, label style, and
    auto-resize flag — so the metadata round-trips through save/load
    without leaning on a Visio master that may not be present in a
    fresh package.

    Once a container exists, any shape can be enrolled into it by
    setting the ``container=`` kwarg on
    :meth:`~vsdx.shapes.shapetree.ShapeTree.add_shape` (or
    :meth:`~vsdx.shapes.group.GroupMembers.add_shape` for shapes
    nested in a group). The shape is reparented under the container's
    nested ``<Shapes>`` and its PinX/PinY are converted to
    container-local coordinates, identical to the group-membership
    convention.

    .. versionadded:: 0.3.0
    """

    # Sentinel @N value on the marker cell — used by :meth:`is_container`
    # for round-trip detection on reload.
    MARKER_VALUE = "1"

    def __init__(
        self,
        shape_element: "CT_Shape",
        parent: "ShapeTree",
    ) -> None:
        super().__init__(shape_element, parent)

    # -- detection -----------------------------------------------------

    @staticmethod
    def is_container_element(shape_el: "CT_Shape") -> bool:
        """Return ``True`` if *shape_el* carries the container marker cell.

        Used by :meth:`ShapeTree._proxy_for` and the page's container
        accessor to dispatch to a :class:`Container` proxy on reload
        without consulting the Visio master catalogue.
        """
        if shape_el.get("Type") != VS_SHAPE_TYPE.GROUP.value:
            return False
        return _user_cell(shape_el, _CELL_IS_CONTAINER) == Container.MARKER_VALUE

    # -- title / position / style metadata -----------------------------

    @property
    def title(self) -> Optional[str]:
        """The container's display title (rendered as the label).

        Backed by ``<Cell N="User.ContainerTitle">``; also mirrored
        into the underlying shape's ``<Text>`` so Visio desktop renders
        the label without any extra adornment from the proxy layer.
        """
        return _user_cell(self._element, _CELL_TITLE)

    @title.setter
    def title(self, value: Optional[str]) -> None:
        _set_user_cell(self._element, _CELL_TITLE, value)
        # Mirror into the shape's text so the label renders in Visio.
        if value is None:
            text_el = getattr(self._element, "text", None)
            if text_el is not None:
                text_el.text = ""
        else:
            self.text = str(value)

    @property
    def title_position(self) -> Optional[str]:
        return _user_cell(self._element, _CELL_TITLE_POSITION)

    @title_position.setter
    def title_position(self, value: Optional[str]) -> None:
        if value is not None:
            _validate_choice("title_position", value, CONTAINER_TITLE_POSITIONS)
        _set_user_cell(self._element, _CELL_TITLE_POSITION, value)

    @property
    def style(self) -> Optional[str]:
        return _user_cell(self._element, _CELL_STYLE)

    @style.setter
    def style(self, value: Optional[str]) -> None:
        if value is not None:
            _validate_choice("style", value, CONTAINER_STYLES)
        _set_user_cell(self._element, _CELL_STYLE, value)

    @property
    def label_style(self) -> Optional[str]:
        return _user_cell(self._element, _CELL_LABEL_STYLE)

    @label_style.setter
    def label_style(self, value: Optional[str]) -> None:
        if value is not None:
            _validate_choice("label_style", value, CONTAINER_LABEL_STYLES)
        _set_user_cell(self._element, _CELL_LABEL_STYLE, value)

    @property
    def border_color(self) -> Optional[str]:
        """Resolved border colour (``#RRGGBB`` or pass-through string)."""
        return _user_cell(self._element, _CELL_BORDER_COLOR)

    @border_color.setter
    def border_color(self, value) -> None:
        resolved = _resolve_color(value, _theme_for(self))
        _set_user_cell(self._element, _CELL_BORDER_COLOR, resolved)
        # Also write to the shape-level LineColor cell so Visio renders
        # the outline in the requested colour (when it's a hex value).
        if resolved is not None and resolved.startswith("#"):
            self.line_color = resolved

    @property
    def fill_color(self) -> Optional[str]:
        return _user_cell(self._element, _CELL_FILL_COLOR)

    @fill_color.setter
    def fill_color(self, value) -> None:
        resolved = _resolve_color(value, _theme_for(self))
        _set_user_cell(self._element, _CELL_FILL_COLOR, resolved)
        if resolved is not None and resolved.startswith("#"):
            self.fill_foregnd = resolved

    # -- auto-resize ---------------------------------------------------

    @property
    def auto_resize(self) -> bool:
        """If ``True``, :meth:`fit_to_members` runs automatically on save.

        Reflected on disk as ``<Cell N="User.ContainerAutoResize" V="1">``
        so the flag round-trips. Setting to ``False`` clears the cell
        rather than writing ``"0"`` so the on-disk shape stays minimal
        for the (common) opt-out path.
        """
        raw = _user_cell(self._element, _CELL_AUTO_RESIZE)
        if raw is None:
            return False
        return raw.strip().lower() in ("1", "true", "yes", "-1")

    @auto_resize.setter
    def auto_resize(self, value: bool) -> None:
        if bool(value):
            _set_user_cell(self._element, _CELL_AUTO_RESIZE, "1")
        else:
            _set_user_cell(self._element, _CELL_AUTO_RESIZE, None)

    def fit_to_members(self) -> None:
        """Resize this container so its PinX/Y/Width/Height enclose its
        members, plus a small padding margin.

        Walks the container's nested ``<Shapes>`` (ignoring nested
        containers' own children), computes the axis-aligned bounding
        box in container-local coordinates, then translates that into
        the parent space. Member coordinates *do not change* — only
        the container's own pin / size cells are rewritten. The
        padding is the standard Visio desktop container inset
        (0.25 inch on each side).

        No-ops on an empty container.
        """
        members = list(self.member_shapes)
        if not members:
            return
        # Compute bounding box in container-local coords.
        x0 = min(_shape_aabb(s)[0] for s in members)
        y0 = min(_shape_aabb(s)[1] for s in members)
        x1 = max(_shape_aabb(s)[2] for s in members)
        y1 = max(_shape_aabb(s)[3] for s in members)
        # Pad and translate to parent-space.
        x0 -= _AUTO_RESIZE_PADDING
        y0 -= _AUTO_RESIZE_PADDING
        x1 += _AUTO_RESIZE_PADDING
        y1 += _AUTO_RESIZE_PADDING
        new_width = x1 - x0
        new_height = y1 - y0
        # The container's own PinX/PinY are in *parent* coordinates;
        # the local-origin offset is the local-coord (x0, y0). When the
        # container moves, every member's local pin shifts by the
        # opposite amount — so we adjust members in place to keep their
        # *parent-space* positions stable.
        old_origin_x = float(self.pin_x) - float(self.width) / 2.0
        old_origin_y = float(self.pin_y) - float(self.height) / 2.0
        new_origin_x = old_origin_x + x0
        new_origin_y = old_origin_y + y0
        # Update the container's own cells.
        _set_cell_float(
            self._element, "PinX", new_origin_x + new_width / 2.0,
            ST_Unit.INCHES.value,
        )
        _set_cell_float(
            self._element, "PinY", new_origin_y + new_height / 2.0,
            ST_Unit.INCHES.value,
        )
        _set_cell_float(
            self._element, "Width", new_width, ST_Unit.INCHES.value
        )
        _set_cell_float(
            self._element, "Height", new_height, ST_Unit.INCHES.value
        )
        # Shift each member by (-x0, -y0) so its local coord still
        # points at the same parent-space spot.
        for member in members:
            _set_cell_float(
                member._element, "PinX",
                float(member.pin_x) - x0, ST_Unit.INCHES.value,
            )
            _set_cell_float(
                member._element, "PinY",
                float(member.pin_y) - y0, ST_Unit.INCHES.value,
            )

    # -- members surface -----------------------------------------------

    @property
    def member_shapes(self) -> "List[Shape]":
        """Snapshot list of contained shapes.

        Equivalent to :attr:`GroupShape.member_shapes` — kept under
        the same name to ease swap-in for callers that already walk a
        group.
        """
        return super().member_shapes

    @property
    def shapes(self) -> "ContainerMembers":  # type: ignore[override]
        """List-like view over this container's contained shapes."""
        return ContainerMembers(self)

    # -- nested-container authoring ------------------------------------

    def add_container(
        self,
        title: Optional[str] = None,
        title_position: str = "top-left",
        style: str = "rounded",
        border_color=None,
        fill_color=None,
        label_style: str = "plain",
        at: "tuple[float, float]" = (0.0, 0.0),
        size: "tuple[float, float]" = (3.0, 2.0),
        auto_resize: bool = False,
    ) -> "Container":
        """Author a child container inside this one.

        The child is reparented under this container's nested
        ``<Shapes>`` so the membership relationship survives save/load.
        *at* is interpreted as parent-local (this container's local)
        coordinates so nested containers position naturally relative
        to their parent.

        Mirrors :meth:`Page.add_container` — see that method for the
        full kwarg semantics.
        """
        page = _resolve_page_from_container(self)
        if page is None:
            raise RuntimeError(
                "cannot add a nested container outside a page-bound tree"
            )

        # Author at page level first to share the master / styling
        # plumbing, then reparent under this container's nested shapes.
        child = _author_container_into_tree(
            tree=self._parent,
            page=page,
            title=title,
            title_position=title_position,
            style=style,
            border_color=border_color,
            fill_color=fill_color,
            label_style=label_style,
            at=at,
            size=size,
            auto_resize=auto_resize,
        )
        # Move the child element from page-top into this container's
        # nested <Shapes>.
        _reparent_into_container(child, self)
        return child

    # -- internal -------------------------------------------------------

    def _adopt(self, shape: "Shape") -> None:
        """Reparent *shape* under this container, converting to local coords.

        Called from :meth:`ShapeTree.add_shape` (and friends) when the
        ``container=`` kwarg is supplied — the new shape is first
        authored top-level (so it picks up a fresh ID and uses the
        usual master-instance plumbing), then handed off here to live
        inside the container.
        """
        from vsdx.shapes.group import _to_group_local

        origin_x = float(self.pin_x) - float(self.width) / 2.0
        origin_y = float(self.pin_y) - float(self.height) / 2.0
        _to_group_local(shape, origin_x, origin_y)
        shape_el = shape._element
        parent_el = shape_el.getparent()
        if parent_el is not None:
            parent_el.remove(shape_el)
        nested = self._element.get_or_add_shapes()
        nested.append(shape_el)


# ---------------------------------------------------------------------------
# Module-level helpers — invoked from ShapeTree.add_container and the
# nested Container.add_container path.
# ---------------------------------------------------------------------------


def _theme_for(shape) -> "Optional[ColorScheme]":
    """Resolve the shape's effective theme colour scheme, or ``None``.

    Walks Shape → ShapeTree → Page → Pages → VisioDocument and reads
    ``doc.theme.color_scheme``. Tolerates a missing parent chain
    (unit-test oxml-only fixtures) by returning ``None`` so the colour
    resolver falls back to the verbatim-string branch.
    """
    document = shape._owning_document() if hasattr(shape, "_owning_document") else None
    if document is None:
        return None
    theme = getattr(document, "theme", None)
    if theme is None:
        return None
    return getattr(theme, "color_scheme", None)


def _resolve_page_from_container(container: "Container"):
    """Walk up to the owning :class:`~vsdx.page.Page` from a container."""
    from vsdx.page import Page
    from vsdx.shapes.shapetree import ShapeTree

    node = container._parent
    while node is not None:
        if isinstance(node, Page):
            return node
        if isinstance(node, ShapeTree):
            node = node._parent
            continue
        node = getattr(node, "_parent", None)
    return None


def _author_container_into_tree(
    tree,
    page,
    title: Optional[str],
    title_position: str,
    style: str,
    border_color,
    fill_color,
    label_style: str,
    at: "tuple[float, float]",
    size: "tuple[float, float]",
    auto_resize: bool,
) -> "Container":
    """Mint a new container shape into *tree* and return its proxy.

    This is the shared back-end for :meth:`Page.add_container` and
    :meth:`Container.add_container` — both lower into the same
    container-creation routine; the latter then reparents the result
    into the nesting container.
    """
    page_shapes = tree._element.shapes_element
    shape_el = page_shapes._add_shape()
    shape_el.set("Type", VS_SHAPE_TYPE.GROUP.value)
    shape_el.shape_id = page.next_shape_id()

    # Materialise the nested <Shapes> immediately so the empty-container
    # save/load round-trip diff is clean.
    shape_el.get_or_add_shapes()

    # Position / size cells — parent-local for top-level, container-local
    # for nested (caller passes the right at= for each case).
    pin_x, pin_y = float(at[0]), float(at[1])
    w, h = float(size[0]), float(size[1])
    _set_cell_float(shape_el, "PinX", pin_x, ST_Unit.INCHES.value)
    _set_cell_float(shape_el, "PinY", pin_y, ST_Unit.INCHES.value)
    _set_cell_float(shape_el, "Width", w, ST_Unit.INCHES.value)
    _set_cell_float(shape_el, "Height", h, ST_Unit.INCHES.value)

    container = Container(shape_el, tree)

    # Stamp the marker cell first so subsequent property setters
    # already see a "real container" element.
    _set_user_cell(shape_el, _CELL_IS_CONTAINER, Container.MARKER_VALUE)

    # Validate vocabulary kwargs through the property setters so the
    # check stays single-sourced.
    container.title_position = _validate_choice(
        "title_position", title_position, CONTAINER_TITLE_POSITIONS
    )
    container.style = _validate_choice("style", style, CONTAINER_STYLES)
    container.label_style = _validate_choice(
        "label_style", label_style, CONTAINER_LABEL_STYLES
    )
    if title is not None:
        container.title = title
    if border_color is not None:
        container.border_color = border_color
    if fill_color is not None:
        container.fill_color = fill_color
    container.auto_resize = bool(auto_resize)
    return container


def _reparent_into_container(child: "Container", container: "Container") -> None:
    """Move *child*'s ``<Shape>`` element from page-top into *container*'s
    nested ``<Shapes>``.

    Used by :meth:`Container.add_container` after the child is authored
    at page level — this preserves the page-allocated shape ID and the
    container-marker cell while folding the child into its enclosing
    container's membership.
    """
    child_el = child._element
    parent_el = child_el.getparent()
    if parent_el is not None:
        parent_el.remove(child_el)
    nested = container._element.get_or_add_shapes()
    nested.append(child_el)
    # Re-bind the child's parent so subsequent `_owning_document()`
    # walks still climb back to the page.
    child._parent = container._parent  # type: ignore[attr-defined]
