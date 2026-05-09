"""``Master`` + ``Masters`` proxies.

A master is a reusable shape template stored in ``/visio/masters``.
0.1.0 ships a tiny catalog of built-in masters (Rectangle, Ellipse,
Triangle, Dynamic connector) and supports *instantiating* them on a
page — full custom master creation lands in 0.2.0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Optional

from vsdx.enum.shapes import VS_SHAPE_TYPE
from vsdx.shared import ParentedElementProxy, PartElementProxy

if TYPE_CHECKING:
    from vsdx.document import VisioDocument
    from vsdx.parts._stubs import MasterPart, MastersPart  # TODO(vsdx/track-2)


#: Names of the masters that are bundled / synthesised by default so
#: ``doc.pages[0].shapes.add_shape('Rectangle')`` just works without
#: the caller having to populate ``doc.masters``.
BUILT_IN_MASTER_NAMES: tuple[str, ...] = (
    VS_SHAPE_TYPE.RECTANGLE.value,
    VS_SHAPE_TYPE.ELLIPSE.value,
    VS_SHAPE_TYPE.TRIANGLE.value,
    VS_SHAPE_TYPE.DYNAMIC_CONNECTOR.value,
)


class Master(PartElementProxy):
    """A single master (reusable shape template).

    0.1.0 surface is deliberately shallow — ``name_u`` / ``base_id`` /
    ``unique_id`` readers and not much else. Shape authoring happens
    at the *page* level; masters exist here only to satisfy the
    ``<Shape Master="…">`` reference.
    """

    def __init__(self, master_part: "MasterPart", parent: "Masters") -> None:
        super().__init__(master_part.master_element, master_part)
        self._master_part = master_part
        self._parent = parent

    @property
    def name_u(self) -> Optional[str]:
        return self._element.get("NameU")

    @property
    def name(self) -> Optional[str]:
        return self._element.get("Name") or self._element.get("NameU")

    @property
    def base_id(self) -> Optional[str]:
        return self._element.get("BaseID")

    @property
    def unique_id(self) -> Optional[str]:
        return self._element.get("UniqueID")

    @property
    def master_id(self) -> Optional[str]:
        return self._element.get("ID")

    @property
    def part(self):  # type: ignore[override]
        return self._master_part


class Masters(ParentedElementProxy):
    """Collection of masters on a :class:`~vsdx.document.VisioDocument`.

    Supports ``__iter__`` / ``__len__`` / ``__getitem__`` *and*
    dictionary-style lookup by NameU (``masters["Rectangle"]``). The
    latter mirrors ``dave-howard/vsdx``'s ``master_index`` idiom and
    is what the shape-tree uses when instantiating a shape by
    master-reference.
    """

    def __init__(self, masters_part: "MastersPart", parent: "VisioDocument") -> None:
        super().__init__(masters_part.element, parent)
        self._masters_part = masters_part
        self._master_cache: list[Master] = []
        self._rebuild_cache()

    # -- container ------------------------------------------------------

    def __iter__(self) -> Iterator[Master]:
        return iter(self._master_cache)

    def __len__(self) -> int:
        return len(self._master_cache)

    def __getitem__(self, key) -> Master:  # type: ignore[no-untyped-def]
        if isinstance(key, int):
            return self._master_cache[key]
        # Dict-style lookup by NameU.
        for m in self._master_cache:
            if m.name_u == key:
                return m
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        for m in self._master_cache:
            if m.name_u == key:
                return True
        return False

    # -- authoring ------------------------------------------------------

    def add_master(self, name_u: str) -> Master:
        """Add a new master with *name_u* and return its proxy."""
        mp = self._masters_part.add_master_part(name_u)
        master = Master(mp, self)
        self._master_cache.append(master)
        return master

    def ensure(self, name_u: str) -> Master:
        """Return the master with *name_u*, creating it if absent.

        Used by the shape-tree during ``add_shape`` to make sure every
        referenced master is present in the index. The convention
        matches the "register-on-use" pattern python-pptx uses for
        chart styles.
        """
        for m in self._master_cache:
            if m.name_u == name_u:
                return m
        return self.add_master(name_u)

    # -- internal -------------------------------------------------------

    def _rebuild_cache(self) -> None:
        self._master_cache = [
            Master(mp, self) for mp in getattr(self._masters_part, "_master_parts", [])
        ]


__all__ = ["BUILT_IN_MASTER_NAMES", "Master", "Masters"]
