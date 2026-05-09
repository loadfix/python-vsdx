"""Table-driven tests for :mod:`vsdx.formula.tokenizer`."""

from __future__ import annotations

import pytest

from vsdx.formula.errors import FormulaParseError
from vsdx.formula.tokenizer import TokenKind, tokenize


class DescribeTokenizer:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("1", [(TokenKind.NUMBER, "1")]),
            ("1.5", [(TokenKind.NUMBER, "1.5")]),
            (".5", [(TokenKind.NUMBER, ".5")]),
            ("1e3", [(TokenKind.NUMBER, "1e3")]),
            ("1.5e-2", [(TokenKind.NUMBER, "1.5e-2")]),
            # Percent is pre-scaled at lex time — value stored as repr(float).
            ("100%", [(TokenKind.NUMBER, "1.0")]),
            ('"hello"', [(TokenKind.STRING, "hello")]),
            ('"he said ""hi"""', [(TokenKind.STRING, 'he said "hi"')]),
            ("Width", [(TokenKind.IDENT, "Width")]),
            ("_foo", [(TokenKind.IDENT, "_foo")]),
            ("TRUE", [(TokenKind.IDENT, "TRUE")]),
            ("+", [(TokenKind.OP, "+")]),
            ("<>", [(TokenKind.OP, "<>")]),
            ("<=", [(TokenKind.OP, "<=")]),
            (">=", [(TokenKind.OP, ">=")]),
            ("&", [(TokenKind.OP, "&")]),
            (
                "1+2",
                [
                    (TokenKind.NUMBER, "1"),
                    (TokenKind.OP, "+"),
                    (TokenKind.NUMBER, "2"),
                ],
            ),
        ],
    )
    def it_tokenizes_basic_literals_and_operators(self, source, expected):
        toks = tokenize(source)
        assert toks[-1].kind is TokenKind.EOF
        got = [(t.kind, t.value) for t in toks[:-1]]
        assert got == expected

    def it_lexes_sheet_N_bang_cell_not_decimal(self):
        # Sheet.5!PinX must split into Sheet DOT 5 BANG PinX — not ``.5``.
        toks = tokenize("Sheet.5!PinX")
        kinds = [t.kind for t in toks if t.kind is not TokenKind.EOF]
        assert kinds == [
            TokenKind.IDENT,
            TokenKind.DOT,
            TokenKind.NUMBER,
            TokenKind.BANG,
            TokenKind.IDENT,
        ]

    def it_lexes_dotted_section_row_name(self):
        toks = tokenize("User.Scale.Value")
        kinds = [t.kind for t in toks if t.kind is not TokenKind.EOF]
        assert kinds == [
            TokenKind.IDENT,
            TokenKind.DOT,
            TokenKind.IDENT,
            TokenKind.DOT,
            TokenKind.IDENT,
        ]

    def it_tracks_source_positions(self):
        toks = tokenize("  1 + 2")
        # First number is at offset 2, operator at 4, second number at 6.
        positions = [t.position for t in toks if t.kind is not TokenKind.EOF]
        assert positions == [2, 4, 6]

    @pytest.mark.parametrize(
        "bad",
        ['"unterminated', "@", "1e", "1.2.3e"],
    )
    def it_rejects_malformed_input(self, bad):
        with pytest.raises(FormulaParseError):
            tokenize(bad)

    def it_handles_whitespace_only(self):
        toks = tokenize("   \t \n")
        assert len(toks) == 1
        assert toks[0].kind is TokenKind.EOF

    def it_rejects_non_string_source(self):
        with pytest.raises(FormulaParseError):
            tokenize(123)  # type: ignore[arg-type]
