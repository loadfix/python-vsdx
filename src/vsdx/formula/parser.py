"""Pratt parser for ShapeSheet formula expressions.

The grammar is:

    expr        := comparison
    comparison  := concat (('=' | '<>' | '<' | '<=' | '>' | '>=') concat)*
    concat      := add ('&' add)*
    add         := mul (('+' | '-') mul)*
    mul         := pow (('*' | '/') pow)*
    pow         := unary ('^' unary)*             # right-assoc
    unary       := ('+' | '-') unary | primary
    primary     := NUMBER | STRING | 'TRUE' | 'FALSE'
                 | function_call
                 | cell_ref
                 | '(' expr ')'
    function_call := IDENT '(' arglist? ')'
    arglist     := expr (',' expr)*
    cell_ref    := [sheet '!'] (section ['.' row])? '.'? cell_name

Cell references are subtle: ``Width`` is a singleton cell, ``User.Scale`` is
a section cell (User-section, row "Scale"), ``Geometry1.X1`` is row 1 of the
first Geometry section, ``Sheet.5!PinX`` is the PinX cell of shape whose
ID attribute equals 5. We parse the dotted/banged prefix up to the first
non-cell-name identifier and classify in ``_finish_cell_ref``.
"""

from __future__ import annotations

from typing import Optional

from vsdx.formula.errors import FormulaParseError
from vsdx.formula.nodes import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    FunctionCall,
    Node,
    NumberLiteral,
    StringLiteral,
    UnaryOp,
)
from vsdx.formula.tokenizer import Token, TokenKind, tokenize

_COMPARISON_OPS = {"=", "<>", "<", "<=", ">", ">="}
_ADD_OPS = {"+", "-"}
_MUL_OPS = {"*", "/"}


# Cell-name tokens that may appear *after* a dotted section with a row
# qualifier, e.g. ``User.Scale.Value``. Visio emits these for prop / user
# cells where the cell name defaults to ``Value``.
_IMPLICIT_CELL_NAMES = {"Value", "Prompt", "Format", "Invisible", "Verify"}


