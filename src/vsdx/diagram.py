# Copyright 2026 The python-ooxml authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
"""Bulk diagram-modernisation operations for Visio drawings.

Three high-level entry points hang off
:class:`~vsdx.document.VisioDocument`:

* :meth:`~vsdx.document.VisioDocument.swap_stencil` — rebind every
  shape that currently points at a master in *from_set* to the
  same-named master in *to_set*. Geometry, text, custom properties
  (a.k.a. ShapeData), and connector glue are preserved.
* :meth:`~vsdx.document.VisioDocument.swap_shapes` — surgical
  per-shape swap, useful when only a subset of shapes (matched by a
  *pattern* dict) needs the new master.
* :meth:`~vsdx.document.VisioDocument.update_theme` — replace the
  document's theme (colour scheme + font scheme + name) without
  touching shape geometry.

Worked example: modernise a 2020 architecture diagram
-----------------------------------------------------

The motivating use-case is keeping an architecture diagram in step
with an evolving icon set. Cloud vendors ship a new stencil every
year or two — the icons get redrawn, names sometimes shift, custom
properties (Region / AccountID / InstanceType) move around. A diagram
authored against the 2020 stencil should, after a single call, look
like the 2024 one without losing positions, links, or labels.

.. code-block:: python

    import vsdx
    from vsdx.diagram import StencilSet

    # Load the existing diagram and the two stencil packages.
    diagram = vsdx.Visio("aws-2020-architecture.vsdx")
    aws_2020 = StencilSet.from_document(
        vsdx.Visio("aws-2020.vssx"), label="AWS-2020",
    )
    aws_2024 = StencilSet.from_document(
        vsdx.Visio("aws-2024.vssx"), label="AWS-2024",
    )

    # Bulk swap. Any shape whose master matches a name in aws_2020 is
    # rebound to the same-named master in aws_2024.
    report = diagram.swap_stencil(
        from_set=aws_2020,
        to_set=aws_2024,
        on_missing="keep-old",   # keep-old | placeholder | error
    )
    print(
        f"swapped {report.shapes_swapped} / kept-old "
        f"{report.shapes_kept_old} / placeholder "
        f"{report.shapes_replaced_with_placeholder}"
    )
    for prop in report.unmappable_properties:
        print(f"  dropped {prop.shape_name}.{prop.property_name}")

    # Surgical override — every "EC2" shape becomes the new master,
    # bypassing whatever name_map the bulk pass would have used.
    diagram.swap_shapes(
        pattern={"master_name": "EC2"},
        new_master=aws_2024.by_name("EC2"),
    )

    # And freshen the colours.
    diagram.update_theme(theme=diagram.theme)
    diagram.save("aws-2024-architecture.vsdx")

What "preserved" means
----------------------

* **Position** — the shape's PinX / PinY / Width / Height / Angle
  cells are kept verbatim. Only ``@Master`` is rewritten.
* **Text** — the shape's own ``<Text>`` element is untouched.
* **Custom properties** — every ``<Section N="Property">`` row is
  copied into the rebound shape. Properties whose programmatic name
  exists on the new master inherit the new master's metadata
  (``Type`` / ``Label`` / ``Format``). Properties whose name does not
  exist on the new master are dropped from the shape and recorded on
  the report as :class:`UnmappableProperty`.
* **Connector glue** — connectors keep their ``ToSheet``
  shape-ID pointers; their ``ToCell`` values that index into a
  specific connection point (``Connections.X1`` / ``Connections.X2``
  / …) are re-mapped to the nearest equivalent point on the new
  master, by Euclidean distance in the master's local coordinate
  frame. Glue against the shape's pin (``PinX`` / ``PinY``) is
  identity — no remapping needed.

Stencil registry
----------------

``python-vsdx-stencils`` is the eventual home for vendor-curated
stencil sets (AWS / Azure / GCP / generic-flowchart / network-
diagram-icons / …). At the time of writing that package ships only a
skeleton — :class:`StencilSet` therefore accepts an in-memory
:class:`~vsdx.document.VisioDocument` (loaded from a ``.vssx``) or a
plain ``dict[str, Master]``. Once the registry lands, callers will be
able to write ``swap_stencil(from_set=stencils.aws_2020,
to_set=stencils.aws_2024)`` and have the package look up the right
``.vssx`` automatically. The signature of :meth:`swap_stencil`
already accepts string set-labels so the call site does not need to
change.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import logging
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Union,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from vsdx.document import VisioDocument
    from vsdx.master import Master, Masters
    from vsdx.shapes.base import Shape


_log = logging.getLogger(__name__)


__all__ = [
    "StencilSet",
    "SwapReport",
    "UnmappableProperty",
    "UnmappableShape",
    "swap_shapes",
    "swap_stencil",
    "update_theme",
]


# ---------------------------------------------------------------------------
# StencilSet — light wrapper over a name -> Master mapping
# ---------------------------------------------------------------------------


class StencilSet:
    """A name -> :class:`~vsdx.master.Master` lookup with a label.

    Constructed from any of:

    * a :class:`~vsdx.document.VisioDocument` (typically a stencil
      ``.vssx`` loaded via :func:`vsdx.Stencil` / :func:`vsdx.Visio`)
      — masters are picked up from ``doc.masters``;
    * a :class:`~vsdx.master.Masters` collection;
    * a plain :class:`dict` mapping NameU strings to
      :class:`~vsdx.master.Master` proxies.

    The *label* is opaque metadata — it shows up on the
    :class:`SwapReport` so callers can tell "AWS-2020" → "AWS-2024"
    swaps apart in a multi-stencil pipeline. It carries no semantic
    weight; matching is always by NameU.

    .. versionadded:: 0.3.0
    """

    def __init__(
        self,
        masters: "Mapping[str, Master]",
        *,
        label: Optional[str] = None,
    ) -> None:
        self._masters: "Dict[str, Master]" = dict(masters)
        self._label = label

    @classmethod
    def from_document(
        cls,
        document: "VisioDocument",
        *,
        label: Optional[str] = None,
    ) -> "StencilSet":
        """Build a :class:`StencilSet` from every master on *document*.

        Masters whose ``name_u`` is ``None`` (a malformed stencil) are
        skipped — duplicates collapse to the last-wins entry, matching
        Python ``dict`` semantics.
        """
        out: "Dict[str, Master]" = {}
        for m in document.masters:
            n = m.name_u
            if n is None:
                continue
            out[n] = m
        return cls(out, label=label)

    @classmethod
    def from_masters(
        cls,
        masters: "Iterable[Master]",
        *,
        label: Optional[str] = None,
    ) -> "StencilSet":
        """Build a :class:`StencilSet` from any iterable of masters."""
        out: "Dict[str, Master]" = {}
        for m in masters:
            n = m.name_u
            if n is None:
                continue
            out[n] = m
        return cls(out, label=label)

    @property
    def label(self) -> Optional[str]:
        """The set's opaque label, e.g. ``"AWS-2020"``."""
        return self._label

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._masters

    def __iter__(self) -> Iterator[str]:
        return iter(self._masters)

    def __len__(self) -> int:
        return len(self._masters)

    def by_name(self, name: str) -> "Optional[Master]":
        """Return the master with NameU *name*, or ``None``."""
        return self._masters.get(name)

    def names(self) -> List[str]:
        """The NameU strings in this set, in insertion order."""
        return list(self._masters.keys())


