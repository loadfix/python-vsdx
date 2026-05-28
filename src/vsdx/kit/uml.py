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
"""UML class diagram template kit — issue #131.

Build a UML class diagram from one of three sources::

    from vsdx.kit.uml import (
        uml_from_python_module,
        uml_from_json_schema,
        uml_from_typescript,
    )

    diagram = uml_from_python_module("myapp.models")
    diagram = uml_from_json_schema("schema.json")
    diagram = uml_from_typescript("models.ts")
    diagram.save("classes.vsdx")

Each class renders as a three-section UML rectangle (name |
attributes | methods). Inheritance edges emit a dynamic connector
tagged ``Relationship=inheritance``; composition edges (deduced from
typed attributes whose target class lives in the diagram) emit a
connector tagged ``Relationship=composition``. A downstream pass can
swap the connector's plain arrow for a hollow-triangle / filled
diamond glyph based on the metadata.

**Source coverage.**

* :func:`uml_from_python_module` introspects a real module via
  :mod:`importlib`. Attributes come from :mod:`dataclasses` fields
  (when present) and :func:`typing.get_type_hints` annotations;
  methods come from :func:`inspect.getmembers`. Inheritance follows
  ``cls.__bases__`` (skipping :class:`object` and out-of-scope
  parents). Composition is heuristically detected when an attribute's
  resolved type points at another class in the diagram.
* :func:`uml_from_json_schema` walks a JSON Schema document
  (``draft-07`` flavour). Each ``definitions`` / ``$defs`` entry plus
  the root (when ``title`` is set) becomes a class; ``properties``
  become attributes typed by ``"type"`` (or ``"$ref"`` -> referenced
  class). ``allOf`` ``$ref`` entries map to inheritance.
* :func:`uml_from_typescript` is a best-effort regex parser that
  recognises ``interface X { ... }``, ``class X extends Y
  implements Z { ... }``, ``type X = { ... }``, and the property /
  method shapes inside each block. Comments and string literals are
  scrubbed before parsing so braces inside them don't fool the
  block-matcher. Generic parameters are tolerated but stripped from
  the rendered name (``Box<T>`` -> ``Box``).

The kit is deliberately scoped to **simple cases** — it draws a
UML diagram, it does not type-check your code. Anything the parser
can't make sense of is silently skipped; partial output is preferred
over hard failure.

.. versionadded:: 0.4.0
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import re
import sys
import typing
from collections.abc import Mapping, Sequence
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

from vsdx.api import Visio
from vsdx.document import VisioDocument
from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.routing import ROUTING_RIGHT_ANGLE
from vsdx.shapes.base import Shape

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

#: A single attribute descriptor — ``(name, type)``. ``type`` may be
#: ``""`` when unknown.
AttributeSpec = Tuple[str, str]

#: A single method descriptor — ``(name, signature)``. ``signature``
#: includes parentheses + return-type annotation, e.g. ``"(self, x: int) -> str"``.
MethodSpec = Tuple[str, str]


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Connector label used on inheritance edges (child -> parent).
UML_RELATION_INHERITANCE: str = "inheritance"

#: Connector label used on composition edges (owner -> part).
UML_RELATION_COMPOSITION: str = "composition"

#: Connector label used on plain associations (owner -> reference).
UML_RELATION_ASSOCIATION: str = "association"

#: All recognised relationship tokens.
UML_RELATIONS: Tuple[str, ...] = (
    UML_RELATION_INHERITANCE,
    UML_RELATION_COMPOSITION,
    UML_RELATION_ASSOCIATION,
)


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

# A parsed-class record: name, attributes, methods, parents (by name),
# and the set of attribute target-class names that should become
# composition edges (filled in by the renderer once it knows which
# classes made the cut).
class _ClassSpec:
    __slots__ = ("name", "attributes", "methods", "parents", "compositions")

    def __init__(
        self,
        name: str,
        attributes: List[AttributeSpec],
        methods: List[MethodSpec],
        parents: List[str],
        compositions: List[str],
    ) -> None:
        self.name = name
        self.attributes = attributes
        self.methods = methods
        self.parents = parents
        self.compositions = compositions


# ---------------------------------------------------------------------------
# Layout constants — tuneable via build kwargs
# ---------------------------------------------------------------------------

_PAGE_MARGIN_X: float = 0.5
_PAGE_MARGIN_Y: float = 0.5

_TITLE_BAND_HEIGHT: float = 0.6

_BOX_WIDTH: float = 2.6
_BOX_HEADER_HEIGHT: float = 0.4
_BOX_ROW_HEIGHT: float = 0.25
_BOX_SECTION_PAD: float = 0.05
_BOX_MIN_HEIGHT: float = 0.9

_LAYOUT_SPACING: float = 2.6

_DEFAULT_PAGE_WIDTH: float = 14.0
_DEFAULT_PAGE_HEIGHT: float = 10.0

_LAYOUT_HIERARCHY: str = "hierarchy"
_LAYOUT_FORCE_DIRECTED: str = "force-directed"

_VALID_LAYOUTS: Set[Optional[str]] = {
    None,
    "hierarchy",
    "force-directed",
    "grid",
    "radial",
}


# ---------------------------------------------------------------------------
# Box-text rendering
# ---------------------------------------------------------------------------


def _box_text(spec: _ClassSpec) -> str:
    """Compose the three-section UML class-box label."""
    lines: List[str] = [spec.name, "-" * 16]
    if spec.attributes:
        for name, typ in spec.attributes:
            if typ:
                lines.append("+ %s: %s" % (name, typ))
            else:
                lines.append("+ %s" % name)
    else:
        lines.append(" ")
    lines.append("-" * 16)
    if spec.methods:
        for name, sig in spec.methods:
            lines.append("+ %s%s" % (name, sig))
    else:
        lines.append(" ")
    return "\n".join(lines)


def _box_height_for(spec: _ClassSpec) -> float:
    """Return the rectangle height (inches) for *spec*."""
    rows = max(1, len(spec.attributes)) + max(1, len(spec.methods))
    h = _BOX_HEADER_HEIGHT + _BOX_ROW_HEIGHT * rows + _BOX_SECTION_PAD * 2
    return max(_BOX_MIN_HEIGHT, h)


# ---------------------------------------------------------------------------
# Common builder — turns a list of _ClassSpec into a VisioDocument
# ---------------------------------------------------------------------------


def _build_diagram(
    classes: Sequence[_ClassSpec],
    *,
    title: str,
    page_width: float,
    page_height: float,
    page_name: Optional[str],
    routing: str,
    spacing: float,
    layout: Optional[str],
) -> VisioDocument:
    if not isinstance(title, str):
        raise TypeError("title must be a str (got %r)" % type(title).__name__)
    if layout not in _VALID_LAYOUTS:
        raise ValueError(
            "layout=%r must be one of %r"
            % (layout, sorted(k for k in _VALID_LAYOUTS if k is not None))
        )
    if not classes:
        raise ValueError("UML diagram requires at least one class")

    name_set = {c.name for c in classes}

    # Restrict edges to classes actually in the diagram. Drop self-loops.
    inheritance_edges: List[Tuple[str, str]] = []
    composition_edges: List[Tuple[str, str]] = []
    for spec in classes:
        for parent in spec.parents:
            if parent in name_set and parent != spec.name:
                inheritance_edges.append((spec.name, parent))
        for target in spec.compositions:
            if target in name_set and target != spec.name:
                composition_edges.append((spec.name, target))

    doc = Visio()
    name = page_name or title.strip() or "UML"
    page = doc.pages.add_page(
        name=name, width=page_width, height=page_height
    )

    inner_w = page_width - 2 * _PAGE_MARGIN_X
    if inner_w <= 0:
        raise ValueError(
            "page_width=%r leaves no inner width after the %r margin"
            % (page_width, _PAGE_MARGIN_X)
        )
    if title:
        title_pin_x = _PAGE_MARGIN_X + inner_w / 2
        title_pin_y = (
            page_height - _PAGE_MARGIN_Y - _TITLE_BAND_HEIGHT / 2
        )
        page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(title_pin_x, title_pin_y),
            size=(inner_w, _TITLE_BAND_HEIGHT),
            text=title,
        )

    # Drop one box per class in input order; auto-layout will move them.
    proxies: Dict[str, Shape] = {}
    drop_x = _PAGE_MARGIN_X + _BOX_WIDTH / 2
    cumulative_y = (
        page_height
        - _PAGE_MARGIN_Y
        - (_TITLE_BAND_HEIGHT if title else 0.0)
        - _BOX_MIN_HEIGHT / 2
    )
    for spec in classes:
        h = _box_height_for(spec)
        pin_y = cumulative_y - h / 2
        cumulative_y -= h + 0.2
        box = page.shapes.add_shape(
            VS_SHAPE_TYPE.RECTANGLE,
            at=(drop_x, pin_y),
            size=(_BOX_WIDTH, h),
            text=_box_text(spec),
        )
        box.data.add_field("ClassName", spec.name, label="Class")
        proxies[spec.name] = box

    # Inheritance connectors — child -> parent.
    for child, parent in inheritance_edges:
        conn = page.add_connector(
            proxies[child], proxies[parent], routing=routing
        )
        conn.data.add_field(
            "Relationship",
            UML_RELATION_INHERITANCE,
            label="Relationship",
        )
        conn.data.add_field("Source", child, label="Source")
        conn.data.add_field("Target", parent, label="Target")

    # Composition connectors — owner -> part.
    for owner, part in composition_edges:
        conn = page.add_connector(
            proxies[owner], proxies[part], routing=routing
        )
        conn.data.add_field(
            "Relationship",
            UML_RELATION_COMPOSITION,
            label="Relationship",
        )
        conn.data.add_field("Source", owner, label="Source")
        conn.data.add_field("Target", part, label="Target")

    has_edges = bool(inheritance_edges or composition_edges)
    chosen_layout = layout
    if chosen_layout is None:
        chosen_layout = (
            _LAYOUT_HIERARCHY if has_edges else _LAYOUT_FORCE_DIRECTED
        )

    origin_x = _PAGE_MARGIN_X + _BOX_WIDTH / 2
    origin_y = (
        page_height
        - _PAGE_MARGIN_Y
        - (_TITLE_BAND_HEIGHT if title else 0.0)
        - _BOX_MIN_HEIGHT / 2
    )
    if chosen_layout == _LAYOUT_HIERARCHY:
        page.layout(
            "hierarchy",
            direction="top-to-bottom",
            spacing=spacing,
            origin=(origin_x, origin_y),
        )
        # Visio Y grows up; flip around the origin so children sit
        # below their parents in the rendered diagram (mirrors the
        # vsdx.kit.org_chart trick).
        for box in proxies.values():
            box.pin_y = 2 * origin_y - float(box.pin_y)
    else:
        page.layout(
            chosen_layout,
            spacing=spacing,
            origin=(origin_x, origin_y),
        )

    return doc


# ---------------------------------------------------------------------------
# Python-module introspection
# ---------------------------------------------------------------------------


def _resolve_python_module(module_name_or_path: str) -> Any:
    """Import *module_name_or_path*, supporting dotted-name and file-path inputs."""
    if isinstance(module_name_or_path, os.PathLike):
        module_name_or_path = os.fspath(module_name_or_path)
    if not isinstance(module_name_or_path, str) or not module_name_or_path.strip():
        raise TypeError(
            "module_name_or_path must be a non-empty str (got %r)"
            % type(module_name_or_path).__name__
        )

    candidate = module_name_or_path.strip()
    # File path?  Load via importlib's spec-from-file-location.
    if candidate.endswith(".py") and os.path.isfile(candidate):
        module_name = os.path.splitext(os.path.basename(candidate))[0]
        spec = importlib.util.spec_from_file_location(module_name, candidate)
        if spec is None or spec.loader is None:  # pragma: no cover — defensive
            raise ImportError(
                "could not build an import spec for %r" % candidate
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(candidate)


def _format_annotation(ann: Any) -> str:
    """Render *ann* as a short human-readable string."""
    if ann is inspect.Parameter.empty or ann is inspect.Signature.empty:
        return ""
    if isinstance(ann, type):
        return ann.__name__
    text = repr(ann)
    # ``typing.Optional[X]`` etc. come back as ``typing.Optional[X]`` —
    # strip the leading module prefix for readability.
    if text.startswith("typing."):
        text = text[len("typing."):]
    return text


def _annotation_target_classes(ann: Any) -> List[str]:
    """Return the class names referenced by *ann*, recursively."""
    found: List[str] = []
    if ann is inspect.Parameter.empty or ann is None:
        return found
    if isinstance(ann, type):
        found.append(ann.__name__)
        return found
    args = typing.get_args(ann)
    for sub in args:
        found.extend(_annotation_target_classes(sub))
    return found


def _is_classlike(obj: Any) -> bool:
    return inspect.isclass(obj)


def _python_class_spec(
    cls: type,
    *,
    in_scope: Set[str],
    skip_dunders: bool,
) -> _ClassSpec:
    """Build a :class:`_ClassSpec` from a real Python class object."""
    # Attribute hints first — best when ``get_type_hints`` resolves
    # forward references.  Falls back to ``__annotations__`` raw when
    # a name fails to resolve (PEP 563 / circular imports).
    raw_hints: Dict[str, Any] = {}
    try:
        raw_hints = dict(typing.get_type_hints(cls))
    except Exception:
        raw_hints = dict(getattr(cls, "__annotations__", {}) or {})

    # ``dataclasses.fields`` gives us the declared order which matches
    # the source; ``__annotations__`` mostly does too on modern Python.
    field_names: List[str] = []
    try:
        import dataclasses

        if dataclasses.is_dataclass(cls):
            field_names = [f.name for f in dataclasses.fields(cls)]
    except Exception:  # pragma: no cover — dataclasses always importable
        pass
    if not field_names:
        field_names = list(getattr(cls, "__annotations__", {}) or {})

    attributes: List[AttributeSpec] = []
    composition_targets: List[str] = []
    for fname in field_names:
        if fname.startswith("_") and skip_dunders:
            continue
        ann = raw_hints.get(fname, getattr(cls, "__annotations__", {}).get(fname))
        attributes.append((fname, _format_annotation(ann)))
        composition_targets.extend(_annotation_target_classes(ann))

    methods: List[MethodSpec] = []
    seen: Set[str] = set()
    for mname, member in inspect.getmembers(cls):
        if mname in seen:
            continue
        if mname.startswith("__") and mname.endswith("__"):
            if skip_dunders and mname not in {"__init__", "__call__"}:
                continue
        # Only count callables defined on the class itself.
        if not (
            inspect.isfunction(member)
            or inspect.ismethod(member)
            or isinstance(member, (staticmethod, classmethod))
        ):
            continue
        owner = getattr(member, "__qualname__", "").split(".")
        if len(owner) >= 2 and owner[-2] != cls.__name__:
            # Inherited from a base class — skip; the parent class
            # carries it.
            continue
        try:
            sig = inspect.signature(
                member.__func__ if isinstance(member, (staticmethod, classmethod))
                else member
            )
            sig_text = str(sig)
        except (TypeError, ValueError):
            sig_text = "(...)"
        methods.append((mname, sig_text))
        seen.add(mname)

    parents = [
        b.__name__
        for b in getattr(cls, "__bases__", ())
        if b is not object
    ]

    # Restrict composition targets to the in-scope classes (the
    # renderer also filters, but trimming here keeps the spec lean).
    compositions = [t for t in composition_targets if t in in_scope and t != cls.__name__]
    return _ClassSpec(
        name=cls.__name__,
        attributes=attributes,
        methods=methods,
        parents=parents,
        compositions=compositions,
    )


def uml_from_python_module(
    module_name_or_path: Union[str, os.PathLike[str]],
    *,
    include_private: bool = False,
    only: Optional[Sequence[str]] = None,
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
    layout: Optional[str] = None,
) -> VisioDocument:
    """Author a UML class diagram by introspecting a Python module.

    *module_name_or_path* is either a dotted import path
    (``"myapp.models"``) or a filesystem path to a ``.py`` file.

    Each top-level class declared in the module becomes a UML box
    (filtered to classes whose ``__module__`` matches the import
    target so re-exports don't double-up). When *only* is given,
    only the named classes are rendered. *include_private* keeps
    underscore-prefixed attributes / methods in the output.

    .. versionadded:: 0.4.0
    """
    module = _resolve_python_module(os.fspath(module_name_or_path)
                                     if isinstance(module_name_or_path, os.PathLike)
                                     else module_name_or_path)
    module_name = module.__name__

    keep_names: Optional[Set[str]] = None
    if only is not None:
        keep_names = {str(n) for n in only}

    candidates: List[type] = []
    for _, obj in inspect.getmembers(module, _is_classlike):
        if getattr(obj, "__module__", None) != module_name:
            continue
        if keep_names is not None and obj.__name__ not in keep_names:
            continue
        candidates.append(obj)

    if not candidates:
        raise ValueError(
            "module %r exposes no introspectable classes" % module_name
        )

    in_scope = {c.__name__ for c in candidates}
    classes = [
        _python_class_spec(c, in_scope=in_scope, skip_dunders=not include_private)
        for c in candidates
    ]
    return _build_diagram(
        classes,
        title=title,
        page_width=page_width,
        page_height=page_height,
        page_name=page_name,
        routing=routing,
        spacing=spacing,
        layout=layout,
    )


# ---------------------------------------------------------------------------
# JSON Schema parsing
# ---------------------------------------------------------------------------


_JSON_PRIMITIVES = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "null": "None",
}


def _json_type_label(prop: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """Return ``(display_type, ref_target)`` for a JSON Schema property."""
    if not isinstance(prop, Mapping):
        return ("", None)
    if "$ref" in prop:
        target = _json_ref_name(prop["$ref"])
        return (target or "object", target)
    typ = prop.get("type")
    if typ == "array":
        items = prop.get("items")
        if isinstance(items, Mapping):
            inner, target = _json_type_label(items)
            return ("List[%s]" % (inner or "any"), target)
        return ("List[any]", None)
    if isinstance(typ, list):
        labels = [
            _JSON_PRIMITIVES.get(t, t) for t in typ if isinstance(t, str)
        ]
        return ("Union[%s]" % ", ".join(labels), None) if labels else ("", None)
    if isinstance(typ, str):
        return (_JSON_PRIMITIVES.get(typ, typ), None)
    return ("", None)


def _json_ref_name(ref: Any) -> Optional[str]:
    """Return the trailing component of a JSON Schema ``$ref``."""
    if not isinstance(ref, str):
        return None
    if "/" in ref:
        return ref.rsplit("/", 1)[-1]
    return ref


def _json_class_specs(
    schema: Mapping[str, Any],
) -> List[_ClassSpec]:
    """Walk *schema* and return one :class:`_ClassSpec` per definition."""
    classes: List[_ClassSpec] = []
    seen: Set[str] = set()

    def add_class(name: str, body: Mapping[str, Any]) -> None:
        if name in seen:
            return
        seen.add(name)
        attrs: List[AttributeSpec] = []
        compositions: List[str] = []
        props = body.get("properties") if isinstance(body, Mapping) else None
        if isinstance(props, Mapping):
            for pname, pdef in props.items():
                if not isinstance(pname, str):
                    continue
                label, target = _json_type_label(pdef)
                attrs.append((pname, label))
                if target:
                    compositions.append(target)
        parents: List[str] = []
        all_of = body.get("allOf") if isinstance(body, Mapping) else None
        if isinstance(all_of, list):
            for item in all_of:
                if isinstance(item, Mapping) and "$ref" in item:
                    tgt = _json_ref_name(item["$ref"])
                    if tgt:
                        parents.append(tgt)
                elif isinstance(item, Mapping) and "properties" in item:
                    sub_props = item.get("properties")
                    if isinstance(sub_props, Mapping):
                        for pname, pdef in sub_props.items():
                            if not isinstance(pname, str):
                                continue
                            label, target = _json_type_label(pdef)
                            attrs.append((pname, label))
                            if target:
                                compositions.append(target)
        classes.append(
            _ClassSpec(
                name=name,
                attributes=attrs,
                methods=[],
                parents=parents,
                compositions=compositions,
            )
        )

    # Definitions first — both draft-04 ``definitions`` and draft-2019
    # ``$defs`` containers are recognised.
    for key in ("definitions", "$defs"):
        defs = schema.get(key)
        if isinstance(defs, Mapping):
            for dname, dbody in defs.items():
                if isinstance(dname, str) and isinstance(dbody, Mapping):
                    add_class(dname, dbody)

    # Root schema as its own class when ``title`` is set.
    root_title = schema.get("title")
    if isinstance(root_title, str) and root_title.strip():
        add_class(root_title.strip(), schema)

    return classes


def uml_from_json_schema(
    path_or_dict: Union[str, os.PathLike[str], Mapping[str, Any]],
    *,
    encoding: str = "utf-8",
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
    layout: Optional[str] = None,
) -> VisioDocument:
    """Author a UML class diagram from a JSON Schema document.

    *path_or_dict* is read from disk when it is an :class:`os.PathLike`
    or a ``str`` pointing at an existing file; raw ``str`` JSON is
    parsed inline; a :class:`Mapping` is consumed verbatim.

    .. versionadded:: 0.4.0
    """
    if isinstance(path_or_dict, Mapping):
        schema: Mapping[str, Any] = path_or_dict
    elif isinstance(path_or_dict, os.PathLike):
        with open(path_or_dict, encoding=encoding) as fh:
            schema = json.load(fh)
    elif isinstance(path_or_dict, str):
        if os.path.isfile(path_or_dict) and "\n" not in path_or_dict:
            with open(path_or_dict, encoding=encoding) as fh:
                schema = json.load(fh)
        else:
            schema = json.loads(path_or_dict)
    else:
        raise TypeError(
            "path_or_dict must be a str, os.PathLike, or Mapping (got %r)"
            % type(path_or_dict).__name__
        )

    if not isinstance(schema, Mapping):
        raise ValueError(
            "JSON Schema root must be a JSON object (got %r)"
            % type(schema).__name__
        )

    classes = _json_class_specs(schema)
    if not classes:
        raise ValueError(
            "JSON Schema contains no definitions / $defs / titled root"
        )

    return _build_diagram(
        classes,
        title=title,
        page_width=page_width,
        page_height=page_height,
        page_name=page_name,
        routing=routing,
        spacing=spacing,
        layout=layout,
    )


# ---------------------------------------------------------------------------
# TypeScript regex parser
# ---------------------------------------------------------------------------


_TS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_TS_LINE_COMMENT_RE = re.compile(r"//[^\n]*", re.MULTILINE)
_TS_STRING_RE = re.compile(r"(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)")


def _ts_strip_noise(source: str) -> str:
    """Remove comments / string literals so braces / colons can't fool us."""
    source = _TS_BLOCK_COMMENT_RE.sub(" ", source)
    source = _TS_LINE_COMMENT_RE.sub(" ", source)
    # Replace string contents with empty placeholders preserving quotes.
    source = _TS_STRING_RE.sub('""', source)
    return source


def _ts_match_block(source: str, open_idx: int) -> int:
    """Return the index of the matching ``}`` for the ``{`` at *open_idx*."""
    depth = 0
    i = open_idx
    while i < len(source):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_TS_HEADER_RE = re.compile(
    r"""(?:export\s+)?
        (?:default\s+)?
        (?:abstract\s+)?
        (?P<kind>interface|class|type)\s+
        (?P<name>[A-Za-z_$][\w$]*)
        (?:\s*<[^>]+>)?                  # generic params, dropped
        (?P<extends>\s+extends\s+[^\{\n]+)?
        (?P<implements>\s+implements\s+[^\{\n]+)?
        \s*(?P<assign>=)?                # `type X = { ... }` form
        \s*\{
    """,
    re.VERBOSE,
)


def _ts_parent_names(blob: Optional[str]) -> List[str]:
    """Return the comma-separated parent identifiers in *blob*."""
    if not blob:
        return []
    body = blob.split(None, 1)[1] if " " in blob.strip() else blob
    body = body.replace("extends", "").replace("implements", "")
    parents: List[str] = []
    for piece in body.split(","):
        piece = piece.strip().rstrip(",")
        if not piece:
            continue
        # Drop generic args from each parent (Foo<Bar, Baz> -> Foo).
        bare = re.match(r"[A-Za-z_$][\w$.]*", piece)
        if bare:
            ident = bare.group(0).rsplit(".", 1)[-1]
            if ident:
                parents.append(ident)
    return parents


_TS_MEMBER_LINE_RE = re.compile(
    r"""^\s*
        (?:(?P<vis>public|private|protected|readonly|static|abstract|async)\s+)*
        (?P<name>[A-Za-z_$][\w$]*)
        (?P<generic>\s*<[^>]*>)?
        (?:(?P<paren>\()(?P<args>.*?)\)\s*(?::\s*(?P<rtype>[^;{=]+))?)?
        (?:(?P<colon>:\s*)(?P<atype>[^;={\n]+))?
        \s*[;,]?\s*$
    """,
    re.VERBOSE,
)

_TS_TARGET_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
_TS_PRIMITIVE_TYPES = {
    "string", "number", "boolean", "any", "void", "null", "undefined",
    "object", "never", "unknown", "bigint", "symbol", "Date", "Array",
    "Map", "Set", "Promise", "Record", "Partial", "Readonly", "Pick",
    "Omit", "Required", "ReadonlyArray", "this",
}


def _ts_collect_targets(type_text: str) -> List[str]:
    """Yank the candidate user-class identifiers out of a TS type expression."""
    targets: List[str] = []
    for m in _TS_TARGET_IDENT_RE.finditer(type_text or ""):
        ident = m.group(0)
        if ident in _TS_PRIMITIVE_TYPES:
            continue
        if ident[0].isupper():
            targets.append(ident)
    return targets


def _ts_parse_block(body: str) -> Tuple[List[AttributeSpec], List[MethodSpec], List[str]]:
    """Parse the inside of a TS class/interface body."""
    attributes: List[AttributeSpec] = []
    methods: List[MethodSpec] = []
    composition: List[str] = []

    # Split on semicolons / newlines while respecting nested braces /
    # angle brackets.
    pieces: List[str] = []
    depth_brace = 0
    depth_angle = 0
    depth_paren = 0
    current: List[str] = []
    for ch in body:
        if ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace = max(0, depth_brace - 1)
        elif ch == "<":
            depth_angle += 1
        elif ch == ">":
            depth_angle = max(0, depth_angle - 1)
        elif ch == "(":
            depth_paren += 1
        elif ch == ")":
            depth_paren = max(0, depth_paren - 1)
        elif (
            ch in (";", "\n")
            and depth_brace == 0
            and depth_angle == 0
            and depth_paren == 0
        ):
            text = "".join(current).strip()
            if text:
                pieces.append(text)
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        pieces.append(tail)

    for piece in pieces:
        # Compress whitespace so the regex behaves predictably across lines.
        piece = " ".join(piece.split())
        m = _TS_MEMBER_LINE_RE.match(piece + ";")
        if m is None:
            continue
        name = m.group("name")
        if not name or name in {"constructor"}:
            continue
        if m.group("paren"):
            args = (m.group("args") or "").strip()
            rtype = (m.group("rtype") or "").strip().rstrip(";").rstrip(",")
            sig = "(%s)" % args
            if rtype:
                sig += " -> %s" % rtype
            methods.append((name, sig))
            composition.extend(_ts_collect_targets(rtype))
            composition.extend(_ts_collect_targets(args))
        else:
            atype = (m.group("atype") or "").strip().rstrip(";").rstrip(",")
            attributes.append((name, atype))
            composition.extend(_ts_collect_targets(atype))
    return attributes, methods, composition


def _ts_parse_source(source: str) -> List[_ClassSpec]:
    cleaned = _ts_strip_noise(source)
    classes: List[_ClassSpec] = []
    seen: Set[str] = set()
    pos = 0
    while True:
        m = _TS_HEADER_RE.search(cleaned, pos)
        if m is None:
            break
        open_idx = m.end() - 1  # the ``{`` is the final char of the match
        close_idx = _ts_match_block(cleaned, open_idx)
        if close_idx == -1:
            break
        name = m.group("name")
        if name and name not in seen:
            seen.add(name)
            body = cleaned[open_idx + 1 : close_idx]
            attrs, methods, composition = _ts_parse_block(body)
            parents: List[str] = []
            parents.extend(_ts_parent_names(m.group("extends")))
            parents.extend(_ts_parent_names(m.group("implements")))
            classes.append(
                _ClassSpec(
                    name=name,
                    attributes=attrs,
                    methods=methods,
                    parents=parents,
                    compositions=composition,
                )
            )
        pos = close_idx + 1
    return classes


def _looks_like_ts_path(text: str) -> bool:
    if "\n" in text:
        return False
    if "{" in text or ";" in text:
        return False
    return os.path.isfile(text)


def uml_from_typescript(
    path_or_string: Union[str, os.PathLike[str]],
    *,
    encoding: str = "utf-8",
    title: str = "",
    page_width: float = _DEFAULT_PAGE_WIDTH,
    page_height: float = _DEFAULT_PAGE_HEIGHT,
    page_name: Optional[str] = None,
    routing: str = ROUTING_RIGHT_ANGLE,
    spacing: float = _LAYOUT_SPACING,
    layout: Optional[str] = None,
) -> VisioDocument:
    """Author a UML class diagram from a TypeScript file or source string.

    The parser is **best-effort regex** — it recognises ``interface
    X { ... }``, ``class X extends Y implements Z { ... }``, and
    ``type X = { ... }`` block forms; anything else is skipped.

    .. versionadded:: 0.4.0
    """
    if isinstance(path_or_string, os.PathLike):
        with open(path_or_string, encoding=encoding) as fh:
            source = fh.read()
    elif isinstance(path_or_string, str):
        if _looks_like_ts_path(path_or_string):
            with open(path_or_string, encoding=encoding) as fh:
                source = fh.read()
        else:
            source = path_or_string
    else:
        raise TypeError(
            "path_or_string must be a str or os.PathLike (got %r)"
            % type(path_or_string).__name__
        )

    classes = _ts_parse_source(source)
    if not classes:
        raise ValueError(
            "TypeScript source contains no parseable class / interface / "
            "type declarations"
        )

    return _build_diagram(
        classes,
        title=title,
        page_width=page_width,
        page_height=page_height,
        page_name=page_name,
        routing=routing,
        spacing=spacing,
        layout=layout,
    )


__all__ = [
    "AttributeSpec",
    "MethodSpec",
    "UML_RELATIONS",
    "UML_RELATION_ASSOCIATION",
    "UML_RELATION_COMPOSITION",
    "UML_RELATION_INHERITANCE",
    "uml_from_json_schema",
    "uml_from_python_module",
    "uml_from_typescript",
]
