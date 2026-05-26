# Copyright 2026 loadfix contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""Live :class:`ShapeSheetContext` over the vsdx proxy / oxml layer.

The default :class:`~vsdx.formula.MappingShapeSheetContext` is fine for
unit tests and one-off evaluations against a hand-built dict, but the
authoring API needs a context that resolves :class:`CellRef` axes
against the actual Visio shape tree:

- ``Width`` → ``<Cell N="Width">`` on the shape (or its master chain).
- ``User.Scale`` → row named ``Scale`` in the ``User`` section,
  cell ``Value``.
- ``Geometry1.X1`` → row 1 of the first ``Geometry`` section, cell
  ``X``.
- ``Sheet.5!PinX`` / ``ShapeName!PinX`` — the ``PinX`` cell of the
  shape on the same page whose ``@ID`` (or ``@NameU`` / ``@Name``)
  matches the qualifier.

The implementation reads directly off ``CT_Shape`` / ``CT_Section`` /
``CT_Row`` (the xmlchemy oxml layer) so it works whether the caller
holds a :class:`~vsdx.shapes.base.Shape` proxy or a bare oxml element
(useful for sub-package consumers that don't want a hard proxy
dependency).

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from vsdx.formula.context import ShapeSheetContext
from vsdx.formula.errors import FormulaEvaluationError
from vsdx.formula.nodes import CellRef, FormulaValue

if TYPE_CHECKING:
    from vsdx.oxml._stubs import CT_Cell, CT_Row, CT_Section, CT_Shape


__all__ = ["ShapeContext"]


# Cell-name patterns recognised as "this is a *cell* in a Geometry-style
# section, not a row qualifier". Visio's geometry sections name cells
# ``X``/``Y``/``A``/``B``/``C``/``D``/``Weight`` plus their numbered
# variants for compound paths. Property / User / Scratch sections name
# rows by free-form strings, so we err on the side of treating an
# unrecognised second part as a row qualifier.
_GEOMETRY_CELL_NAMES = re.compile(
    r"^(X|Y|A|B|C|D|Weight|NoFill|NoLine|NoShow|NoSnap|NoQuickDrag)\d*$"
)


def _coerce(raw: Optional[str]) -> Optional[FormulaValue]:
    """Best-effort coercion from a raw ``@V`` string to a Python value.

    Mirrors :func:`vsdx.cell._coerce_v`; duplicated here to avoid an
    import cycle (the cell module pulls in the formula package, and
    the formula package can't pull it back).
    """

    if raw is None or raw == "":
        return None
    upper = raw.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    try:
        return float(raw)
    except ValueError:
        return raw


def _shape_singleton_value(shape_el: "CT_Shape", name: str) -> Optional[FormulaValue]:
    """Return the coerced ``@V`` of ``<Cell N=name>`` on *shape_el*.

    Reads the cell's *value* (not its formula) — recursive evaluation
    is already happening one level up via the dependency-graph driver.
    Walks the shape's master chain through the proxy when available,
    otherwise reads only the instance shape.
    """

    for cell in shape_el.cell_lst:
        if cell.get("N") == name:
            return _coerce(cell.get("V"))
    return None


def _section_for(shape_el: "CT_Shape", section_name: str) -> Optional["CT_Section"]:
    """Return the first section named *section_name* on *shape_el*.

    Visio sections are typed by ``@N`` (``User``, ``Property``,
    ``Geometry``, ``Scratch``, ...). For sections that may repeat
    (``Geometry1`` / ``Geometry2``), callers should pass the suffixed
    spelling and we resolve via the section's ``@N`` + ``@IX`` pair.
    """

    # Strip a trailing numeric suffix and treat it as the section
    # ordinal — ``Geometry1`` → ``(Geometry, 0)``, ``Geometry2`` →
    # ``(Geometry, 1)`` — Visio numbers them 1-based for display.
    base, ix = _split_section_index(section_name)
    for section in shape_el.section_lst:
        if section.get("N") != base:
            continue
        if ix is None:
            return section
        section_ix = section.get("IX")
        try:
            si = int(section_ix) if section_ix is not None else 0
        except ValueError:
            si = 0
        if si == ix:
            return section
    return None


