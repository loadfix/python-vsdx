"""Shared helpers for python-vsdx acceptance test step implementations.

Mirrors ``python-pptx/features/steps/helpers.py`` — exposes the
``_scratch`` path used for throw-away saved files and a path-resolver
for the bundled ``default.vsdx`` template (the only on-disk
``.vsdx`` fixture the suite relies on; everything else is generated
in-step).
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import os

thisdir = os.path.split(__file__)[0]
scratch_dir = os.path.abspath(os.path.join(thisdir, "..", "_scratch"))


def scratch_path(filename: str) -> str:
    """Return the absolute path to *filename* under ``features/_scratch``."""
    return os.path.join(scratch_dir, filename)


def default_template_path() -> str:
    """Return the absolute path to the bundled ``default.vsdx`` template.

    Skips cleanly if the template isn't on disk yet (clean checkout
    before the seed-template fixture lands).
    """
    from vsdx.templates import default_template_path as _impl

    return str(_impl())
