"""Bundled Visio template + default-master fragments.

Two kinds of asset live here:

- ``default.vsdx`` — a minimal Visio-authored empty document used as the
  base package when :class:`vsdx.api.Visio` is called with no args. The
  file is produced by Microsoft Visio desktop and copied in verbatim.
- ``fragments/*.xml`` — per-master ``<Master>`` / ``<MasterContents>``
  XML fragments extracted from Visio-authored source fixtures
  (Rectangle, Ellipse, Triangle, Dynamic Connector). These splice into
  a package when the proxy layer instantiates a shape from a built-in
  master without having to open the source ``.vsdx`` every time.

Both asset kinds are populated from the Microsoft Visio-produced
fixtures requested in ``/tmp/vsdx-fixture-requests.md``. Until those
land, the runtime helpers here raise :class:`TemplateNotAvailable` with
an actionable message pointing at that request file.

The legality of shipping Visio-authored default content follows the
same rationale python-pptx uses for ``default-16x9.pptx`` — it's a
neutral, feature-free baseline produced by the end-user's own copy of
the product, included as a derivative work on a permissive basis. See
``README.md`` for the attribution note.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Iterator


class TemplateNotAvailable(FileNotFoundError):
    """Raised when a required bundled asset isn't on disk yet.

    The message always includes the request file's path so callers
    know exactly which fixture is still pending.
    """


_MASTER_FRAGMENTS = {
    "Rectangle": "rectangle.xml",
    "Ellipse": "ellipse.xml",
    "Triangle": "triangle.xml",
    "Dynamic Connector": "dynamic-connector.xml",
}


def default_template_path() -> Path:
    """Return the on-disk path to the bundled ``default.vsdx`` template.

    Raises :class:`TemplateNotAvailable` if the file hasn't been
    produced yet (track 4's fixture request is still outstanding).
    """
    package = resources.files(__name__)
    target = package / "default.vsdx"
    path = Path(str(target))
    if not path.exists():
        raise TemplateNotAvailable(
            "default.vsdx is not bundled yet — see the 'Track 4' section "
            "of /tmp/vsdx-fixture-requests.md for the fixture to produce "
            "and the on-disk destination."
        )
    return path


def master_fragment_path(master_name: str) -> Path:
    """Return the on-disk path to a per-master XML fragment.

    ``master_name`` is the Visio ``NameU`` attribute of the master
    (e.g. ``"Rectangle"``, ``"Dynamic Connector"``). Raises
    :class:`KeyError` for unknown masters, :class:`TemplateNotAvailable`
    for known masters whose fragment hasn't been extracted yet.
    """
    if master_name not in _MASTER_FRAGMENTS:
        raise KeyError(
            f"no bundled fragment for master {master_name!r}; known masters: "
            f"{sorted(_MASTER_FRAGMENTS)!r}"
        )
    filename = _MASTER_FRAGMENTS[master_name]
    package = resources.files(__name__) / "fragments"
    target = package / filename
    path = Path(str(target))
    if not path.exists():
        raise TemplateNotAvailable(
            f"fragment for {master_name!r} not bundled yet — see "
            f"/tmp/vsdx-fixture-requests.md (the "
            f"``{master_name.lower().replace(' ', '-')}-master.office.vsdx`` "
            f"entry)."
        )
    return path


def available_masters() -> Iterator[str]:
    """Yield the names of all masters with a bundled fragment on disk."""
    for name in _MASTER_FRAGMENTS:
        try:
            master_fragment_path(name)
        except TemplateNotAvailable:
            continue
        yield name


__all__ = [
    "TemplateNotAvailable",
    "available_masters",
    "default_template_path",
    "master_fragment_path",
]
