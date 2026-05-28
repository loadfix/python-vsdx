# Copyright 2026 the python-vsdx authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.
"""Layered architecture views — logical / physical / network in one builder.

A :class:`LayeredView` is a *logical* authoring helper, not a Visio
schema feature. It captures one set of architectural entities and
relationships once, with a per-layer descriptor for each entity, and
projects each layer to its own freshly-rendered ``.vsdx`` page.

Typical AWS architecture in 3 views::

    from vsdx import Visio

    doc = Visio()
    page = doc.pages.add_page("AWS Service Map")

    arch = page.add_layered_view(
        layers=["logical", "physical", "network"]
    )

    arch.add_entity(
        "app-server",
        logical={"kind": "service",   "name": "Order Service"},
        physical={"kind": "ec2",      "name": "i-abc123",
                  "instance_type": "m5.large"},
        network={"kind": "eni",       "name": "eni-001",
                  "ip": "10.0.1.5"},
    )
    arch.add_entity(
        "database",
        logical={"kind": "datastore", "name": "Orders DB"},
        physical={"kind": "rds",      "name": "orders-prod",
                  "engine": "postgres"},
        network={"kind": "eni",       "name": "eni-002",
                  "ip": "10.0.2.10"},
    )

    arch.add_relationship("app-server", "database", kind="reads-writes")

    arch.show("logical").save_to_page("logical.vsdx")
    arch.show("physical").save_to_page("physical.vsdx")
    arch.show("network").save_to_page("network.vsdx")

Each ``show("…").save_to_page("…")`` writes a brand-new single-page
``.vsdx`` with the entities and connectors picked from the matching
layer. Entities missing a descriptor for that layer are silently
omitted and any relationship whose endpoints are not both present in
that layer is dropped.

Round-trip is supported through :meth:`VisioDocument.save` /
:func:`load_layered_view` — the entity / relationship / layer
configuration is serialised as JSON inside a custom XML part
(``/customXml/layeredView{N}.xml``) so subsequent sessions recover
the builder verbatim.

Default shape masters per ``kind`` (uses the built-in
:class:`~vsdx.shapes.Rectangle` / :class:`~vsdx.shapes.Ellipse`
masters so the view renders without depending on
``python-vsdx-stencils``):

==============  ==================================================
``kind``        master
==============  ==================================================
``service``     Rectangle (rounded role)
``datastore``   Ellipse (cylinder stand-in)
``ec2``         Rectangle (AWS rectangle stand-in)
``rds``         Ellipse (cylinder stand-in)
``eni``         Rectangle (small)
*(any other)*   Rectangle
==============  ==================================================

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import json
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.page import Page


__all__ = [
    "DEFAULT_KIND_MASTERS",
    "LAYERED_VIEW_CONTENT_TYPE",
    "LAYERED_VIEW_PARTNAME_TMPL",
    "LayeredView",
    "LayeredViewRenderer",
    "load_layered_view",
]


#: Mapping from a ``kind`` value to the built-in master ``NameU`` used
#: when rendering entities of that kind. Lookups fall through to
#: :data:`DEFAULT_FALLBACK_MASTER` for unknown kinds so authoring is
#: forgiving — a user-defined ``kind`` like ``"lambda"`` still emits a
#: visible shape.
DEFAULT_KIND_MASTERS: Dict[str, str] = {
    "service": "Rectangle",
    "datastore": "Ellipse",
    "ec2": "Rectangle",
    "rds": "Ellipse",
    "eni": "Rectangle",
    "vpc": "Rectangle",
    "subnet": "Rectangle",
    "queue": "Rectangle",
    "topic": "Rectangle",
    "function": "Rectangle",
    "bucket": "Ellipse",
    "user": "Triangle",
    "role": "Triangle",
}

#: Master used when a ``kind`` is not present in
#: :data:`DEFAULT_KIND_MASTERS`.
DEFAULT_FALLBACK_MASTER = "Rectangle"


#: Default per-shape footprint, in inches. Picked to be visually
#: distinct on a default 8.5x11 page without overflowing it for typical
#: 4-8 entity diagrams.
DEFAULT_SHAPE_SIZE: Tuple[float, float] = (1.6, 1.0)
DEFAULT_SHAPE_SIZE_SMALL: Tuple[float, float] = (1.0, 0.6)


#: Content-type used when persisting the LayeredView config as a
#: customXml-style part.  Office consumers ignore application/xml parts
#: they don't recognise so this is safe to ship inside drawings opened
#: by Microsoft Visio desktop.
LAYERED_VIEW_CONTENT_TYPE = "application/xml"

#: Partname template used by the round-trip writer.  ``%d`` is allocated
#: by :meth:`OpcPackage.next_partname`.
LAYERED_VIEW_PARTNAME_TMPL = "/visio/layeredViews/layeredView%d.xml"


#: JSON-payload schema marker. Helps ``load_layered_view`` reject
#: arbitrary application/xml-or-json parts that happen to share the
#: partname template.
LAYERED_VIEW_SCHEMA = "vsdx.layered-view/1"


# ---------------------------------------------------------------------------
# Per-kind shape sizing
# ---------------------------------------------------------------------------


def _master_for_kind(kind: str) -> str:
    """Return the master ``NameU`` to use for an entity of *kind*.

    Falls through to :data:`DEFAULT_FALLBACK_MASTER` when *kind* is not
    present in :data:`DEFAULT_KIND_MASTERS`. Lookups are case-insensitive
    so callers that mix ``"EC2"`` / ``"ec2"`` get a consistent result.
    """
    if not isinstance(kind, str):
        return DEFAULT_FALLBACK_MASTER
    lookup = kind.strip().lower()
    return DEFAULT_KIND_MASTERS.get(lookup, DEFAULT_FALLBACK_MASTER)


def _size_for_kind(kind: str) -> Tuple[float, float]:
    """Return the default ``(width, height)`` in inches for *kind*.

    ``eni`` (and any future "small leaf") gets the small footprint;
    everything else gets the standard one.
    """
    if isinstance(kind, str) and kind.strip().lower() in ("eni",):
        return DEFAULT_SHAPE_SIZE_SMALL
    return DEFAULT_SHAPE_SIZE


# ---------------------------------------------------------------------------
# Public proxy classes
# ---------------------------------------------------------------------------


class LayeredView:
    """Logical authoring helper for multi-view (layered) architectures.

    Construct via :meth:`Page.add_layered_view`. Entities and
    relationships are accumulated in source order; rendering is
    deferred until :meth:`show` is called.

    .. versionadded:: 0.3.0
    """

    def __init__(
        self,
        layers: Sequence[str],
        page: "Optional[Page]" = None,
        name: Optional[str] = None,
    ) -> None:
        if not layers:
            raise ValueError("LayeredView requires at least one layer name")
        seen: set[str] = set()
        normalised: List[str] = []
        for layer in layers:
            if not isinstance(layer, str) or not layer.strip():
                raise ValueError(
                    "layer names must be non-empty strings, got %r" % (layer,)
                )
            if layer in seen:
                raise ValueError("duplicate layer name: %r" % (layer,))
            seen.add(layer)
            normalised.append(layer)
        self._layers: List[str] = normalised
        self._entities: "List[Tuple[str, Dict[str, Dict[str, Any]]]]" = []
        self._entity_index: Dict[str, int] = {}
        self._relationships: "List[Dict[str, Any]]" = []
        self._page = page
        self._name = name

    # -- introspection --------------------------------------------------

    @property
    def layers(self) -> List[str]:
        """The configured layer names, in declaration order."""
        return list(self._layers)

    @property
    def name(self) -> Optional[str]:
        """The optional logical name for this view (used in repr / save).

        Defaults to the owning page's name when added via
        :meth:`Page.add_layered_view`.
        """
        return self._name

    @property
    def entity_ids(self) -> List[str]:
        """All entity ids, in insertion order."""
        return [eid for eid, _ in self._entities]

    @property
    def relationships(self) -> "List[Dict[str, Any]]":
        """Read-only copy of the relationship descriptors."""
        return [dict(r) for r in self._relationships]

    def entity(self, entity_id: str) -> "Dict[str, Dict[str, Any]]":
        """Return the per-layer descriptor mapping for *entity_id*.

        Raises :class:`KeyError` when no entity carries that id.
        """
        if entity_id not in self._entity_index:
            raise KeyError(entity_id)
        idx = self._entity_index[entity_id]
        return dict(self._entities[idx][1])

    # -- authoring ------------------------------------------------------

    def add_entity(
        self,
        entity_id: str,
        **per_layer_descriptors: Mapping[str, Any],
    ) -> "LayeredView":
        """Add an entity carrying one descriptor per layer.

        :param entity_id: a unique-within-this-view string handle.
            Used as the ``add_relationship`` source/target reference and
            as the auto-label fallback when a layer descriptor omits
            ``name``.
        :param per_layer_descriptors: keyword arguments where each
            keyword is a layer name (must appear in :attr:`layers`) and
            each value is a mapping with at least a ``kind`` (and
            usually a ``name``) plus arbitrary metadata. A layer may
            be omitted entirely — the entity will simply not appear
            in that layer's render.

        :returns: ``self`` for fluent chaining.

        :raises ValueError: if *entity_id* is empty / re-used, if an
            unknown layer name is supplied, or if a descriptor is not a
            mapping.
        """
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("entity_id must be a non-empty string")
        if entity_id in self._entity_index:
            raise ValueError(
                "entity_id %r is already declared in this view" % entity_id
            )
        descriptors: Dict[str, Dict[str, Any]] = {}
        for layer_name, descriptor in per_layer_descriptors.items():
            if layer_name not in self._layers:
                raise ValueError(
                    "unknown layer %r for entity %r (configured layers: %r)"
                    % (layer_name, entity_id, self._layers)
                )
            if not isinstance(descriptor, Mapping):
                raise ValueError(
                    "descriptor for entity %r layer %r must be a mapping, "
                    "got %r" % (entity_id, layer_name, type(descriptor).__name__)
                )
            # Deep-ish copy so the caller's dict isn't aliased into the
            # view's state — protects against post-add mutation surprise.
            descriptors[layer_name] = dict(descriptor)
        self._entity_index[entity_id] = len(self._entities)
        self._entities.append((entity_id, descriptors))
        return self

    def add_relationship(
        self,
        from_id: str,
        to_id: str,
        kind: Optional[str] = None,
        **metadata: Any,
    ) -> "LayeredView":
        """Add a relationship between two entities.

        Surfaces in every layer where *both* endpoint entities have a
        descriptor — layers where one or both endpoints are missing
        skip the connector silently.

        :param from_id: the source entity's id (must already be
            declared via :meth:`add_entity`).
        :param to_id: the target entity's id.
        :param kind: optional verb describing the relationship
            (``"reads-writes"`` / ``"depends-on"`` / ``"hosts"``).
            Saved verbatim in the round-trip and rendered as the
            connector's text label.
        :param metadata: extra keyword arguments are stored verbatim
            and round-tripped — useful for downstream analysers
            (latency budget, encryption mode, …).

        :returns: ``self`` for fluent chaining.

        :raises ValueError: if either endpoint id is unknown.
        """
        if from_id not in self._entity_index:
            raise ValueError(
                "from_id %r is not a known entity in this view" % from_id
            )
        if to_id not in self._entity_index:
            raise ValueError(
                "to_id %r is not a known entity in this view" % to_id
            )
        rel: Dict[str, Any] = {
            "from": from_id,
            "to": to_id,
        }
        if kind is not None:
            rel["kind"] = str(kind)
        if metadata:
            rel["metadata"] = dict(metadata)
        self._relationships.append(rel)
        return self

    # -- rendering ------------------------------------------------------

    def show(self, layer_name: str) -> "LayeredViewRenderer":
        """Return a :class:`LayeredViewRenderer` for *layer_name*.

        :raises ValueError: when *layer_name* is not in :attr:`layers`.
        """
        if layer_name not in self._layers:
            raise ValueError(
                "layer %r is not configured on this view (layers: %r)"
                % (layer_name, self._layers)
            )
        return LayeredViewRenderer(self, layer_name)

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> "Dict[str, Any]":
        """Return a JSON-friendly dict capturing this view's state.

        Round-tripped verbatim by :meth:`from_dict`. The shape is::

            {
              "schema": "vsdx.layered-view/1",
              "name": "<optional>",
              "layers": [...],
              "entities": [
                {"id": "...", "descriptors": {<layer>: {...}, ...}},
                ...
              ],
              "relationships": [
                {"from": "...", "to": "...",
                 "kind": "...", "metadata": {...}},
                ...
              ]
            }
        """
        out: Dict[str, Any] = {
            "schema": LAYERED_VIEW_SCHEMA,
            "name": self._name,
            "layers": list(self._layers),
            "entities": [
                {"id": eid, "descriptors": dict(descriptors)}
                for eid, descriptors in self._entities
            ],
            "relationships": [dict(r) for r in self._relationships],
        }
        return out

    def to_json(self) -> str:
        """Return :meth:`to_dict` rendered as a UTF-8 JSON string.

        Output is sorted-key for stable round-trip diffs.
        """
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LayeredView":
        """Inverse of :meth:`to_dict`.

        :raises ValueError: when the payload's ``schema`` field doesn't
            match :data:`LAYERED_VIEW_SCHEMA`.
        """
        schema = data.get("schema")
        if schema != LAYERED_VIEW_SCHEMA:
            raise ValueError(
                "unrecognised LayeredView payload schema %r (expected %r)"
                % (schema, LAYERED_VIEW_SCHEMA)
            )
        layers = data.get("layers") or []
        view = cls(layers=list(layers), name=data.get("name"))
        for entity in data.get("entities") or []:
            eid = entity.get("id")
            descriptors = entity.get("descriptors") or {}
            if not isinstance(eid, str) or not eid:
                continue
            # Filter descriptors against the configured layers so a
            # corrupted payload can't smuggle in unknown layers via
            # round-trip.
            cleaned: Dict[str, Dict[str, Any]] = {}
            for layer, desc in descriptors.items():
                if layer in view._layers and isinstance(desc, Mapping):
                    cleaned[layer] = dict(desc)
            view._entity_index[eid] = len(view._entities)
            view._entities.append((eid, cleaned))
        for rel in data.get("relationships") or []:
            f = rel.get("from")
            t = rel.get("to")
            if f not in view._entity_index or t not in view._entity_index:
                continue
            new_rel: Dict[str, Any] = {"from": f, "to": t}
            if rel.get("kind") is not None:
                new_rel["kind"] = str(rel["kind"])
            md = rel.get("metadata")
            if isinstance(md, Mapping):
                new_rel["metadata"] = dict(md)
            view._relationships.append(new_rel)
        return view

    @classmethod
    def from_json(cls, payload: Union[str, bytes]) -> "LayeredView":
        """Parse JSON *payload* and reconstruct a :class:`LayeredView`."""
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return cls.from_dict(json.loads(payload))

    # -- repr -----------------------------------------------------------

    def __repr__(self) -> str:
        return (
            "LayeredView(name=%r, layers=%r, entities=%d, "
            "relationships=%d)"
            % (
                self._name,
                self._layers,
                len(self._entities),
                len(self._relationships),
            )
        )


class LayeredViewRenderer:
    """One-shot renderer for a single layer of a :class:`LayeredView`.

    Returned by :meth:`LayeredView.show`. Holds a reference to the
    parent view and the chosen layer name so :meth:`save_to_page` can
    project just that layer's entities and relationships.

    .. versionadded:: 0.3.0
    """

    def __init__(self, view: LayeredView, layer: str) -> None:
        self._view = view
        self._layer = layer

    @property
    def layer(self) -> str:
        """The layer name this renderer projects."""
        return self._layer

    @property
    def view(self) -> LayeredView:
        """The owning :class:`LayeredView`."""
        return self._view

    # -- iteration ------------------------------------------------------

    def visible_entities(self) -> "List[Tuple[str, Dict[str, Any]]]":
        """Return entities present in this layer, in declaration order.

        Each element is ``(entity_id, descriptor)``. Entities lacking
        a descriptor for the renderer's layer are filtered out.
        """
        out: List[Tuple[str, Dict[str, Any]]] = []
        for eid, descriptors in self._view._entities:
            if self._layer in descriptors:
                out.append((eid, dict(descriptors[self._layer])))
        return out

    def visible_relationships(self) -> "List[Dict[str, Any]]":
        """Return relationships whose endpoints both appear in this layer."""
        present_ids = {eid for eid, _ in self.visible_entities()}
        out: List[Dict[str, Any]] = []
        for rel in self._view._relationships:
            if rel["from"] in present_ids and rel["to"] in present_ids:
                out.append(dict(rel))
        return out

    # -- rendering ------------------------------------------------------

    def save_to_page(
        self,
        path: str,
        page_name: Optional[str] = None,
    ) -> str:
        """Render this layer to a fresh single-page ``.vsdx`` at *path*.

        A brand-new :class:`~vsdx.document.VisioDocument` is created
        (no relationship to the originating document is preserved) and
        a single page is added carrying:

        * one shape per visible entity, positioned automatically along
          a horizontal row (entity 0 leftmost, entity N-1 rightmost);
        * one connector per visible relationship, glued via the page's
          :meth:`~vsdx.page.Page.connect` helper.

        Each rendered shape carries its descriptor's ``name`` (or the
        entity-id when the descriptor omits one) as its visible label
        and the LayeredView config is persisted as a custom XML part
        on the produced document so :func:`load_layered_view` recovers
        the original builder.

        :returns: the resolved *path* (passed through verbatim — handy
            for chaining ``save_to_page("…").upload()`` style helpers).
        """
        # Local imports — vsdx.api / vsdx.page wrappers want to import
        # this module from their own __init__, so deferring keeps the
        # import graph acyclic.
        from vsdx.api import Visio

        doc = Visio()
        page_label = page_name or "%s — %s" % (
            self._view.name or "layered view",
            self._layer,
        )
        page = doc.pages.add_page(name=page_label)

        # Layout pass — collect entities, then place them in a simple
        # left-to-right row so the produced .vsdx renders sensibly when
        # opened in Visio without needing a separate layout engine.
        entities = self.visible_entities()
        positions: Dict[str, Any] = {}
        x = 1.0
        y_centre = float(page.height) / 2.0
        for eid, descriptor in entities:
            kind = str(descriptor.get("kind") or "")
            master = _master_for_kind(kind)
            w, h = _size_for_kind(kind)
            label = (
                str(descriptor.get("name"))
                if descriptor.get("name") is not None
                else eid
            )
            shape = page.shapes.add_shape(
                master,
                at=(x + w / 2.0, y_centre),
                size=(w, h),
                text=label,
            )
            positions[eid] = shape
            x += w + 0.6

        # Connectors — only fire when both endpoints landed on this
        # layer's render. ``visible_relationships`` already filters
        # against ``visible_entities`` so we just look the proxies up.
        for rel in self.visible_relationships():
            src = positions.get(rel["from"])
            dst = positions.get(rel["to"])
            if src is None or dst is None:
                continue
            connector = page.shapes.add_connector(src, dst)
            kind = rel.get("kind")
            if kind:
                try:
                    connector.text = str(kind)
                except Exception:  # noqa: BLE001 -- text is best-effort
                    pass

        # Persist the originating LayeredView configuration so a load
        # round-trip recovers it. The custom-xml-style part lives
        # alongside the document but is ignored by Microsoft Visio (it
        # opens application/xml parts opportunistically and silently
        # drops them on save when nothing relates to them).
        _persist_layered_view_part(doc, self._view, layer=self._layer)

        doc.save(path)
        return path


# ---------------------------------------------------------------------------
# Round-trip helpers
# ---------------------------------------------------------------------------


def _persist_layered_view_part(
    doc: "VisioDocument",
    view: LayeredView,
    layer: Optional[str] = None,
) -> None:
    """Attach *view*'s JSON config to *doc* as a custom XML part.

    Silently degrades if the supporting OPC primitives aren't
    available (older ``python-ooxml-opc`` releases) — the .vsdx still
    saves; only the round-trip is lost.
    """
    try:
        from ooxml_opc import Part
    except Exception:  # pragma: no cover - defensive
        return

    package = doc.package
    document_part = package.main_document_part

    # JSON payload, wrapped in a thin XML envelope so file-type
    # heuristics see <?xml…?> at the head and treat it as XML.
    json_payload = view.to_json()
    if layer is not None:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<layeredView '
            'xmlns="urn:loadfix:python-vsdx:layered-view:1" '
            'rendered-layer="%s">\n'
            '<![CDATA[%s]]>\n'
            "</layeredView>\n"
        ) % (_xml_escape_attr(layer), json_payload)
    else:
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<layeredView "
            'xmlns="urn:loadfix:python-vsdx:layered-view:1">\n'
            "<![CDATA[%s]]>\n"
            "</layeredView>\n"
        ) % json_payload

    partname = package.next_partname(LAYERED_VIEW_PARTNAME_TMPL)
    blob = envelope.encode("utf-8")
    # Use the bytes-only :class:`ooxml_opc.Part` base class — XmlPart
    # would lxml-canonicalise our JSON-bearing CDATA on emit and break
    # the round-trip. ``Part(blob=…)`` round-trips bytes verbatim.
    part = Part(
        partname=partname,
        content_type=LAYERED_VIEW_CONTENT_TYPE,
        package=package,
        blob=blob,
    )
    document_part.relate_to(
        part,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml",
    )


def _xml_escape_attr(value: str) -> str:
    """Minimal attribute escape for ``rendered-layer="…"``."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def load_layered_view(path: str) -> LayeredView:
    """Load a ``.vsdx`` written by :meth:`LayeredViewRenderer.save_to_page`
    and recover its :class:`LayeredView` config.

    Walks the document part's relationships looking for a custom-XML
    relationship whose target part carries a ``<layeredView>`` envelope
    (the format written by :meth:`LayeredViewRenderer.save_to_page`).
    The first matching part is parsed and returned.

    :raises ValueError: when the package carries no
        :class:`LayeredView` payload.
    """
    from vsdx.api import Visio

    doc = Visio(path)
    package = doc.package
    document_part = package.main_document_part
    target_reltype = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml"
    )
    for rel in document_part.rels.values():
        if rel.is_external:
            continue
        if rel.reltype != target_reltype:
            continue
        target_part = rel.target_part
        try:
            blob = target_part.blob
        except Exception:  # noqa: BLE001 -- malformed parts skipped
            continue
        view = _parse_layered_view_blob(blob)
        if view is not None:
            return view
    raise ValueError(
        "no LayeredView payload found in %r — was it saved via "
        "LayeredViewRenderer.save_to_page?" % path
    )


