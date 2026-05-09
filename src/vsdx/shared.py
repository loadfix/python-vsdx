"""Shared proxy base classes for python-vsdx.

Mirror python-pptx's ``shared.py`` exactly so the proxy hierarchy
feels identical. Three base classes:

* ``ElementProxy`` — wraps an lxml element (or, for 0.1.0, any
  object that presents a ``.tag`` / children interface — the stubs
  below use a small dataclass shim until Track 1 lands the real
  ``CT_*`` classes).
* ``ParentedElementProxy`` — adds a ``parent`` pointer so the wrapped
  element can walk up the proxy tree (used by ``Shape`` reaching its
  owning ``Page``).
* ``PartElementProxy`` — adds a ``part`` pointer; used where a proxy
  owns a part (``VisioDocument``, ``PagePart``'s root, etc.).

These deliberately carry no concrete behaviour — they exist for
docs-wise consistency with python-pptx and so the integration pass
can swap the duck-typed ``element`` parameter for a real
``BaseOxmlElement`` once Track 1 hands off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


class ElementProxy:
    """Base class for every proxy object in the vsdx API surface.

    The wrapped ``_element`` is intentionally typed as ``Any`` on
    construction because Track 1 (oxml) is still in flight. Subclasses
    re-annotate it precisely.
    """

    def __init__(self, element: Any) -> None:
        self._element = element

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ElementProxy):
            return False
        return self._element is other._element

    def __ne__(self, other: object) -> bool:
        if not isinstance(other, ElementProxy):
            return True
        return self._element is not other._element

    def __hash__(self) -> int:
        return id(self._element)

    @property
    def element(self) -> Any:
        """Return the underlying oxml element."""
        return self._element


class ParentedElementProxy(ElementProxy):
    """ElementProxy that also remembers its proxy-tree parent.

    The ``parent`` reference gives sub-shapes like a ``Run`` or a
    ``Cell`` a path back up to the page / document that owns them,
    without having to re-index the lxml tree each time.
    """

    def __init__(self, element: Any, parent: Any) -> None:
        super().__init__(element)
        self._parent = parent

    @property
    def parent(self) -> Any:
        return self._parent

    @property
    def part(self) -> Any:
        # Walk up until we find an object that exposes ``part``.
        p = self._parent
        while p is not None:
            if hasattr(p, "_as_part"):
                return p
            if hasattr(p, "part"):
                return p.part
            p = getattr(p, "_parent", None)
        return None


class PartElementProxy(ElementProxy):
    """ElementProxy that wraps a part-root element and remembers its part."""

    def __init__(self, element: Any, part: Any) -> None:
        super().__init__(element)
        self._part = part

    @property
    def part(self) -> Any:
        return self._part


class Subshape:
    """Helper mixin for sub-shape proxies that only care about their part.

    Mirrors ``pptx.shapes.Subshape``. Used by run / paragraph / cell
    proxies that need the containing part (to add a relationship, say)
    but don't need a proxy-tree parent reference beyond that.
    """

    def __init__(self, parent: Any) -> None:
        self._parent = parent

    @property
    def part(self) -> Any:
        return self._parent.part


__all__ = [
    "ElementProxy",
    "ParentedElementProxy",
    "PartElementProxy",
    "Subshape",
]