# Type alias for "anything we accept as a stencil source". String
# accepted so future registry-backed lookups can write
# ``swap_stencil(from_set='AWS-2020', ...)`` once the registry lands.
StencilLike = Union[StencilSet, "VisioDocument", Mapping[str, "Master"], str]


# ---------------------------------------------------------------------------
# Report dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnmappableProperty:
    """A custom property that did not survive the swap.

    Emitted for every ``<Section N="Property"> <Row N=...>`` whose
    programmatic name has no matching row on the new master. The
    value is the typed Python value the property carried before the
    swap.
    """

    shape_id: int
    shape_name: Optional[str]
    property_name: str
    value: Any


@dataclass(frozen=True)
class UnmappableShape:
    """A shape that could not be remapped — recorded on the report.

    ``reason`` is one of ``"missing-master"`` (the new stencil had no
    same-named master and *on_missing* was ``"keep-old"`` or
    ``"placeholder"``) or ``"explicit-error"`` (set when *on_missing*
    is ``"error"`` — though the swap then aborts, so callers will
    never see a populated report in that case).
    """

    shape_id: int
    shape_name: Optional[str]
    old_master_name: str
    reason: str


@dataclass
class SwapReport:
    """The outcome of a :meth:`~vsdx.document.VisioDocument.swap_stencil` call.

    Mutable on purpose — the swap engine appends to the lists as it
    walks the document. Once the call returns the report is read-only
    by convention.

    .. versionadded:: 0.3.0
    """

    from_set: Optional[str] = None
    to_set: Optional[str] = None
    shapes_swapped: int = 0
    shapes_kept_old: int = 0
    shapes_replaced_with_placeholder: int = 0
    unmappable_properties: List[UnmappableProperty] = field(default_factory=list)
    unmappable_shapes: List[UnmappableShape] = field(default_factory=list)
    connector_endpoints_remapped: int = 0

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            "<SwapReport from=%r to=%r swapped=%d kept-old=%d "
            "placeholder=%d unmappable_properties=%d>"
            % (
                self.from_set,
                self.to_set,
                self.shapes_swapped,
                self.shapes_kept_old,
                self.shapes_replaced_with_placeholder,
                len(self.unmappable_properties),
            )
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_stencil(stencil: StencilLike, *, role: str) -> StencilSet:
    """Normalise *stencil* to a :class:`StencilSet`.

    *role* is purely diagnostic — it shows up in the ``TypeError``
    message if *stencil* is not a recognised shape (``"from_set"`` or
    ``"to_set"``).
    """
    # Local imports defer the cycles vsdx.diagram <-> vsdx.document.
    from vsdx.document import VisioDocument
    from vsdx.master import Master, Masters

    if isinstance(stencil, StencilSet):
        return stencil
    if isinstance(stencil, VisioDocument):
        return StencilSet.from_document(stencil)
    if isinstance(stencil, Masters):
        # A bare Masters collection — borrow its label-less snapshot.
        return StencilSet.from_masters(list(stencil))
    if isinstance(stencil, Mapping):
        out: "Dict[str, Master]" = {}
        for k, v in stencil.items():
            if not isinstance(k, str):
                raise TypeError(
                    f"{role} mapping keys must be str (got {type(k).__name__})"
                )
            if not isinstance(v, Master):
                raise TypeError(
                    f"{role} mapping values must be vsdx.master.Master "
                    f"(got {type(v).__name__})"
                )
            out[k] = v
        return StencilSet(out)
    if isinstance(stencil, str):
        raise NotImplementedError(
            f"{role}=%r is a string — registry-backed lookup is "
            f"deferred until python-vsdx-stencils ships. Pass a "
            f"StencilSet or VisioDocument explicitly for now." % stencil
        )
    raise TypeError(
        f"{role} must be a StencilSet, VisioDocument, Masters, or "
        f"dict[str, Master] (got {type(stencil).__name__})"
    )


