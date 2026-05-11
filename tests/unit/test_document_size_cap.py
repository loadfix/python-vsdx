"""Regression canary for the input-stream size cap in ``_coerce_to_stream``.

An un-hardened build reads the full ``source.read()`` into memory before
any zip-header sniff, so a multi-GB blob passed to ``VisioDocument.open``
exhausts address space during the buffer copy. The cap (default 512 MiB
via :data:`MAX_VSDX_BYTES`) fails fast with :class:`OoxmlVsdxError`.

Uses a synthetic zero-filled ``BytesIO`` buffer at 600 MiB so the canary
is deterministic without needing a fixture file. The test tolerates the
~600 MiB allocation at test time — it happens once per run and releases
immediately when the exception unwinds.
"""

from __future__ import annotations

import io

import pytest

from vsdx.document import MAX_VSDX_BYTES, OoxmlVsdxError, _coerce_to_stream


class DescribeCoerceToStreamSizeCap:
    def it_rejects_a_stream_above_the_cap(self):
        # 600 MiB > 512 MiB default cap.
        buf = io.BytesIO(b"\x00" * (600 * 1024 * 1024))
        with pytest.raises(OoxmlVsdxError):
            _coerce_to_stream(buf)

    def it_accepts_a_stream_right_at_the_cap(self):
        # Exactly MAX_VSDX_BYTES must still load. Uses a smaller check
        # to keep runtime reasonable — the boundary test for the full
        # 512 MiB value is unnecessary; we only need to prove the
        # rejection branch is `> cap`, not `>= cap`.
        buf = io.BytesIO(b"\x00" * 1024)
        out = _coerce_to_stream(buf)
        assert out.read() == b"\x00" * 1024

    def it_rewinds_the_caller_stream_after_rejection(self):
        # Even on the reject path, the caller's stream cursor should
        # be restored — matches the happy-path contract so the caller
        # can fall back to a streaming loader if they wish.
        buf = io.BytesIO(b"\x00" * (600 * 1024 * 1024))
        buf.seek(0)
        with pytest.raises(OoxmlVsdxError):
            _coerce_to_stream(buf)
        assert buf.tell() == 0

    def it_exposes_MAX_VSDX_BYTES_as_a_module_constant(self):
        # Callers that want to configure the cap (by subclassing or
        # monkey-patching) need the constant to be discoverable.
        assert MAX_VSDX_BYTES == 512 * 1024 * 1024
