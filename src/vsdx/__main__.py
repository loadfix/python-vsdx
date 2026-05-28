"""Command-line entry point — ``python -m vsdx``.

Currently exposes a single subcommand:

* ``lint <path>`` — run :func:`vsdx.lint.lint` against every page in the
  given drawing and print each finding as one line. Exits non-zero when
  any ``error``-severity finding fires (so the command fits naturally
  into a CI gate); ``warning`` / ``info`` findings always exit zero.

Future subcommands (info, validate, …) will land alongside ``lint`` —
the dispatch is intentionally simple to keep the surface trivial to
extend.

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence


def _cmd_lint(args: argparse.Namespace) -> int:
    # Imported lazily so ``python -m vsdx --help`` doesn't pay the OPC
    # / xmlchemy import bill on the help path.
    from vsdx.api import VisioPackageOpener
    from vsdx.lint import SEVERITY_ERROR

    selected_rules = args.rules.split(",") if args.rules else None

    try:
        doc = VisioPackageOpener.open(args.path)
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    exit_code = 0
    total = 0
    for page in doc.pages:
        page_name = page.name or "?"
        findings = page.lint(rules=selected_rules)
        for finding in findings:
            total += 1
            print("%s: %s" % (page_name, finding))
            if finding.severity == SEVERITY_ERROR:
                exit_code = 1
    if total == 0:
        print("clean")
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vsdx",
        description="Inspect / lint Microsoft Visio (.vsdx) files.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    lint_p = sub.add_parser(
        "lint",
        help="Lint a .vsdx for diagram-quality issues.",
    )
    lint_p.add_argument("path", help="Path to a .vsdx / .vsdm file.")
    lint_p.add_argument(
        "--rules",
        default=None,
        help="Comma-separated rule-id allowlist (default: all rules).",
    )
    lint_p.set_defaults(func=_cmd_lint)
    return parser


def main(argv: "Optional[Sequence[str]]" = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