_VALID_ON_MISSING = ("keep-old", "placeholder", "error")


def _walk_shape_elements(diagram: "VisioDocument") -> "Iterator[Any]":
    """Yield every ``<Shape>`` element on every page, recursing into groups."""

    def _walk(shapes_el: Any) -> "Iterator[Any]":
        for shape_el in getattr(shapes_el, "shape_lst", []):
            yield shape_el
            nested = getattr(shape_el, "shapes", None)
            if nested is not None:
                yield from _walk(nested)

    for page in diagram.pages:
        contents = page._page_part.element  # noqa: SLF001 -- private bridge
        shapes_el = getattr(contents, "shapes_element", None)
        if shapes_el is None:
            continue
        yield from _walk(shapes_el)


def _shape_name(shape_el: Any) -> Optional[str]:
    """Return ``@Name`` / ``@NameU`` on *shape_el* — the human name."""
    return shape_el.get("Name") or shape_el.get("NameU")


def _shape_id(shape_el: Any) -> int:
    raw = getattr(shape_el, "shape_id", None)
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _master_name_u_of(shape_el: Any) -> Optional[str]:
    return shape_el.get("Master") or shape_el.get("MasterShape")


def _import_master_into(diagram: "VisioDocument", master: "Master") -> "Master":
    """Return a destination-local master matching *master*, importing or refreshing.

    Reuses the helpers on :class:`~vsdx.shapes.shapetree.ShapeTree` so
    we get the same ``@BaseID``-first / NameU-fallback match logic and
    the same deep-copy-of-master-contents behaviour.

    When a local master with the same name *already* exists (from
    e.g. a placeholder ``masters.add_master(name)`` call before the
    swap), its master-contents element is **overwritten** with a deep
    copy of *master*'s contents — so the post-swap diagram carries
    the new stencil's metadata (properties, connection points,
    geometry) on the same NameU. Idempotent in the sense that calling
    twice with the same *master* leaves the destination unchanged.
    """
    from copy import deepcopy

    from vsdx.shapes.shapetree import ShapeTree

    dest_masters = diagram.masters
    local = ShapeTree._find_local_master(dest_masters, master)  # noqa: SLF001
    if local is None:
        return ShapeTree._import_master(dest_masters, master)  # noqa: SLF001

    # Refresh the local master's contents from the source. This is
    # the difference between a "placeholder local master + new
    # source" (where the local has no properties / connection points)
    # and "we already imported this exact master earlier in the swap
    # pass" (where the deep-copy is a no-op). Detecting the no-op
    # would require diffing two trees; instead we deep-copy
    # unconditionally — cheap, and the cost is bounded by the master
    # part size, not the document size.
    src_part = master._master_part  # noqa: SLF001
    src_contents_el = src_part.element
    cloned_contents = deepcopy(src_contents_el)
    local._master_part._element = cloned_contents  # noqa: SLF001
    return local


