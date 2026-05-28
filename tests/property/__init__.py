"""Property-based tests for python-vsdx using Hypothesis.

This package contains property-based tests that exercise python-vsdx's
read/write contracts with randomly-generated input. Tests live here
rather than under ``tests/unit/`` so they can be opted-in or skipped
independently when ``hypothesis`` is not installed.

Pattern
-------

1. Define a Hypothesis strategy (``@composite`` or ``st.*``) that
   produces well-formed input — shape pin coordinates, dimensions,
   and text labels. The strategies blacklist control characters and
   lone surrogates that the OOXML spec forbids.
2. Drive ``vsdx.Visio`` authoring with the generated input, save to
   an in-memory ``BytesIO``, reload, and assert the round trip
   preserves the input.

Each property test uses Hypothesis's default settings
(``max_examples=100``); per-test ``@settings`` overrides are applied
where the cost of one example is high (each example builds a small
Visio package).

Run
---

    pytest tests/property/ -q

The dependency on ``hypothesis`` is dev-only; production users do
not need it installed.
"""

from __future__ import annotations
