# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false
# pyright: reportAttributeAccessIssue=false
"""Visio-specific ``ST_*`` simple types.

Ported from Microsoft Learn's `Visio Types reference
<https://learn.microsoft.com/en-us/office/client-developer/visio/typesvisio-xml>`_
and cross-checked against ``dave-howard/vsdx`` for real-world Visio
output. Base classes come from the shared
``python-ooxml-xmlchemy.simpletypes`` vocabulary.

Design notes:

- ``ST_FormulaString`` is the Visio formula expression grammar
  (ShapeSheet). **Authoring never evaluates** the expression — we
  store it as an opaque XML-safe string and let Visio desktop
  recompute ``Cell/@V`` at open time. Validation therefore rejects
  only patently-broken inputs (nested quoting, NUL bytes).
- ``ST_PageIndex`` / ``ST_ShapeIndex`` / ``ST_BaseID`` /
  ``ST_UniqueID`` are ID-like integers / GUIDs in cell attributes.
- ``ST_Boolean`` matches Visio's "0/1 on wire" convention (no
  ``true``/``false`` spellings inside cell attribute text).

.. versionadded:: 0.1.0
"""

from __future__ import annotations

import re

from ooxml_xmlchemy import (
    BaseIntType,
    BaseSimpleType,
    BaseStringEnumerationType,
    BaseStringType,
    XsdString,
    XsdStringEnumeration,
    XsdUnsignedInt,
)

__all__ = [
    "ST_BaseID",
    "ST_Boolean",
    "ST_FormulaString",
    "ST_LayerMember",
    "ST_LineStyle",
    "ST_PageIndex",
    "ST_RouteStyle",
    "ST_RowType",
    "ST_SectionName",
    "ST_ShapeIndex",
    "ST_ShapeType",
    "ST_UniqueID",
    "ST_UnitString",
    "ST_WindowType",
]


# -- GUID pattern, shared by BaseID / UniqueID ------------------------------

# Visio writes GUIDs with surrounding braces, e.g.
# ``{91A5A9A0-1234-5678-ABCD-1234567890AB}``. Anchor the regex to avoid
# runtime-unbounded matching on attacker input.
_GUID_RE = re.compile(
    r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$"
)


# -- numeric simple types ---------------------------------------------------


class ST_PageIndex(XsdUnsignedInt):
    """``Page/@ID`` — unsigned int identifying a page in the index.

    Visio assigns sequentially-incrementing IDs starting at 0.

    .. versionadded:: 0.1.0
    """


class ST_ShapeIndex(XsdUnsignedInt):
    """``Shape/@ID`` — unsigned int identifying a shape on its page.

    IDs are page-scoped; they collide across pages by design (a Visio
    page always carries its own shape-ID space).

    .. versionadded:: 0.1.0
    """


class ST_Boolean(BaseIntType):
    """Visio's ``0``/``1`` boolean convention as used inside cell attrs.

    Real Visio output never spells out ``true`` / ``false`` in cell
    attribute text — it's always the numeric literal.

    .. versionadded:: 0.1.0
    """

    @classmethod
    def convert_from_xml(cls, str_value: str) -> bool:  # type: ignore[override]
        if str_value in ("0", "false", "False"):
            return False
        if str_value in ("1", "true", "True"):
            return True
        raise ValueError(
            "expected Visio boolean 0/1, got %r" % str_value
        )

    @classmethod
    def convert_to_xml(cls, value: bool) -> str:  # type: ignore[override]
        return "1" if value else "0"

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        if not isinstance(value, bool):
            raise TypeError(
                "value must be bool, got %s" % type(value).__name__
            )


# -- enumeration simple types -----------------------------------------------


class ST_ShapeType(XsdStringEnumeration):
    """``Shape/@Type`` — one of the five Visio shape kinds.

    Per MS Learn's ``ShapeType_Type`` page — values come from the
    controlled vocabulary ``Shape`` / ``Group`` / ``Foreign`` /
    ``Guide`` / ``Page``.

    .. versionadded:: 0.1.0
    """

    SHAPE = "Shape"
    GROUP = "Group"
    FOREIGN = "Foreign"
    GUIDE = "Guide"
    PAGE = "Page"

    _members = (SHAPE, GROUP, FOREIGN, GUIDE, PAGE)


class ST_LineStyle(XsdStringEnumeration):
    """``Cell[@N='LineStyle']/@V`` — named line style.

    Values come from the Visio built-in style vocabulary. This list
    covers the five defaults MS Learn documents; user stylesheets may
    extend it and values outside this set are stored as opaque
    strings (see ``ST_OpenEnumeration`` pattern in other loadfix
    packages; for 0.1.0 we enforce just the documented set and
    widen later if corpus fixtures show otherwise).

    .. versionadded:: 0.1.0
    """

    NORMAL = "Normal"
    NONE = "None"
    VISIO_10 = "Visio 10"
    VISIO_20 = "Visio 20"
    VISIO_40 = "Visio 40"

    _members = (NORMAL, NONE, VISIO_10, VISIO_20, VISIO_40)


