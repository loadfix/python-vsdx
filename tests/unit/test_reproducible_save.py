"""End-to-end tests for ``VisioDocument.save(..., reproducible=True)``.

Closes the unified ``reproducible=`` API contract (issue #150). The
flag is a deterministic-build shorthand: every zip-member uses the
fixed 1980-01-01 timestamp, member order is normalised, and external
file attributes are clamped — yielding byte-identical archives across
machines and runs for byte-identical inputs.
"""

from __future__ import annotations

import io
import zipfile

from vsdx import Visio


class DescribeReproducibleSave:
    """Reproducible save produces byte-identical output for identical inputs."""

    def it_is_byte_identical_across_two_fresh_authoring_runs(self):
        def build() -> bytes:
            doc = Visio()
            doc.pages.add_page()
            buf = io.BytesIO()
            doc.save(buf, reproducible=True)
            return buf.getvalue()

        assert build() == build()

    def it_is_byte_identical_across_load_and_resave_round_trips(self):
        seed = io.BytesIO()
        doc = Visio()
        doc.pages.add_page()
        doc.save(seed, reproducible=True)

        def reload() -> bytes:
            seed.seek(0)
            doc = Visio(seed)
            buf = io.BytesIO()
            doc.save(buf, reproducible=True)
            return buf.getvalue()

        assert reload() == reload()

    def it_stamps_every_zip_member_with_the_fixed_timestamp(self):
        doc = Visio()
        doc.pages.add_page()
        buf = io.BytesIO()
        doc.save(buf, reproducible=True)

        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            timestamps = {info.date_time for info in z.infolist()}
        assert timestamps == {(1980, 1, 1, 0, 0, 0)}

    def it_emits_zip_members_in_sorted_order(self):
        doc = Visio()
        doc.pages.add_page()
        buf = io.BytesIO()
        doc.save(buf, reproducible=True)

        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            names = z.namelist()
        assert names == sorted(names)

    def but_it_does_not_force_a_fixed_timestamp_when_reproducible_is_False(self):
        doc = Visio()
        doc.pages.add_page()
        buf = io.BytesIO()
        doc.save(buf)  # default: reproducible=False

        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            timestamps = {info.date_time for info in z.infolist()}
        assert timestamps != {(1980, 1, 1, 0, 0, 0)}