def _typed_value(row: Any) -> Any:
    """Return the typed Python value of a Property ``<Row>``.

    Mirrors :class:`~vsdx.shape_data.ShapeDataField.value` without
    pulling the proxy in (avoids a circular import bloom for what is
    a four-line read).
    """
    from vsdx.shape_data import (
        PROPERTY_TYPE_BOOLEAN,
        PROPERTY_TYPE_CURRENCY,
        PROPERTY_TYPE_NUMBER,
        PROPERTY_TYPE_STRING,
    )

    type_v: Optional[str] = None
    raw_v: Optional[str] = None
    for cell in getattr(row, "cell_lst", []):
        n = cell.get("N")
        if n == "Type":
            type_v = cell.get("V")
        elif n == "Value":
            raw_v = cell.get("V")
    if raw_v is None or raw_v == "":
        return None
    try:
        t = int(type_v) if type_v not in (None, "") else PROPERTY_TYPE_STRING
    except ValueError:
        t = PROPERTY_TYPE_STRING
    if t in (PROPERTY_TYPE_NUMBER, PROPERTY_TYPE_CURRENCY):
        try:
            return float(raw_v)
        except ValueError:
            return raw_v
    if t == PROPERTY_TYPE_BOOLEAN:
        return raw_v.strip().lower() in ("1", "true", "yes", "-1")
    return raw_v


def _master_property_names(master: "Master") -> List[str]:
    """Return the set of ``<Row N=...>`` programmatic names on *master*.

    Walks the master's first content shape — the convention used by
    every master Visio desktop emits. Returns an empty list when the
    master carries no Property section.
    """
    content = master._content_shape_element  # noqa: SLF001 -- private bridge
    if content is None:
        return []
    names: List[str] = []
    for section in getattr(content, "section_lst", []):
        if section.get("N") != "Property":
            continue
        for row in getattr(section, "row_lst", []):
            n = row.get("N")
            if n is not None:
                names.append(n)
    return names


def _master_connection_points(master: "Master") -> List[Tuple[float, float]]:
    """Return the (x, y) coordinates of every connection point on *master*.

    Walks the master's first content shape's
    ``<Section N="Connection">`` rows; orders them by ``@IX`` ascending
    so the index of the returned list matches the ``Connections.X<n>``
    cell-name suffix Visio uses for connector glue.
    """
    content = master._content_shape_element  # noqa: SLF001
    if content is None:
        return []
    rows: List[Tuple[int, float, float]] = []
    for section in getattr(content, "section_lst", []):
        if section.get("N") != "Connection":
            continue
        for row in getattr(section, "row_lst", []):
            try:
                ix = int(row.get("IX") or 0)
            except (TypeError, ValueError):
                ix = 0
            x = _row_cell_float(row, "X")
            y = _row_cell_float(row, "Y")
            if x is None or y is None:
                continue
            rows.append((ix, x, y))
    rows.sort(key=lambda r: r[0])
    return [(x, y) for _ix, x, y in rows]


def _row_cell_float(row: Any, name: str) -> Optional[float]:
    for cell in getattr(row, "cell_lst", []):
        if cell.get("N") == name:
            v = cell.get("V")
            if v is None or v == "":
                return None
            try:
                return float(v)
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# Property-section transplant
# ---------------------------------------------------------------------------


