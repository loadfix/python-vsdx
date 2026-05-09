"""Per-entry zip-package diff for the vsdx byte-round-trip harness.

Visio's authoring floor requires *byte-identical* round-trip on unmodified
reads — see ``audits/2026-05-09-vsdx-scoping.md`` §9.1 and the "Three
conformance constraints" section of ``python-vsdx/CLAUDE.md``. This module
provides the diff primitive the conformance tests run against.

Why per-entry, not whole-zip-hash
---------------------------------

A whole-zip SHA would be fooled by cosmetic differences the OPC writer is
explicitly allowed to perturb: zip-entry ordering, ``zip_date_time``,
compression level. The reproducible-zip writer in
``ooxml_opc.zip_writer`` normalises those, but the *test* should still
isolate one changed part from dragging the whole-zip comparison red.
Failing at the entry level also gives developers a readable message
naming the guilty part instead of "hash differs".

What counts as "equal"
----------------------

For Visio 0.1.0 the byte-round-trip contract is literal: same zip entry
name, same bytes, same count. We deliberately do **not** canonicalise
XML before comparing — attribute-order preservation is part of the
contract (xmlchemy descriptor setters must not re-sort, see
``CLAUDE.md`` track 1). Canonicalisation would mask the very bug the
harness is meant to catch.

The xlsx harness (``python-xlsx/tests/roundtrip/diff.py``) goes the
other way — canonicalises XML before comparing — because xlsx's
contract is weaker ("nothing silently drops", not "bytes match").
Different contract → different primitive.

.. versionadded:: 0.1.0
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "EntryDiff",
    "RoundtripDiff",
    "compare_zips",
    "read_zip_entries",
    "render_entry_preview",
]


@dataclass
class EntryDiff:
    """One zip entry that differs between original and saved packages.

    Attributes:
        name: The zip-entry name (e.g. ``visio/pages/page1.xml``).
        original_len: Byte length of the entry in the original package.
        saved_len: Byte length of the entry in the saved package.
        original_preview: First 200 chars of the original entry (text),
            or a short hex preview if the entry is binary.
        saved_preview: Equivalent preview of the saved entry.
    """

    name: str
    original_len: int
    saved_len: int
    original_preview: str
    saved_preview: str


@dataclass
class RoundtripDiff:
    """Result of comparing an original and a saved ``.vsdx`` package.

    Attributes:
        fixture: Human-readable identifier for the fixture (usually its
            basename).
        missing: Entries present in the original but absent from the
            saved package (dropped parts).
        added: Entries present in the saved package but absent from the
            original (spurious parts).
        changed: Entries whose *bytes* differ between the two. Each
            :class:`EntryDiff` carries a preview so the assertion
            message shows the nature of the drift without dumping the
            whole XML.
    """

    fixture: str
    # ``field(default_factory=list)`` makes pyright infer ``list[Unknown]``
    # because the factory's return type has no parameterisation. Annotating
    # the default factory with an explicit ``list[T]`` lambda gives pyright
    # the concrete element type it needs under strict mode.
    missing: list[str] = field(default_factory=lambda: [])
    added: list[str] = field(default_factory=lambda: [])
    changed: list[EntryDiff] = field(default_factory=lambda: [])

    def is_clean(self) -> bool:
        """Return ``True`` when the round-trip is byte-identical."""
        return not (self.missing or self.added or self.changed)


def read_zip_entries(
    source: str | Path | bytes | bytearray | io.BytesIO,
) -> dict[str, bytes]:
    """Return ``{entry_name: bytes}`` for every file in the zip.

    Directory entries are skipped — they carry no payload and their
    presence / absence is incidental to the round-trip contract.
    """
    if isinstance(source, (bytes, bytearray)):
        buf: str | io.BytesIO = io.BytesIO(bytes(source))
    elif isinstance(source, Path):
        buf = str(source)
    elif isinstance(source, str):
        buf = source
    else:
        buf = source  # file-like
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(buf, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out[info.filename] = zf.read(info.filename)
    return out


def render_entry_preview(data: bytes, limit: int = 200) -> str:
    """Return a short, printable preview of ``data`` for diff messages.

    XML-shaped payloads (anything starting with ``<`` after decoding as
    UTF-8) get the first ``limit`` characters of their text; binary
    payloads get a compact hex dump of the first 32 bytes with the
    total length appended. The goal is a readable ~one-line hint, not
    a full diff dump.
    """
    if not data:
        return "<empty>"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        head = data[:32].hex(" ")
        return f"<binary {len(data)} bytes: {head}...>"
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _describe_change(
    name: str, original: bytes, saved: bytes
) -> EntryDiff:
    return EntryDiff(
        name=name,
        original_len=len(original),
        saved_len=len(saved),
        original_preview=render_entry_preview(original),
        saved_preview=render_entry_preview(saved),
    )


def compare_zips(
    original: dict[str, bytes],
    saved: dict[str, bytes],
    fixture: str = "<anonymous>",
) -> RoundtripDiff:
    """Compare two ``{entry_name: bytes}`` maps and summarise the drift.

    Byte-equal entries are omitted from the result. Entries that exist
    in only one side go into ``missing`` / ``added``. Entries present
    in both but with different bytes go into ``changed`` with a short
    preview attached.
    """
    diff = RoundtripDiff(fixture=fixture)
    original_names = set(original)
    saved_names = set(saved)
    diff.missing = sorted(original_names - saved_names)
    diff.added = sorted(saved_names - original_names)
    for name in sorted(original_names & saved_names):
        if original[name] != saved[name]:
            diff.changed.append(_describe_change(name, original[name], saved[name]))
    return diff


def format_diff_message(diff: RoundtripDiff, *, limit: int = 10) -> str:
    """Render a ``RoundtripDiff`` as a readable assertion message.

    Caps the ``changed`` list at ``limit`` entries so a totally-broken
    round-trip doesn't produce a megabyte of output. The message always
    states the fixture name and the three category counts up front so
    the failure is scannable.
    """
    lines: list[str] = [
        f"{diff.fixture}: byte-round-trip drift — "
        f"missing={len(diff.missing)} added={len(diff.added)} "
        f"changed={len(diff.changed)}",
    ]
    if diff.missing:
        lines.append("  missing (dropped on save):")
        for name in diff.missing[:limit]:
            lines.append(f"    - {name}")
        if len(diff.missing) > limit:
            lines.append(f"    ... (+{len(diff.missing) - limit} more)")
    if diff.added:
        lines.append("  added (not in original):")
        for name in diff.added[:limit]:
            lines.append(f"    + {name}")
        if len(diff.added) > limit:
            lines.append(f"    ... (+{len(diff.added) - limit} more)")
    if diff.changed:
        lines.append("  changed (bytes differ):")
        for entry in diff.changed[:limit]:
            lines.append(
                f"    * {entry.name} "
                f"(orig {entry.original_len}B -> saved {entry.saved_len}B)"
            )
            lines.append(f"        orig: {entry.original_preview}")
            lines.append(f"        save: {entry.saved_preview}")
        if len(diff.changed) > limit:
            lines.append(f"    ... (+{len(diff.changed) - limit} more)")
    return "\n".join(lines)


def diff_fixture_bytes(
    fixture_bytes: bytes, saved_bytes: bytes, fixture: str
) -> RoundtripDiff:
    """Convenience: unpack two in-memory zips and diff them."""
    original = read_zip_entries(fixture_bytes)
    saved = read_zip_entries(saved_bytes)
    return compare_zips(original, saved, fixture=fixture)


def round_trip_pair(path: str | Path) -> tuple[bytes, bytes]:
    """Load a ``.vsdx`` at ``path`` via vsdx, save it, return both bytes.

    Kept separate from :func:`diff_fixture_bytes` so test modules can
    cache the expensive load-and-save step without re-computing the
    diff on every assertion.
    """
    # Imported lazily so this module doesn't hard-require vsdx at
    # collection time — useful for environments where the package isn't
    # installed yet but the harness module is being imported for
    # documentation / static analysis.
    from vsdx.package import VisioPackage

    source_path = Path(path)
    original_bytes = source_path.read_bytes()
    package = VisioPackage.open(str(source_path))
    buf = io.BytesIO()
    package.save(buf)
    return original_bytes, buf.getvalue()