def _parse_layered_view_blob(blob: bytes) -> Optional[LayeredView]:
    """Recover a :class:`LayeredView` from a serialised envelope blob.

    Returns ``None`` if the blob isn't recognisably a LayeredView
    envelope — caller iterates over candidates and accepts the first
    successful parse.
    """
    if not blob:
        return None
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "layered-view" not in text:
        return None
    # Pull the JSON out of the CDATA section. We don't run an XML
    # parser here on purpose — the envelope is fixed-shape and the
    # blob is generated by us, so a regex is both simpler and avoids
    # XXE risk.
    start = text.find("<![CDATA[")
    if start == -1:
        return None
    start += len("<![CDATA[")
    end = text.find("]]>", start)
    if end == -1:
        return None
    json_text = text[start:end]
    try:
        return LayeredView.from_json(json_text)
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Page integration helpers
# ---------------------------------------------------------------------------


def _build_layered_view_for_page(
    page: "Page",
    layers: Iterable[str],
    name: Optional[str] = None,
) -> LayeredView:
    """Factory used by :meth:`Page.add_layered_view`.

    Kept as a free function so :class:`Page` doesn't need to carry the
    construction logic inline — and so the function can grow defaults
    (e.g. picking up the page name when *name* is ``None``) without
    enlarging :class:`Page`'s public surface.
    """
    if name is None:
        try:
            name = page.name
        except Exception:  # noqa: BLE001 -- best-effort default
            name = None
    view = LayeredView(layers=list(layers), page=page, name=name)
    return view