def _transplant_properties(
    shape_el: Any,
    new_master: "Master",
    report: SwapReport,
) -> None:
    """Walk every Property row on *shape_el* and rebuild against *new_master*.

    For each row whose ``@N`` exists on the new master:

    * the row stays on the shape;
    * its ``Type`` / ``Format`` / ``Label`` / ``Prompt`` cells are
      overwritten with the new master's metadata for that property
      (so the value semantics travel with the master, not the shape).

    For each row whose ``@N`` is *not* on the new master:

    * the row is removed from the shape;
    * an :class:`UnmappableProperty` is appended to *report*.

    Properties on the new master that the shape does *not* currently
    carry are not added — Visio's master-inheritance walk picks them
    up at render time, so we don't need to materialise them on the
    instance.
    """
    new_property_names = set(_master_property_names(new_master))
    new_property_metadata = _master_property_metadata(new_master)

    section = None
    for sec in getattr(shape_el, "section_lst", []):
        if sec.get("N") == "Property":
            section = sec
            break
    if section is None:
        return

    rows_to_remove: List[Any] = []
    for row in list(getattr(section, "row_lst", [])):
        name = row.get("N")
        if name is None:
            continue
        if name in new_property_names:
            # Overwrite metadata cells from the new master — keep the
            # value the user set on the instance.
            metadata = new_property_metadata.get(name, {})
            for cell_name in ("Type", "Format", "Label", "Prompt"):
                if cell_name in metadata:
                    _set_or_replace_row_cell(row, cell_name, metadata[cell_name])
        else:
            report.unmappable_properties.append(
                UnmappableProperty(
                    shape_id=_shape_id(shape_el),
                    shape_name=_shape_name(shape_el),
                    property_name=name,
                    value=_typed_value(row),
                )
            )
            rows_to_remove.append(row)

    for row in rows_to_remove:
        section.remove(row)


def _master_property_metadata(master: "Master") -> Dict[str, Dict[str, str]]:
    """Return ``{property_name: {cell_name: cell_v}}`` for *master*'s rows.

    Used by :func:`_transplant_properties` to overwrite the shape-
    instance's property metadata after the swap, so that e.g. a
    ``Type`` cell migration from "String" (0) to "Number" (2) on the
    new master takes effect on the rebound shape.
    """
    out: Dict[str, Dict[str, str]] = {}
    content = master._content_shape_element  # noqa: SLF001
    if content is None:
        return out
    for section in getattr(content, "section_lst", []):
        if section.get("N") != "Property":
            continue
        for row in getattr(section, "row_lst", []):
            name = row.get("N")
            if name is None:
                continue
            metadata: Dict[str, str] = {}
            for cell in getattr(row, "cell_lst", []):
                cn = cell.get("N")
                cv = cell.get("V")
                if cn is not None and cv is not None:
                    metadata[cn] = cv
            out[name] = metadata
    return out


def _set_or_replace_row_cell(row: Any, name: str, value: str) -> None:
    """Create-or-update ``<Cell N=name V=value>`` on *row*."""
    for cell in getattr(row, "cell_lst", []):
        if cell.get("N") == name:
            cell.set("V", value)
            return
    cell = row._add_cell()  # noqa: SLF001 -- xmlchemy convention
    cell.set("N", name)
    cell.set("V", value)


# ---------------------------------------------------------------------------
# Connector glue remapping
# ---------------------------------------------------------------------------


_CONNECTIONS_X_PREFIX = "Connections.X"
_CONNECTIONS_Y_PREFIX = "Connections.Y"


def _parse_connection_index(cell: Optional[str]) -> Optional[int]:
    """Return the 1-based ``Connections.X<n>`` index, or ``None`` if N/A.

    Connector glue uses ``@ToCell="PinX"`` for centre-of-shape glue
    (no remapping needed) and ``@ToCell="Connections.X1"`` /
    ``"Connections.X2"`` / ... for glue to a specific connection
    point. We only remap the latter form.
    """
    if cell is None:
        return None
    if cell.startswith(_CONNECTIONS_X_PREFIX):
        suffix = cell[len(_CONNECTIONS_X_PREFIX) :]
    elif cell.startswith(_CONNECTIONS_Y_PREFIX):
        suffix = cell[len(_CONNECTIONS_Y_PREFIX) :]
    else:
        return None
    try:
        return int(suffix)
    except ValueError:
        return None


def _nearest_index(
    target: Tuple[float, float], candidates: List[Tuple[float, float]]
) -> Optional[int]:
    """Return the 1-based index of the *candidates* point nearest *target*."""
    if not candidates:
        return None
    best_index = 0
    best_d = math.inf
    for i, (cx, cy) in enumerate(candidates):
        d = (cx - target[0]) ** 2 + (cy - target[1]) ** 2
        if d < best_d:
            best_d = d
            best_index = i
    return best_index + 1  # 1-based to match Visio's ``Connections.X<n>``