def _split_section_index(name: str) -> "tuple[str, Optional[int]]":
    """Split ``Geometry2`` → ``("Geometry", 1)``; ``User`` → ``("User", None)``.

    A trailing numeric suffix is treated as the 1-based section ordinal
    Visio uses in cell-reference syntax. The bare base name (no suffix)
    means "the first section of this kind" so we return ``None`` and
    let :func:`_section_for` pick the first match.
    """

    match = re.match(r"^([A-Za-z_]+)(\d+)$", name)
    if match is None:
        return name, None
    base, suffix = match.group(1), int(match.group(2))
    # Visio's cell-reference syntax is 1-based — ``Geometry1`` means
    # ``IX=0`` in the on-disk numbering for the very first section, but
    # the more common Visio convention (and what dave-howard/vsdx
    # produces) is to keep the IX matching the suffix. Match
    # whichever one we find.
    return base, suffix - 1


def _row_value(
    section: "CT_Section",
    row_qualifier: Optional[str],
    cell_name: Optional[str],
) -> Optional[FormulaValue]:
    """Resolve a row+cell pair against a section and return the cell's ``@V``.

    Looks rows up by ``@N`` (named-row sections) first, falling back to
    ``@IX`` (indexed rows) when *row_qualifier* parses as an integer.
    The cell name within the row defaults to ``Value`` for User /
    Property / Scratch sections — this is the implicit shape Visio
    emits for ``<Cell V="..."/>`` rows that omit ``@N`` (the row's
    sole cell carries the value).
    """

    target_row = _find_row(section, row_qualifier)
    if target_row is None:
        return None
    target_cell_name = cell_name or "Value"
    for cell in target_row.cell_lst:
        if cell.get("N") == target_cell_name:
            return _coerce(cell.get("V"))
    # Some Visio sections (Geometry) emit cells whose @N matches the
    # *cell* axis (X / Y / A / B / ...) and the row has no Value cell.
    # If we asked for "Value" but the row has just one unnamed cell,
    # return that.
    if target_cell_name == "Value":
        cells = list(target_row.cell_lst)
        if len(cells) == 1:
            return _coerce(cells[0].get("V"))
    return None


def _find_row(
    section: "CT_Section", qualifier: Optional[str]
) -> Optional["CT_Row"]:
    """Locate the row in *section* that matches *qualifier*.

    A ``None`` qualifier returns the first row (Visio's convention for
    section refs that omit a row qualifier). A numeric qualifier
    matches ``@IX``; a non-numeric one matches ``@N``.
    """

    rows = list(section.row_lst)
    if not rows:
        return None
    if qualifier is None:
        return rows[0]
    # Numeric qualifier → IX lookup (Visio is 1-based in formula text).
    try:
        ix_target = int(qualifier)
    except ValueError:
        ix_target = None
    if ix_target is not None:
        for row in rows:
            row_ix = row.get("IX")
            try:
                ri = int(row_ix) if row_ix is not None else None
            except ValueError:
                ri = None
            if ri == ix_target:
                return row
        # Some authoring tools use 0-based IX in the XML but 1-based
        # in the formula reference. Try the off-by-one alternative.
        for row in rows:
            row_ix = row.get("IX")
            try:
                ri = int(row_ix) if row_ix is not None else None
            except ValueError:
                ri = None
            if ri == ix_target - 1:
                return row
        return None
    # Named-row lookup.
    for row in rows:
        if row.get("N") == qualifier:
            return row
    return None


def _resolve_local_ref(
    shape_el: "CT_Shape", ref: CellRef
) -> Optional[FormulaValue]:
    """Resolve a same-shape cell ref (no ``Sheet.N!`` prefix)."""

    if ref.section is None:
        # Singleton cell — look up by name on the shape.
        return _shape_singleton_value(shape_el, ref.name)
    section = _section_for(shape_el, ref.section)
    if section is None:
        return None
    # If the second token (stored in ``ref.name`` for two-part refs
    # without a row, or in ``ref.row`` for three-part refs) looks like
    # a Geometry-style cell name, treat the section ref as
    # ``section.<row=1>.<cell=name>``. Otherwise treat it as
    # ``section.<row=name>.Value``.
    if ref.row is None:
        # Two-part: ``Section.Token``.
        if _GEOMETRY_CELL_NAMES.match(ref.name):
            # Geometry-style — first row's cell named ref.name.
            return _row_value(section, row_qualifier=None, cell_name=ref.name)
        # Otherwise treat as a row-qualified value cell.
        return _row_value(section, row_qualifier=ref.name, cell_name="Value")
    # Three-part: ``Section.Row.Cell``.
    return _row_value(section, row_qualifier=ref.row, cell_name=ref.name)


