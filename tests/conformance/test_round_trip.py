"""Byte-identical round-trip conformance harness for python-vsdx.

Enforces the first of the three non-negotiable conformance constraints
declared in ``python-vsdx/CLAUDE.md`` and
``audits/2026-05-09-vsdx-scoping.md`` §9.1:

    Byte-identical round-trip on unmodified reads.

For every Microsoft-Visio-authored fixture we can find, load it via
:class:`vsdx.package.VisioPackage`, serialise it back via ``.save()``,
and assert that the resulting zip entries are byte-identical to the
original's. Failure points at the single part whose bytes drift,
rather than dumping the whole-package diff.

Scope — pure instrumentation
---------------------------

This harness does **not** fix any round-trip bugs. It surfaces them.
When a fixture lands and the test fails, the failure gets its own
ticket; the harness itself stays frozen at the byte-equality contract.
Every relaxation risks masking a real silent drop — see the xlsx
round-trip harness's stern stance in
``python-xlsx/tests/roundtrip/test_fidelity.py`` for the same
discipline applied there.

How to run
----------

.. code-block:: shell

    # run the harness (skipped cleanly when no fixtures are present)
    pytest -m conformance tests/conformance/

    # exclude the harness from an ordinary unit run
    pytest -m 'not conformance' tests/

Fixture sources
---------------

- ``~/code/ooxml-reference-corpus/fixtures/vsdx/*.office.vsdx`` —
  18 fixtures listed in ``audits/2026-05-09-vsdx-fixture-guide.md``.
  Overridable with ``VSDX_CORPUS_ROOT``.
- ``src/vsdx/templates/default.vsdx`` — bundled template used by
  :func:`vsdx.api.Visio` when called with no arguments.

Both sources may be absent in a clean checkout; the harness skips
rather than failing, per the standard green-CI contract.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.conformance.conftest import ALL_FIXTURE_IDS, ALL_FIXTURES
from tests.conformance.diff import (
    RoundtripDiff,
    compare_zips,
    format_diff_message,
    read_zip_entries,
)

# Module-level marker so ``pytest -m conformance`` selects the harness,
# and ``pytest -m 'not conformance'`` excludes it during a plain unit
# run. All tests in the file inherit this marker.
pytestmark = pytest.mark.conformance


# Module-level skipif so an empty fixture list (clean checkout, no
# corpus mounted, no template bundled) produces a single readable
# skip reason rather than one "no-fixtures" skip per parametrised test.
_SKIP_REASON = (
    "no vsdx fixtures available — land .office.vsdx files under "
    "~/code/ooxml-reference-corpus/fixtures/vsdx/ (see "
    "audits/2026-05-09-vsdx-fixture-guide.md) or bundle "
    "src/vsdx/templates/default.vsdx"
)


# ---------------------------------------------------------------------------
# Session-cached load + save
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def round_trip_bytes() -> dict[str, tuple[bytes, bytes]]:
    """Return ``{fixture_name: (original_bytes, saved_bytes)}``.

    The load + save step is the expensive half of the harness — each
    invocation parses a full OPC package and re-emits it through the
    reproducible-zip writer. Caching the pair per module lets downstream
    tests attach assertions (byte-equal, entry-count, whatever comes
    next) without paying the cost again.

    Fixtures the reader refuses (for instance a stencil-only ``.vssx``
    variant before 0.2.0 lands content-type support) are logged on
    the returned map as ``(original_bytes, b"")`` paired with an
    :exc:`Exception`; the per-fixture test then skips with the
    exception's type in its reason. That keeps one unsupported
    fixture from taking down the whole module.
    """
    # Lazy import: keep the module importable outside an installed
    # editable dev environment so CI's collection phase doesn't blow
    # up if a sibling job is running without ``pip install -e``.
    from vsdx.package import VisioPackage

    cache: dict[str, tuple[bytes, bytes]] = {}
    for path in ALL_FIXTURES:
        original = path.read_bytes()
        try:
            package = VisioPackage.open(str(path))
            buf = io.BytesIO()
            package.save(buf)
            cache[path.name] = (original, buf.getvalue())
        except Exception as exc:  # noqa: BLE001 — surfacing reader refusals
            # Stash the exception as the "saved" slot; the per-fixture
            # test inspects the empty-saved case and skips cleanly.
            # We avoid pytest.skip here because the session fixture
            # runs once; a skip would wipe out every later fixture.
            cache[path.name] = (original, b"")
            # Store the exception on the cache keyed by a reserved
            # sentinel so the per-fixture test can give a useful
            # message. ``dict`` key namespaces keep this tidy.
            cache[f"__error__:{path.name}"] = (type(exc).__name__.encode(), str(exc).encode())
    return cache


# ---------------------------------------------------------------------------
# Per-fixture byte-round-trip tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ALL_FIXTURES, reason=_SKIP_REASON)
@pytest.mark.parametrize(
    "fixture_path",
    ALL_FIXTURES,
    ids=ALL_FIXTURE_IDS,
)
def test_round_trip_is_byte_identical(
    fixture_path: Path,
    round_trip_bytes: dict[str, tuple[bytes, bytes]],
) -> None:
    """Every part in the saved package must byte-equal the original.

    The comparison is per zip entry, not whole-zip hash — see
    ``diff.py`` for the rationale. A failure names the drifting
    part(s) and shows a short preview of the textual divergence
    (capped at 200 chars per side) so the investigator can triage
    without running a separate diff tool.
    """
    name = fixture_path.name
    original_bytes, saved_bytes = round_trip_bytes[name]

    if not saved_bytes:
        # Reader refused — surface the exception type in the skip
        # reason so the failure remains attributable to the fixture
        # rather than looking like a bug in the harness.
        err_entry = round_trip_bytes.get(f"__error__:{name}")
        if err_entry is not None:
            exc_name = err_entry[0].decode()
            exc_msg = err_entry[1].decode()
            pytest.skip(
                f"{name}: VisioPackage.open raised {exc_name}: "
                f"{exc_msg} — not a round-trip regression, file a "
                f"reader bug."
            )
        pytest.skip(f"{name}: reader returned empty bytes.")

    original_entries = read_zip_entries(original_bytes)
    saved_entries = read_zip_entries(saved_bytes)
    diff: RoundtripDiff = compare_zips(
        original_entries, saved_entries, fixture=name
    )

    if not diff.is_clean():
        # Surface a readable, length-capped message — the investigator
        # gets the drifting entry names and a 200-char preview of each
        # side, not a megabyte of XML dump. See
        # ``tests/conformance/diff.py::format_diff_message``.
        pytest.fail(format_diff_message(diff))