def _remap_connector_glue(
    diagram: "VisioDocument",
    swapped_shape_id: int,
    old_points: List[Tuple[float, float]],
    new_points: List[Tuple[float, float]],
    report: SwapReport,
) -> None:
    """Update every ``<Connect>`` whose ``@ToSheet`` is *swapped_shape_id*.

    For each connect with a ``Connections.X<n>`` style ``@ToCell``,
    look up the (x, y) of the n-th old connection point, find the
    nearest point on the new master, and rewrite ``@ToCell`` to point
    at that new index. Connects against ``PinX`` / ``PinY`` are left
    alone — they glue to the shape's centre, not a specific anchor.
    """
    if swapped_shape_id == 0:
        return
    if not new_points:
        # The new master has no connection points — Visio falls back
        # to PinX/PinY anyway. Drop the cell-specific suffix to make
        # the fallback explicit.
        for connect_el in _iter_connects_for(diagram, swapped_shape_id):
            to_cell = connect_el.get("ToCell")
            idx = _parse_connection_index(to_cell)
            if idx is None:
                continue
            connect_el.set("ToCell", "PinX" if to_cell.startswith(_CONNECTIONS_X_PREFIX) else "PinY")
            report.connector_endpoints_remapped += 1
        return

    for connect_el in _iter_connects_for(diagram, swapped_shape_id):
        to_cell = connect_el.get("ToCell")
        idx = _parse_connection_index(to_cell)
        if idx is None:
            continue
        # ``Connections.X<n>`` is 1-based.
        old_idx0 = idx - 1
        if old_idx0 < 0 or old_idx0 >= len(old_points):
            # Glue references a connection point the old master never
            # defined — fall back to the first new point so the
            # connector keeps a target rather than dangling.
            new_index = 1
        else:
            new_index = _nearest_index(old_points[old_idx0], new_points) or 1
        prefix = (
            _CONNECTIONS_X_PREFIX
            if to_cell.startswith(_CONNECTIONS_X_PREFIX)
            else _CONNECTIONS_Y_PREFIX
        )
        new_value = f"{prefix}{new_index}"
        if to_cell != new_value:
            connect_el.set("ToCell", new_value)
            report.connector_endpoints_remapped += 1


def _iter_connects_for(
    diagram: "VisioDocument", to_sheet: int
) -> "Iterator[Any]":
    """Yield every ``<Connect>`` whose ``@ToSheet`` is *to_sheet*."""
    for page in diagram.pages:
        contents = page._page_part.element  # noqa: SLF001
        connects = getattr(contents, "connects_element", None)
        if connects is None:
            continue
        for connect_el in getattr(connects, "connect_lst", []):
            try:
                ts = int(connect_el.get("ToSheet") or 0)
            except (TypeError, ValueError):
                continue
            if ts == to_sheet:
                yield connect_el


# ---------------------------------------------------------------------------
# Top-level swap entry points
# ---------------------------------------------------------------------------