def _resolve_cross_shape(
    shape_el: "CT_Shape", ref: CellRef
) -> Optional[FormulaValue]:
    """Resolve a ``Sheet.N!...`` or ``ShapeName!...`` cross-shape ref.

    Walks the owning page's ``<Shapes>`` tree to find the shape with a
    matching ``@ID`` (numeric prefix) or ``@NameU``/``@Name`` (string
    prefix), then recurses with a same-shape ref to resolve the rest
    of the qualifier.
    """

    sheet = ref.sheet or ""
    target_shape = _find_sibling_shape(shape_el, sheet)
    if target_shape is None:
        return None
    local = CellRef(
        name=ref.name,
        section=ref.section,
        row=ref.row,
        sheet=None,
        source=ref.source,
    )
    return _resolve_local_ref(target_shape, local)


def _find_sibling_shape(
    shape_el: "CT_Shape", sheet: str
) -> Optional["CT_Shape"]:
    """Search the owning page for a sibling shape matching *sheet*.

    The search walks the page's ``<PageContents>`` shape tree. *sheet*
    may be the textual ``Sheet.N`` form (numeric ID) or a bare
    shape-name (``@NameU`` / ``@Name``).
    """

    # ``Sheet.5`` form — extract the numeric ID.
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    if sheet.lower().startswith("sheet."):
        try:
            target_id = int(sheet.split(".", 1)[1])
        except (ValueError, IndexError):
            target_id = None
    elif sheet.isdigit():
        target_id = int(sheet)
    else:
        target_name = sheet

    page_root = _ascend_to_page_contents(shape_el)
    if page_root is None:
        return None
    for el in _walk_shapes(page_root):
        if target_id is not None:
            sid = el.get("ID")
            try:
                if sid is not None and int(sid) == target_id:
                    return el
            except ValueError:
                continue
        elif target_name is not None:
            if el.get("NameU") == target_name or el.get("Name") == target_name:
                return el
    return None


def _ascend_to_page_contents(shape_el: "CT_Shape"):
    """Walk up from *shape_el* until we hit the page-level ``<PageContents>``.

    Returns the ``<PageContents>`` element (or ``None`` if the shape is
    parentless — e.g. a unit-test fixture parsed in isolation).
    """

    node = shape_el.getparent()
    while node is not None:
        tag = getattr(node, "tag", "")
        if isinstance(tag, str) and tag.endswith("}PageContents"):
            return node
        if isinstance(tag, str) and tag.endswith("}Master"):
            return node
        node = node.getparent()
    return None


def _walk_shapes(root):
    """Yield every ``<Shape>`` descendant of *root* (depth-first)."""

    for child in root.iter():
        tag = getattr(child, "tag", "")
        if isinstance(tag, str) and tag.endswith("}Shape"):
            yield child


class ShapeContext(ShapeSheetContext):
    """Live :class:`ShapeSheetContext` over a shape's oxml tree.

    Resolves cell refs by walking the shape's direct ``<Cell>`` children
    and ``<Section>`` rows, and follows ``Sheet.N!`` / ``ShapeName!``
    prefixes by searching the owning page's shape tree.

    Construct via :func:`Context.for_shape` (the canonical entry point)
    rather than directly — the wrapper handles both
    :class:`~vsdx.shapes.base.Shape` proxy inputs and bare oxml
    elements.

    .. versionadded:: 0.3.0
    """

    def __init__(self, shape_el: "CT_Shape", *, strict: bool = False) -> None:
        self._shape_el = shape_el
        self._strict = strict

    def resolve(self, ref: CellRef) -> Optional[FormulaValue]:
        if ref.sheet is not None:
            value = _resolve_cross_shape(self._shape_el, ref)
        else:
            value = _resolve_local_ref(self._shape_el, ref)
        if value is None and self._strict:
            raise FormulaEvaluationError(
                f"unresolved cell reference: {ref.qualified()!r}"
            )
        return value


def for_shape(shape_or_element: object, *, strict: bool = False) -> ShapeContext:
    """Build a :class:`ShapeContext` for a shape proxy or oxml element.

    Accepts either a :class:`~vsdx.shapes.base.Shape` proxy (carries a
    ``_element`` attribute pointing at the underlying ``CT_Shape``) or
    a bare ``CT_Shape`` element. ``strict=True`` makes unresolved
    references raise :class:`FormulaEvaluationError` instead of
    yielding ``None`` (the default — matches Visio's "treat missing
    cells as zero" implicit-default rule).

    .. versionadded:: 0.3.0
    """

    element = getattr(shape_or_element, "_element", shape_or_element)
    return ShapeContext(element, strict=strict)
