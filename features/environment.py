"""Behave environment hooks for python-vsdx acceptance tests.

Mirrors ``python-pptx/features/environment.py`` and
``python-docx/features/environment.py``: ensures the per-feature
``_scratch`` directory exists before any scenario runs, so steps can
freely save throw-away ``.vsdx`` files without cleanup boilerplate.
"""

# Copyright 2026 loadfix contributors
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from __future__ import annotations

import os

scratch_dir = os.path.abspath(
    os.path.join(os.path.split(__file__)[0], "_scratch")
)


def before_all(context):  # type: ignore[no-untyped-def]
    if not os.path.isdir(scratch_dir):
        os.mkdir(scratch_dir)
