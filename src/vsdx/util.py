"""Utility classes for vsdx — length units, lazy properties, shared helpers.

Visio's native unit at the @U attribute level is usually "IN" (inches),
sometimes "MM", "CM", or "PT". Internally we keep lengths in *inches as
float* because Visio's XML at the cell level stores decimal inches, not
EMUs. This is a deliberate divergence from docx/pptx (which pin to EMU
throughout) — it keeps the @V / @U attributes round-trippable without
precision loss.

The classes mirror the shape of ``pptx.util.Length`` / ``Inches`` /
``Cm`` / ``Mm`` / ``Pt`` so users coming from python-pptx meet a
familiar surface. We additionally expose an ``emu`` accessor so
callers can convert to the shared-package EMU vocabulary when needed
(e.g. when talking to ``ooxml_opc.units``).
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Generic, TypeVar, cast


class Length(float):
    """Base class for Visio length values expressed in inches.

    A ``Length`` is a ``float`` with conversion accessors. Internally the
    value carried is *inches* (not EMU). The accessors convert to other
    units on demand.
    """

    _INCHES_PER_CM = 1.0 / 2.54
    _INCHES_PER_MM = 1.0 / 25.4
    _INCHES_PER_PT = 1.0 / 72.0
    _EMUS_PER_INCH = 914400

    def __new__(cls, inches: float) -> "Length":
        return float.__new__(cls, inches)

    @property
    def inches(self) -> float:
        return float(self)

    @property
    def cm(self) -> float:
        return float(self) / self._INCHES_PER_CM

    @property
    def mm(self) -> float:
        return float(self) / self._INCHES_PER_MM

    @property
    def pt(self) -> float:
        return float(self) / self._INCHES_PER_PT

    @property
    def emu(self) -> int:
        return int(round(float(self) * self._EMUS_PER_INCH))


class Inches(Length):
    """Convenience constructor for a length in inches."""

    def __new__(cls, inches: float) -> "Inches":
        return cast("Inches", float.__new__(cls, float(inches)))


class Cm(Length):
    """Convenience constructor for a length in centimetres."""

    def __new__(cls, cm: float) -> "Cm":
        return cast("Cm", float.__new__(cls, cm * Length._INCHES_PER_CM))


class Mm(Length):
    """Convenience constructor for a length in millimetres."""

    def __new__(cls, mm: float) -> "Mm":
        return cast("Mm", float.__new__(cls, mm * Length._INCHES_PER_MM))


class Pt(Length):
    """Convenience constructor for a length in points (1/72 inch)."""

    def __new__(cls, pt: float) -> "Pt":
        return cast("Pt", float.__new__(cls, pt * Length._INCHES_PER_PT))


class Emu(Length):
    """Convenience constructor from English Metric Units.

    Accepted for interop with shared-package code that thinks in EMU.
    """

    def __new__(cls, emu: int) -> "Emu":
        return cast("Emu", float.__new__(cls, emu / Length._EMUS_PER_INCH))


T = TypeVar("T")


class lazyproperty(Generic[T]):
    """Decorator like ``@property`` but computed once per instance and cached.

    Exact semantic match for ``pptx.util.lazyproperty`` — the proxy
    layer relies on identity (``obj.pages is obj.pages``) for collection
    members, so re-computing on each access would break equality and
    churn allocations.
    """

    def __init__(self, fget: Callable[[Any], T]):
        self._fget = fget
        self._name = fget.__name__
        functools.update_wrapper(self, fget, updated=[])

    def __get__(self, instance: Any, owner: Any = None) -> T:
        if instance is None:
            return cast(T, self)
        value = self._fget(instance)
        instance.__dict__[self._name] = value
        return value


__all__ = ["Cm", "Emu", "Inches", "Length", "Mm", "Pt", "lazyproperty"]