class ST_RouteStyle(BaseIntType):
    """``Cell[@N='RouteStyle']/@V`` — connector routing style.

    Integer enumeration. Values 0..16 per MS Learn's RouteStyle_Type
    page; we don't restrict the range because Visio tolerates
    out-of-range values on read (it clamps at apply-time).

    .. versionadded:: 0.1.0
    """

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        cls.validate_int(value)
        if value < 0 or value > 255:
            raise ValueError(
                "RouteStyle must be 0..255, got %d" % value
            )


class ST_RowType(XsdStringEnumeration):
    """``Row/@T`` — geometry-row type discriminator.

    Used when the enclosing ``<Section>`` is Geometry — ``@T`` names
    the row kind (``MoveTo`` / ``LineTo`` / ``ArcTo`` / ``EllipticalArcTo``
    / ``InfiniteLine`` / ``Ellipse`` / ``SplineStart`` / ``SplineKnot`` /
    ``PolylineTo`` / ``NURBSTo`` / ``RelMoveTo`` / ``RelLineTo`` /
    ``RelQuadBezTo`` / ``RelCubBezTo`` / ``PrivateFeature``). For
    non-geometry sections the ``@T`` attribute is omitted and rows
    use ``@IX`` (index-based) or ``@N`` (name-based) discrimination.

    .. versionadded:: 0.1.0
    """

    MOVE_TO = "MoveTo"
    LINE_TO = "LineTo"
    ARC_TO = "ArcTo"
    ELLIPTICAL_ARC_TO = "EllipticalArcTo"
    INFINITE_LINE = "InfiniteLine"
    ELLIPSE = "Ellipse"
    SPLINE_START = "SplineStart"
    SPLINE_KNOT = "SplineKnot"
    POLYLINE_TO = "PolylineTo"
    NURBS_TO = "NURBSTo"
    REL_MOVE_TO = "RelMoveTo"
    REL_LINE_TO = "RelLineTo"
    REL_QUAD_BEZ_TO = "RelQuadBezTo"
    REL_CUB_BEZ_TO = "RelCubBezTo"

    _members = (
        MOVE_TO,
        LINE_TO,
        ARC_TO,
        ELLIPTICAL_ARC_TO,
        INFINITE_LINE,
        ELLIPSE,
        SPLINE_START,
        SPLINE_KNOT,
        POLYLINE_TO,
        NURBS_TO,
        REL_MOVE_TO,
        REL_LINE_TO,
        REL_QUAD_BEZ_TO,
        REL_CUB_BEZ_TO,
    )


class ST_SectionName(XsdStringEnumeration):
    """``Section/@N`` — named section kind.

    MS Learn documents 14 section names in ``SectionName_Type``. The
    vocabulary is extensible (Visio allows user-defined section names
    in practice), but 0.1.0 constrains it to the documented set; we
    relax if fixtures surface out-of-vocabulary names.

    .. versionadded:: 0.1.0
    """

    ACTIONS = "Actions"
    ANNOTATION = "Annotation"
    CHARACTER = "Character"
    CONNECTION = "Connection"
    CONNECTION_ABCD = "ConnectionABCD"
    CONTROLS = "Controls"
    FIELD = "Field"
    GEOMETRY = "Geometry"
    HYPERLINK = "Hyperlink"
    LAYER = "Layer"
    PARAGRAPH = "Paragraph"
    PROPERTY = "Property"
    REVIEWER = "Reviewer"
    SCRATCH = "Scratch"
    TABS = "Tabs"
    USER = "User"

    _members = (
        ACTIONS,
        ANNOTATION,
        CHARACTER,
        CONNECTION,
        CONNECTION_ABCD,
        CONTROLS,
        FIELD,
        GEOMETRY,
        HYPERLINK,
        LAYER,
        PARAGRAPH,
        PROPERTY,
        REVIEWER,
        SCRATCH,
        TABS,
        USER,
    )


class ST_UnitString(BaseStringType):
    """``Cell/@U`` — display-unit hint.

    Opaque string from the Visio unit table (``IN``, ``MM``, ``CM``,
    ``PT``, ``PC``, ``FT``, ``YD``, ``MI``, ``DEG``, ``RAD``, and
    composite units like ``DM`` / ``MGM`` / ``MGP``). We don't enforce
    membership because Visio carries user-defined units for custom
    stencils.

    .. versionadded:: 0.1.0
    """

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        cls.validate_string(value)
        # Unit strings are short and alphanumeric; reject payloads
        # that would look like injection attempts.
        if "\x00" in value or len(value) > 32:
            raise ValueError(
                "unit string must be short and NUL-free"
            )


