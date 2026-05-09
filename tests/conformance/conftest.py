"""Conformance-harness pytest configuration for python-vsdx.

Discovers the two fixture sources the byte-round-trip harness runs
against:

1. Every ``*.office.vsdx`` (and ``*.office.vssx``) file under the
   reference-corpus directory at
   ``~/code/ooxml-reference-corpus/fixtures/vsdx/``. Path is
   overridable with the ``VSDX_CORPUS_ROOT`` env var (same convention
   as ``tests/conftest.py``'s ``_default_corpus_root``). When the
   directory is missing the conformance tests skip cleanly — the
   fixture set is produced by the user via Microsoft Visio desktop
   and may not exist in every checkout.

2. The bundled template at ``src/vsdx/templates/default.vsdx`` when
   present. :func:`vsdx.templates.default_template_path` raises
   :class:`TemplateNotAvailable` until the user lands the fixture; we
   treat that the same as "not present" and omit it from the fixture
   list rather than hard-failing the harness.

The list is computed **at import time** so pytest's parametrisation
machinery can build per-fixture test IDs that are visible in verbose
output (e.g. ``test_round_trip_is_byte_identical[empty.office.vsdx]``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

__all__ = [
    "CORPUS_FIXTURES",
    "CORPUS_FIXTURE_IDS",
    "TEMPLATE_FIXTURES",
    "TEMPLATE_FIXTURE_IDS",
    "ALL_FIXTURES",
    "ALL_FIXTURE_IDS",
    "discover_corpus_fixtures",
    "discover_template_fixtures",
]


# -- Extensions we treat as Visio-family packages. ``.vsdx`` is the
# -- 0.1.0 target; the other Visio OOXML variants (``.vsdm`` macro-
# -- enabled drawing, ``.vssx`` / ``.vssm`` stencil, ``.vstx`` /
# -- ``.vstm`` template) are out of 0.1.0 scope per the scoping doc
# -- but are listed here so fixtures dropped in early get exercised
# -- and surface their scope mismatch as a skip/xfail rather than
# -- silently missing.
_VSDX_EXTENSIONS = (".vsdx", ".vsdm", ".vssx", ".vssm", ".vstx", ".vstm")


def _corpus_root() -> Path:
    """Return the resolved corpus-fixture directory.

    Mirrors ``tests/conftest.py::_default_corpus_root`` so conformance
    and unit suites agree on the lookup. Kept a private copy instead
    of importing the unit conftest to keep the module independently
    importable outside a pytest session.
    """
    override = os.environ.get("VSDX_CORPUS_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path("~/code/ooxml-reference-corpus/fixtures/vsdx").expanduser()


def discover_corpus_fixtures(root: Path | None = None) -> list[Path]:
    """Return every Visio-family fixture under ``root``.

    Sorted by filename so parametrisation is deterministic across runs.
    Returns an empty list when the directory is absent — the caller is
    expected to guard with a module-level skipif or per-test skip so
    the harness doesn't raise on clean checkouts.
    """
    base = root or _corpus_root()
    if not base.is_dir():
        return []
    return sorted(
        path
        for path in base.iterdir()
        if path.is_file()
        and path.suffix.lower() in _VSDX_EXTENSIONS
        # Skip MS Office lock files (``~$empty.office.vsdx``) — they
        # mean Visio desktop is *currently editing* the fixture and
        # the lock is a tiny OLE CFB blob, not a zip.
        and not path.name.startswith("~$")
    )


def discover_template_fixtures() -> list[Path]:
    """Return the bundled ``default.vsdx`` template when it exists.

    Wraps :func:`vsdx.templates.default_template_path` and swallows
    :class:`vsdx.templates.TemplateNotAvailable` so the conformance
    module can be imported in environments where the template asset
    hasn't been bundled yet (which is the current state — see
    ``tests/test_templates.py``).
    """
    try:
        # Deferred import: ``vsdx.templates`` pulls in ``vsdx.__init__``
        # which drags in half the package. We only pay that cost when
        # the harness actually runs (i.e. collection time for a
        # ``-m conformance`` invocation).
        from vsdx.templates import TemplateNotAvailable, default_template_path
    except ImportError:
        return []
    try:
        path = default_template_path()
    except TemplateNotAvailable:
        return []
    return [path]


CORPUS_FIXTURES: list[Path] = discover_corpus_fixtures()
CORPUS_FIXTURE_IDS: list[str] = [p.name for p in CORPUS_FIXTURES]

TEMPLATE_FIXTURES: list[Path] = discover_template_fixtures()
TEMPLATE_FIXTURE_IDS: list[str] = [
    f"template:{p.name}" for p in TEMPLATE_FIXTURES
]

ALL_FIXTURES: list[Path] = CORPUS_FIXTURES + TEMPLATE_FIXTURES
ALL_FIXTURE_IDS: list[str] = CORPUS_FIXTURE_IDS + TEMPLATE_FIXTURE_IDS


@pytest.fixture(scope="session")
def corpus_fixtures_list() -> list[Path]:
    """Expose the discovered corpus fixture list as a session fixture."""
    return list(CORPUS_FIXTURES)


@pytest.fixture(scope="session")
def template_fixtures_list() -> list[Path]:
    """Expose the discovered template fixture list as a session fixture."""
    return list(TEMPLATE_FIXTURES)