def swap_stencil(
    diagram: "VisioDocument",
    *,
    from_set: StencilLike,
    to_set: StencilLike,
    on_missing: str = "keep-old",
    name_map: Optional[Mapping[str, str]] = None,
) -> SwapReport:
    """Bulk-swap every shape in *diagram* from *from_set* to *to_set*.

    See the module docstring for the worked walkthrough.

    :param diagram: the :class:`~vsdx.document.VisioDocument` to mutate.
    :param from_set: the stencil whose masters are being replaced.
        Accepts a :class:`StencilSet`, a :class:`VisioDocument`
        (typically a loaded ``.vssx``), a :class:`~vsdx.master.Masters`
        collection, or a plain ``dict[str, Master]``. Plain strings
        like ``"AWS-2020"`` are reserved for the future
        ``python-vsdx-stencils`` registry — passing one today raises
        :class:`NotImplementedError`.
    :param to_set: the replacement stencil; same accepted forms as
        *from_set*.
    :param on_missing: behaviour when the new stencil has no master
        with the same NameU as the shape's current master:

        * ``"keep-old"`` (default) — leave the shape pointing at the
          old master, and record the unmapped shape on the report.
          The old master stays in :attr:`VisioDocument.masters` so
          render fidelity is preserved.
        * ``"placeholder"`` — rebind the shape to the built-in
          ``Rectangle`` master and record it on the report.
          Connector glue and properties are left untouched (the
          rectangle has no connection points; the shape inherits
          the rectangle's empty Property section).
        * ``"error"`` — raise :class:`KeyError` on the first unmapped
          shape.

    :param name_map: optional explicit ``{old_name: new_name}`` map
        consulted before NameU-equality. Useful when a vendor renames
        a master between releases (``EC2-Instance`` →
        ``EC2.Instance``).

    :returns: a :class:`SwapReport` summarising the swap.
    :raises KeyError: when *on_missing* is ``"error"`` and a shape's
        master is absent from *to_set*.
    :raises ValueError: when *on_missing* is not one of the supported
        tokens.

    .. versionadded:: 0.3.0
    """
    if on_missing not in _VALID_ON_MISSING:
        raise ValueError(
            "on_missing must be one of %r; got %r"
            % (_VALID_ON_MISSING, on_missing)
        )

    src = _coerce_stencil(from_set, role="from_set")
    dst = _coerce_stencil(to_set, role="to_set")
    name_map = dict(name_map or {})

    report = SwapReport(from_set=src.label, to_set=dst.label)
    placeholder_master: Optional["Master"] = None

    for shape_el in _walk_shape_elements(diagram):
        old_name = _master_name_u_of(shape_el)
        if old_name is None:
            continue
        if old_name not in src and old_name not in name_map:
            # Shape's master is not part of the from-set — leave it
            # alone. Counts as neither swapped nor kept-old (it was
            # never a candidate).
            continue
        target_name = name_map.get(old_name, old_name)
        new_master = dst.by_name(target_name)
        if new_master is None:
            if on_missing == "error":
                raise KeyError(
                    "no master named %r in to_set; shape ID=%d (%s)"
                    % (target_name, _shape_id(shape_el), _shape_name(shape_el))
                )
            if on_missing == "keep-old":
                report.shapes_kept_old += 1
                report.unmappable_shapes.append(
                    UnmappableShape(
                        shape_id=_shape_id(shape_el),
                        shape_name=_shape_name(shape_el),
                        old_master_name=old_name,
                        reason="missing-master",
                    )
                )
                continue
            # placeholder
            if placeholder_master is None:
                placeholder_master = diagram.masters.ensure("Rectangle")
            _rebind_shape(shape_el, placeholder_master, src, report, diagram)
            report.shapes_replaced_with_placeholder += 1
            report.unmappable_shapes.append(
                UnmappableShape(
                    shape_id=_shape_id(shape_el),
                    shape_name=_shape_name(shape_el),
                    old_master_name=old_name,
                    reason="missing-master",
                )
            )
            continue

        _rebind_shape(shape_el, new_master, src, report, diagram)
        report.shapes_swapped += 1

    return report


def _rebind_shape(
    shape_el: Any,
    new_master: "Master",
    src: StencilSet,
    report: SwapReport,
    diagram: "VisioDocument",
) -> None:
    """Point *shape_el* at *new_master*, transplanting properties + glue."""
    # 1. Make sure the new master is registered on the destination
    # document so ``@Master=<NameU>`` resolves at load time. Idempotent.
    local_new = _import_master_into(diagram, new_master)

    # 2. Collect connection-point coordinates of the old + new
    # masters BEFORE rewriting ``@Master`` — the old-master lookup
    # needs the original name.
    old_name = _master_name_u_of(shape_el)
    old_master = src.by_name(old_name) if old_name else None
    old_points = _master_connection_points(old_master) if old_master else []
    new_points = _master_connection_points(local_new)

    # 3. Rewrite the master pointer.
    shape_el.set("Master", local_new.name_u)

    # 4. Transplant the Property section.
    _transplant_properties(shape_el, local_new, report)

    # 5. Remap connector glue.
    _remap_connector_glue(
        diagram,
        _shape_id(shape_el),
        old_points,
        new_points,
        report,
    )


# ---------------------------------------------------------------------------
# Targeted swap: pattern -> new master
# ---------------------------------------------------------------------------