class ST_WindowType(XsdStringEnumeration):
    """``Window/@WindowType`` — Visio window kind.

    .. versionadded:: 0.1.0
    """

    DRAWING = "Drawing"
    STENCIL = "Stencil"
    SHEET = "Sheet"
    ICON = "Icon"

    _members = (DRAWING, STENCIL, SHEET, ICON)


# -- opaque-string simple types ---------------------------------------------


class ST_FormulaString(BaseStringType):
    """``Cell/@F`` — ShapeSheet formula expression.

    Treated as an opaque string at the oxml layer. No evaluation.
    Validation rejects NUL bytes and pathologically-long payloads.

    The canonical examples from real Visio output: ``"Width*0"``,
    ``"(BeginX+EndX)/2"``, ``"ATAN2(EndY-BeginY,EndX-BeginX)"``,
    ``"Sheet.2!Width*0.5"`` (cross-shape reference).

    A leading ``=`` is **not** part of the serialised value — MS Visio
    emits bare expressions. The proxy layer (out of oxml-track scope)
    may accept a leading ``=`` and strip it.

    .. versionadded:: 0.1.0
    """

    _MAX_LEN = 16 * 1024  # 16 KiB cap — cover pathological cases

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        cls.validate_string(value)
        if "\x00" in value:
            raise ValueError("formula string contains NUL byte")
        if len(value) > cls._MAX_LEN:
            raise ValueError(
                "formula string exceeds %d-byte cap" % cls._MAX_LEN
            )


class ST_BaseID(BaseStringType):
    """``Master/@BaseID`` — curly-braced GUID identifying a master by base.

    Example: ``{91A5A9A0-1234-5678-ABCD-1234567890AB}``. Two masters
    in two different documents that share a BaseID represent copies
    of the same underlying Visio master.

    .. versionadded:: 0.1.0
    """

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        cls.validate_string(value)
        if not _GUID_RE.match(value):
            raise ValueError(
                "BaseID must be a curly-braced GUID, got %r" % value
            )


class ST_LayerMember(BaseStringType):
    """``Cell[@N='LayerMember']/@V`` — comma-separated non-negative ints.

    Gives the zero-based indices of the ``<Layer>`` rows (in the owning
    page's ``<Section N="Layer">``) that a shape belongs to. Real Visio
    output emits ``"0"``, ``"0,2"``, ``"0,2,5"`` etc. — strictly
    non-negative integers joined by a literal comma, no whitespace.

    We never normalise (sort / dedup) on read-modify-write: the
    round-trip invariant is byte-identical preservation of the source
    ordering (§2.5 of the 0.2.0 scoping doc).

    .. versionadded:: 0.2.0
    """

    _LAYER_MEMBER_RE = re.compile(r"^\d+(,\d+)*$")
    _MAX_LEN = 4 * 1024  # 4 KiB cap — a shape on 1000 layers is already absurd

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        cls.validate_string(value)
        if value == "":
            # empty-string LayerMember means "not on any layer"; Visio
            # desktop treats this identically to an absent cell. Accept
            # it so proxy-layer delete() can clear membership without a
            # special-case removal.
            return
        if len(value) > cls._MAX_LEN:
            raise ValueError(
                "LayerMember exceeds %d-byte cap" % cls._MAX_LEN
            )
        if not cls._LAYER_MEMBER_RE.match(value):
            raise ValueError(
                "LayerMember must be comma-separated non-negative ints, "
                "got %r" % value
            )


class ST_UniqueID(BaseStringType):
    """``Master/@UniqueID`` — curly-braced GUID unique to this master.

    Distinct from ``BaseID``: ``UniqueID`` is fresh per-document
    (regenerated on every Save-As), while ``BaseID`` is preserved
    across documents to identify master lineage.

    .. versionadded:: 0.1.0
    """

    @classmethod
    def validate(cls, value) -> None:  # type: ignore[override]
        cls.validate_string(value)
        if not _GUID_RE.match(value):
            raise ValueError(
                "UniqueID must be a curly-braced GUID, got %r" % value
            )


# -- re-export of base types for tests that assert class hierarchy ----------
# (avoids a direct dependency on the base-simple-type module from tests)

_BaseStringEnum = BaseStringEnumerationType  # alias for pyright/rewrap
_BaseSimple = BaseSimpleType  # alias for pyright/rewrap
_XsdString = XsdString  # aliased to pin it in the namespace