class Parser:
    """Recursive-descent Pratt parser over a flat token list.

    Instantiated per-formula; not thread-safe and not reusable. Use the
    module-level :func:`parse` convenience for one-shot parsing.
    """

    def __init__(self, tokens: list[Token], source: str = ""):
        self._tokens = tokens
        self._pos = 0
        self._source = source

    # ------------------------------------------------------------------ utilities

    def _peek(self, offset: int = 0) -> Token:
        idx = self._pos + offset
        if idx >= len(self._tokens):
            return self._tokens[-1]
        return self._tokens[idx]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: TokenKind, value: Optional[str] = None) -> Token:
        tok = self._peek()
        if tok.kind is not kind or (value is not None and tok.value != value):
            expected = value if value is not None else kind.value
            raise FormulaParseError(
                f"expected {expected!r}, got {tok.value!r}",
                source=self._source,
                position=tok.position,
            )
        return self._advance()

    # ------------------------------------------------------------------ grammar

    def parse(self) -> Node:
        node = self._parse_expr()
        final = self._peek()
        if final.kind is not TokenKind.EOF:
            raise FormulaParseError(
                f"unexpected trailing input {final.value!r}",
                source=self._source,
                position=final.position,
            )
        return node

    def _parse_expr(self) -> Node:
        return self._parse_comparison()

    def _parse_comparison(self) -> Node:
        left = self._parse_concat()
        while True:
            tok = self._peek()
            if tok.kind is TokenKind.OP and tok.value in _COMPARISON_OPS:
                self._advance()
                right = self._parse_concat()
                left = BinaryOp(tok.value, left, right)
            else:
                return left

    def _parse_concat(self) -> Node:
        left = self._parse_add()
        while True:
            tok = self._peek()
            if tok.kind is TokenKind.OP and tok.value == "&":
                self._advance()
                right = self._parse_add()
                left = BinaryOp("&", left, right)
            else:
                return left

    def _parse_add(self) -> Node:
        left = self._parse_mul()
        while True:
            tok = self._peek()
            if tok.kind is TokenKind.OP and tok.value in _ADD_OPS:
                self._advance()
                right = self._parse_mul()
                left = BinaryOp(tok.value, left, right)
            else:
                return left

    def _parse_mul(self) -> Node:
        left = self._parse_pow()
        while True:
            tok = self._peek()
            if tok.kind is TokenKind.OP and tok.value in _MUL_OPS:
                self._advance()
                right = self._parse_pow()
                left = BinaryOp(tok.value, left, right)
            else:
                return left

    def _parse_pow(self) -> Node:
        left = self._parse_unary()
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value == "^":
            self._advance()
            # Right-associative: recurse to parse the full RHS chain.
            right = self._parse_pow()
            return BinaryOp("^", left, right)
        return left

    def _parse_unary(self) -> Node:
        tok = self._peek()
        if tok.kind is TokenKind.OP and tok.value in {"+", "-"}:
            self._advance()
            operand = self._parse_unary()
            return UnaryOp(tok.value, operand)
        return self._parse_primary()

    def _parse_primary(self) -> Node:
        tok = self._peek()
        if tok.kind is TokenKind.NUMBER:
            self._advance()
            return NumberLiteral(float(tok.value))
        if tok.kind is TokenKind.STRING:
            self._advance()
            return StringLiteral(tok.value)
        if tok.kind is TokenKind.LPAREN:
            self._advance()
            node = self._parse_expr()
            self._expect(TokenKind.RPAREN)
            return node
        if tok.kind is TokenKind.IDENT:
            return self._parse_ident_prefixed()
        raise FormulaParseError(
            f"unexpected token {tok.value!r}", source=self._source, position=tok.position
        )

    # ----------------------------------------------------------------- cell refs

    def _parse_ident_prefixed(self) -> Node:
        """Parse an identifier-prefixed primary.

        Could be a boolean literal (``TRUE`` / ``FALSE``), a function call
        (``IDENT '(' ...``), or a cell reference (everything else, possibly
        with ``Sheet.N!`` prefix and ``.`` or ``!`` qualifiers).
        """
        first = self._peek()
        upper = first.value.upper()
        if upper == "TRUE" and self._peek(1).kind is not TokenKind.LPAREN:
            self._advance()
            return BoolLiteral(True)
        if upper == "FALSE" and self._peek(1).kind is not TokenKind.LPAREN:
            self._advance()
            return BoolLiteral(False)

        # Function call: IDENT '(' ...
        if self._peek(1).kind is TokenKind.LPAREN:
            return self._parse_function_call()

        return self._parse_cell_ref()

    def _parse_function_call(self) -> Node:
        name_tok = self._advance()
        self._expect(TokenKind.LPAREN)
        args: list[Node] = []
        if self._peek().kind is not TokenKind.RPAREN:
            args.append(self._parse_expr())
            while self._peek().kind is TokenKind.COMMA:
                self._advance()
                args.append(self._parse_expr())
        self._expect(TokenKind.RPAREN)
        return FunctionCall(name_tok.value.upper(), tuple(args))

    def _parse_cell_ref(self) -> Node:
        start_pos = self._peek().position
        source_start = start_pos

        first = self._advance()
        parts: list[str] = [first.value]

        # Optional sheet qualifier: IDENT '!' ...
        sheet: Optional[str] = None
        if self._peek().kind is TokenKind.DOT and self._peek(1).kind is TokenKind.NUMBER:
            # Sheet.5 form — consume '.NUMBER'
            self._advance()
            num_tok = self._advance()
            parts.append(".")
            parts.append(num_tok.value)
            # Expect BANG next.
            if self._peek().kind is TokenKind.BANG:
                self._advance()
                sheet = f"{first.value}.{num_tok.value}"
                parts.append("!")
                # Rebuild parts as new ref scope.
                first_after_bang = self._advance()
                parts.append(first_after_bang.value)
                first = first_after_bang
                ref_parts: list[str] = [first_after_bang.value]
            else:
                # Unclear — rollback-style: treat "Foo.5" as a syntax error.
                raise FormulaParseError(
                    "expected '!' after Sheet.N qualifier",
                    source=self._source,
                    position=self._peek().position,
                )
        elif self._peek().kind is TokenKind.BANG:
            # Named-sheet form: ShapeName!Cell
            self._advance()
            sheet = first.value
            parts.append("!")
            first_after_bang = self._advance()
            parts.append(first_after_bang.value)
            first = first_after_bang
            ref_parts = [first_after_bang.value]
        else:
            ref_parts = [first.value]

        # Now read dotted qualifiers on the local cell reference. We
        # consume ``.<IDENT>`` pairs greedily; also support ``.<NUMBER>``
        # for indexed row qualifiers like ``Geometry1.1``.
        while self._peek().kind is TokenKind.DOT:
            # Peek the next token — if it's not a name-like thing, stop.
            nxt = self._peek(1)
            if nxt.kind not in {TokenKind.IDENT, TokenKind.NUMBER}:
                break
            self._advance()  # consume dot
            name_tok = self._advance()
            ref_parts.append(name_tok.value)
            parts.append(".")
            parts.append(name_tok.value)

        source_text = "".join(parts) if not sheet else self._source[source_start : self._peek().position]

        return self._finish_cell_ref(ref_parts, sheet, source_text)

    def _finish_cell_ref(
        self, parts: list[str], sheet: Optional[str], source_text: str
    ) -> CellRef:
        """Classify the parsed dotted parts into section/row/name axes.

        The rules (cross-verified with MS Learn cell-reference docs + the
        reference ``vsdx`` Python library):

        - ``Width`` — 1 part → singleton cell named "Width".
        - ``User.Scale`` — 2 parts → section=User, row=Scale, name=Value.
        - ``Prop.Foo.Prompt`` — 3 parts, last is an implicit cell name.
        - ``Geometry1.X1`` — 2 parts; the second part starts with a cell
          letter → section=Geometry1, row=None, name=X1. Handled as a
          2-part fall-through because we can't reliably distinguish
          ``User.X1`` (row) from ``Geometry1.X1`` (cell) at parse time;
          the evaluator's ``ShapeSheetContext`` does the final resolution.
        """
        if len(parts) == 1:
            return CellRef(name=parts[0], sheet=sheet, source=source_text)
        if len(parts) == 2:
            section, second = parts
            if second in _IMPLICIT_CELL_NAMES:
                # e.g. ``User.Value`` — a section-level default name.
                return CellRef(
                    name=second, section=section, sheet=sheet, source=source_text
                )
            # Two-part refs default to section+row, name "Value" for
            # user/prop/scratch-style sections. Geometry sections have a
            # different shape (section.cellname) but the context resolver
            # handles both spellings.
            return CellRef(
                name=second, section=section, row=None, sheet=sheet, source=source_text
            )
        if len(parts) == 3:
            section, row, name = parts
            return CellRef(
                name=name, section=section, row=row, sheet=sheet, source=source_text
            )
        # ≥4 parts is unusual but not necessarily invalid — Visio sometimes
        # emits nested group-shape refs. Fold everything between the first
        # and last into ``row``.
        section = parts[0]
        name = parts[-1]
        row = ".".join(parts[1:-1])
        return CellRef(name=name, section=section, row=row, sheet=sheet, source=source_text)


def parse(source: str) -> Node:
    """Parse ``source`` (a formula string) into an AST.

    ``source`` may include a leading ``=`` (Excel-style) which is stripped
    for compatibility with ``dave-howard/vsdx`` output.
    """
    if not isinstance(source, str):
        raise FormulaParseError("formula source must be a string")
    text = source.strip()
    if text.startswith("="):
        text = text[1:].lstrip()
    tokens = tokenize(text)
    parser = Parser(tokens, source=text)
    return parser.parse()