def swap_shapes(
    diagram: "VisioDocument",
    *,
    pattern: Mapping[str, Any],
    new_master: "Master",
) -> int:
    """Swap every shape matching *pattern* to point at *new_master*.

    *pattern* is a small dict expressing match conditions. Supported
    keys:

    * ``master_name`` — match shapes whose ``@Master`` (NameU) equals
      this string.
    * ``shape_name`` — match shapes whose ``@Name`` / ``@NameU``
      equals this string.
    * ``shape_type`` — match shapes whose ``@Type`` (Visio's element
      kind: ``"Shape"``, ``"Group"``, ``"Foreign"``) equals this
      string.

    All supplied conditions must hold (logical AND). Returns the
    number of shapes that were rebound.

    Property transplant + connector-glue remapping use the same
    logic as :func:`swap_stencil`. Unmappable properties are
    silently dropped — call sites that need a report should use
    :func:`swap_stencil` with a one-master stencil instead.

    :raises TypeError: if *new_master* is not a :class:`~vsdx.master.Master`.
    :raises ValueError: if *pattern* is empty or contains an
        unsupported key.

    .. versionadded:: 0.3.0
    """
    from vsdx.master import Master

    if not isinstance(new_master, Master):
        raise TypeError(
            "new_master must be a vsdx.master.Master, got %s"
            % type(new_master).__name__
        )

    if not pattern:
        raise ValueError("pattern must not be empty")
    supported = {"master_name", "shape_name", "shape_type"}
    unknown = set(pattern.keys()) - supported
    if unknown:
        raise ValueError(
            "unsupported pattern keys: %s (supported: %s)"
            % (sorted(unknown), sorted(supported))
        )

    # Build a one-shot "from" stencil that resolves any current master
    # name on a matched shape to the source proxy — needed so the
    # connection-point remapper knows what the old master looked like.
    src_dict: Dict[str, Master] = {}
    for m in diagram.masters:
        n = m.name_u
        if n is not None:
            src_dict[n] = m
    src_stencil = StencilSet(src_dict)

    # Throw-away report — caller doesn't see one, by design (the
    # surface is "I know what I'm doing, just do it").
    report = SwapReport()

    swapped = 0
    for shape_el in _walk_shape_elements(diagram):
        if not _matches_pattern(shape_el, pattern):
            continue
        _rebind_shape(shape_el, new_master, src_stencil, report, diagram)
        swapped += 1

    return swapped


def _matches_pattern(shape_el: Any, pattern: Mapping[str, Any]) -> bool:
    """Return ``True`` when *shape_el* satisfies every key in *pattern*."""
    expected_master = pattern.get("master_name")
    if expected_master is not None and _master_name_u_of(shape_el) != expected_master:
        return False
    expected_name = pattern.get("shape_name")
    if expected_name is not None and _shape_name(shape_el) != expected_name:
        return False
    expected_type = pattern.get("shape_type")
    if expected_type is not None and (shape_el.get("Type") or "") != expected_type:
        return False
    return True


# ---------------------------------------------------------------------------
# Bulk theme update
# ---------------------------------------------------------------------------


def update_theme(diagram: "VisioDocument", *, theme: Any) -> None:
    """Apply *theme* to *diagram* by deep-copying its theme element.

    *theme* may be:

    * a :class:`~vsdx.theme.Theme` proxy (typically loaded from a
      different document);
    * a raw lxml element rooted at ``a:theme``;
    * any object exposing a ``.part`` attribute that has a
      ``theme_element`` (the proxy contract).

    The replacement preserves the part name (``/visio/theme/theme1.xml``)
    and the document's relationship to it; only the in-memory element
    is swapped. When the document has no theme part (e.g. authored
    from scratch), this is a no-op — track-4 seed-template injection
    still pending.

    :raises TypeError: if *theme* doesn't expose a recognisable theme
        element.

    .. versionadded:: 0.3.0
    """
    own = diagram.theme
    if own is None:
        # Document carries no theme part — caller wants a theme but
        # there's nothing to overwrite. Bail quietly; once track-4
        # lands we can synthesize a theme part on demand.
        _log.info(
            "VisioDocument.update_theme called on a document with no "
            "theme part; skipping. Authored-from-scratch packages do "
            "not yet carry a default theme."
        )
        return

    new_element = _coerce_theme_element(theme)
    own_part = own.part
    own_part._element = deepcopy(new_element)  # noqa: SLF001 -- private bridge


def _coerce_theme_element(theme: Any) -> Any:
    """Return the lxml ``a:theme`` element of *theme*."""
    from vsdx.parts.theme import ThemePart
    from vsdx.theme import Theme

    if isinstance(theme, Theme):
        return theme.part._element  # noqa: SLF001
    if isinstance(theme, ThemePart):
        return theme._element  # noqa: SLF001
    # Duck-type: anything with a .part attribute that has _element.
    part = getattr(theme, "part", None)
    if part is not None and hasattr(part, "_element"):
        return part._element  # noqa: SLF001
    # Fallback: assume it's a bare lxml element. Cheap shape check —
    # any object that quacks like an Element exposes ``.tag``.
    if hasattr(theme, "tag"):
        return theme
    raise TypeError(
        "theme must be a vsdx.theme.Theme, ThemePart, or lxml element; "
        "got %s" % type(theme).__name__
    )
