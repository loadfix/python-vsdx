"""Tokenizer for the ShapeSheet formula language.

Produces a flat ``list[Token]`` the parser consumes. The tokenizer is
deliberately forgiving — it accepts whatever Visio desktop emits — but
rejects obvious garbage (stray ``@``, unterminated strings, numeric
literals that would overflow Python's ``float``).

Token kinds we emit:

- ``NUMBER`` — integer, float, or percentage (``100%`` stored as ``1.0``).
- ``STRING`` — double-quoted, with ``""`` escape (same as Excel).
- ``IDENT`` — bare names: cell refs (``Width``, ``User.Scale``), function
  names (``IF``, ``GUARD``), ``TRUE``/``FALSE``. Disambiguation between
  "is this a function or a cell" happens in the parser, not here.
- ``OP`` — one of ``+ - * / ^ = <> < <= > >= & ! . , ( )``.
- ``COMMA``, ``LPAREN``, ``RPAREN``, ``BANG``, ``DOT`` — structural, split
  out so the parser doesn't need to re-scan ``OP`` text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from vsdx.formula.errors import FormulaParseError


class TokenKind(str, Enum):
    NUMBER = "NUMBER"
    STRING = "STRING"
    IDENT = "IDENT"
    OP = "OP"
    COMMA = "COMMA"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    BANG = "BANG"
    DOT = "DOT"
    EOF = "EOF"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    position: int

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Token({self.kind.value}, {self.value!r}, pos={self.position})"


# Two-character operator lookahead — longer ones must come first.
_TWO_CHAR_OPS = {"<=", ">=", "<>"}
_SINGLE_CHAR_OPS = set("+-*/^=<>&")


def tokenize(source: str) -> list[Token]:
    """Lex ``source`` into a list of ``Token``s ending with an EOF sentinel.

    The tokenizer is whitespace-insensitive outside string literals and
    preserves the original character offset on every token for error
    messages.
    """
    if not isinstance(source, str):
        raise FormulaParseError("formula source must be a string")

    tokens: list[Token] = []
    i = 0
    n = len(source)

    while i < n:
        c = source[i]

        # Whitespace — skip.
        if c in " \t\r\n":
            i += 1
            continue

        # String literal — double-quoted with "" escape.
        if c == '"':
            start = i
            i += 1
            buf: list[str] = []
            while i < n:
                ch = source[i]
                if ch == '"':
                    if i + 1 < n and source[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    tokens.append(Token(TokenKind.STRING, "".join(buf), start))
                    break
                buf.append(ch)
                i += 1
            else:
                raise FormulaParseError(
                    "unterminated string literal", source=source, position=start
                )
            continue

        # Number — integer or decimal, optional trailing %.
        #
        # We accept a leading '.' (``.5``) only when the preceding token
        # *isn't* an identifier / number / ')' — otherwise ``Sheet.5`` would
        # be lexed as ``Sheet`` + ``.5`` instead of the intended ``Sheet``
        # ``.`` ``5``. This matches Visio's disambiguation: dotted cell
        # qualifiers take priority over decimal literals.
        preceded_by_ref_context = (
            tokens
            and tokens[-1].kind
            in {TokenKind.IDENT, TokenKind.NUMBER, TokenKind.RPAREN}
        )
        if c.isdigit() or (
            c == "."
            and not preceded_by_ref_context
            and i + 1 < n
            and source[i + 1].isdigit()
        ):
            start = i
            saw_dot = c == "."
            i += 1
            while i < n:
                ch = source[i]
                if ch.isdigit():
                    i += 1
                elif ch == "." and not saw_dot:
                    saw_dot = True
                    i += 1
                else:
                    break
            # Exponent part.
            if i < n and source[i] in "eE":
                i += 1
                if i < n and source[i] in "+-":
                    i += 1
                if i >= n or not source[i].isdigit():
                    raise FormulaParseError(
                        "malformed exponent in numeric literal",
                        source=source,
                        position=start,
                    )
                while i < n and source[i].isdigit():
                    i += 1
            raw = source[start:i]
            # Percent suffix — divide by 100 at lex time.
            if i < n and source[i] == "%":
                i += 1
                try:
                    value = float(raw) / 100.0
                except ValueError as exc:  # pragma: no cover - defensive
                    raise FormulaParseError(
                        f"invalid numeric literal {raw!r}",
                        source=source,
                        position=start,
                    ) from exc
                tokens.append(Token(TokenKind.NUMBER, repr(value), start))
                continue
            try:
                float(raw)
            except ValueError as exc:
                raise FormulaParseError(
                    f"invalid numeric literal {raw!r}",
                    source=source,
                    position=start,
                ) from exc
            tokens.append(Token(TokenKind.NUMBER, raw, start))
            continue

        # Identifier — letter or underscore, then letters/digits/underscore.
        # Visio identifiers can also include '_' anywhere and must start
        # with a letter or underscore.
        if c.isalpha() or c == "_":
            start = i
            i += 1
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            tokens.append(Token(TokenKind.IDENT, source[start:i], start))
            continue

        # Structural punctuation.
        if c == "(":
            tokens.append(Token(TokenKind.LPAREN, c, i))
            i += 1
            continue
        if c == ")":
            tokens.append(Token(TokenKind.RPAREN, c, i))
            i += 1
            continue
        if c == ",":
            tokens.append(Token(TokenKind.COMMA, c, i))
            i += 1
            continue
        if c == "!":
            tokens.append(Token(TokenKind.BANG, c, i))
            i += 1
            continue
        if c == ".":
            tokens.append(Token(TokenKind.DOT, c, i))
            i += 1
            continue

        # Operators — try two-char first.
        if i + 1 < n and source[i : i + 2] in _TWO_CHAR_OPS:
            tokens.append(Token(TokenKind.OP, source[i : i + 2], i))
            i += 2
            continue
        if c in _SINGLE_CHAR_OPS:
            tokens.append(Token(TokenKind.OP, c, i))
            i += 1
            continue

        raise FormulaParseError(
            f"unexpected character {c!r}", source=source, position=i
        )

    tokens.append(Token(TokenKind.EOF, "", n))
    return tokens
