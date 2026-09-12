"""EBNF Page Range Parser, AST, and Resolvers conforming to PLAN.md §13."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pdftoolscli.domain.errors import PageBoundsError, RangeSyntaxError

# Hard limits defined in PLAN.md §13
MAX_EXPRESSION_BYTES = 64 * 1024  # 64 KiB
MAX_TERMS = 4096
MAX_RESOLVED_REFERENCES = 1_000_000


@dataclass(frozen=True)
class SourceSpan:
    """Represents the location of a token or term in the source expression."""

    start: int
    end: int
    line: int = 1
    column: int = 1


class TokenType(Enum):
    NUMBER = "NUMBER"
    KEYWORD = "KEYWORD"
    COMMA = "COMMA"
    HYPHEN = "HYPHEN"
    EOF = "EOF"


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str
    span: SourceSpan


class Lexer:
    """Lexer strictly conforming to PLAN.md §13 EBNF grammar."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.length = len(text)
        self.line = 1
        self.col = 1

    def _advance(self) -> str:
        ch = self.text[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def next_token(self) -> Token:
        # Skip whitespace
        while self.pos < self.length and self.text[self.pos] in " \t\r\n":
            self._advance()

        if self.pos >= self.length:
            return Token(TokenType.EOF, "", SourceSpan(self.pos, self.pos, self.line, self.col))

        start_pos = self.pos
        start_line = self.line
        start_col = self.col
        ch = self.text[self.pos]

        if ch == ",":
            self._advance()
            return Token(
                TokenType.COMMA,
                ",",
                SourceSpan(start_pos, self.pos, start_line, start_col),
            )

        if ch == "-":
            self._advance()
            return Token(
                TokenType.HYPHEN,
                "-",
                SourceSpan(start_pos, self.pos, start_line, start_col),
            )

        # Check for numbers: positive_integer = nonzero_digit, { digit }
        if "0" <= ch <= "9":
            if ch == "0":
                # Disallow leading zero / zero
                self._advance()
                raise RangeSyntaxError(
                    "Page indices must be positive integers starting from 1 "
                    "(leading zeros and 0 are invalid)",
                    offset=start_pos,
                    line=start_line,
                    column=start_col,
                )

            digits = []
            while self.pos < self.length and "0" <= self.text[self.pos] <= "9":
                digits.append(self._advance())

            # Check if there is space inside a number followed by more digits, e.g. "1 2"
            if self.pos < self.length and self.text[self.pos] in " \t":
                # Peek past whitespace
                peek_pos = self.pos
                while peek_pos < self.length and self.text[peek_pos] in " \t":
                    peek_pos += 1
                if peek_pos < self.length and "0" <= self.text[peek_pos] <= "9":
                    raise RangeSyntaxError(
                        "Whitespace inside numbers is rejected",
                        offset=self.pos,
                        line=self.line,
                        column=self.col,
                    )

            val = "".join(digits)
            return Token(
                TokenType.NUMBER,
                val,
                SourceSpan(start_pos, self.pos, start_line, start_col),
            )

        # Check for alphabetic keywords: last, all, odd, even
        if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            letters = []
            while self.pos < self.length and (
                ("a" <= self.text[self.pos] <= "z") or ("A" <= self.text[self.pos] <= "Z")
            ):
                letters.append(self._advance())
            word = "".join(letters)
            if word in ("last", "all", "odd", "even"):
                return Token(
                    TokenType.KEYWORD,
                    word,
                    SourceSpan(start_pos, self.pos, start_line, start_col),
                )
            raise RangeSyntaxError(
                f"Unknown keyword or identifier '{word}'; expected 'last', 'all', 'odd', or 'even'",
                offset=start_pos,
                line=start_line,
                column=start_col,
            )

        # Invalid character
        self._advance()
        raise RangeSyntaxError(
            f"Unexpected character '{ch}' in page range expression",
            offset=start_pos,
            line=start_line,
            column=start_col,
        )


# --- AST Nodes ---


@dataclass(frozen=True)
class IndexNode:
    """Represents a single index: positive integer or 'last'."""

    value: int | Literal["last"]
    span: SourceSpan


@dataclass(frozen=True)
class SingleIndexTerm:
    """Represents a term that is a single index."""

    index: IndexNode
    span: SourceSpan


@dataclass(frozen=True)
class RangeTerm:
    """Represents a range term: start - end."""

    start: IndexNode
    end: IndexNode
    span: SourceSpan


@dataclass(frozen=True)
class KeywordTerm:
    """Represents a keyword term: 'all', 'odd', or 'even'."""

    keyword: Literal["all", "odd", "even"]
    span: SourceSpan


TermNode = SingleIndexTerm | RangeTerm | KeywordTerm


@dataclass(frozen=True)
class RangeAST:
    """AST representation of a parsed page range expression."""

    terms: list[TermNode]
    raw_expression: str

    def format(self) -> str:
        """Serialize AST back to canonical page range expression string."""
        parts: list[str] = []
        for term in self.terms:
            if isinstance(term, SingleIndexTerm):
                parts.append(str(term.index.value))
            elif isinstance(term, RangeTerm):
                parts.append(f"{term.start.value}-{term.end.value}")
            elif isinstance(term, KeywordTerm):
                parts.append(term.keyword)
        return ",".join(parts)


class Parser:
    """Recursive descent parser strictly conforming to §13 EBNF grammar."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.lexer = Lexer(text)
        self.current_token: Token = self.lexer.next_token()

    def _peek(self) -> Token:
        return self.current_token

    def _consume(self, expected_type: TokenType | None = None) -> Token:
        token = self.current_token
        if expected_type is not None and token.type != expected_type:
            raise RangeSyntaxError(
                f"Expected {expected_type.value}, found {token.type.value} ('{token.value}')",
                offset=token.span.start,
                line=token.span.line,
                column=token.span.column,
            )
        self.current_token = self.lexer.next_token()
        return token

    def parse(self) -> RangeAST:
        # Check overall length in UTF-8 bytes
        encoded = self.text.encode("utf-8")
        if len(encoded) > MAX_EXPRESSION_BYTES:
            raise RangeSyntaxError(
                f"Page range expression exceeds maximum size of {MAX_EXPRESSION_BYTES} bytes",
                offset=0,
            )

        if self._peek().type == TokenType.EOF:
            raise RangeSyntaxError(
                "Page range expression cannot be empty",
                offset=0,
            )

        terms: list[TermNode] = []
        terms.append(self._parse_term())

        while self._peek().type == TokenType.COMMA:
            comma_token = self._consume(TokenType.COMMA)
            if self._peek().type == TokenType.EOF:
                raise RangeSyntaxError(
                    "Trailing comma is not permitted in page range",
                    offset=comma_token.span.start,
                    line=comma_token.span.line,
                    column=comma_token.span.column,
                )
            if self._peek().type == TokenType.COMMA:
                raise RangeSyntaxError(
                    "Empty term between consecutive commas is not permitted",
                    offset=self._peek().span.start,
                    line=self._peek().span.line,
                    column=self._peek().span.column,
                )
            terms.append(self._parse_term())

            if len(terms) > MAX_TERMS:
                raise RangeSyntaxError(
                    f"Page range expression exceeds maximum limit of {MAX_TERMS} terms",
                    offset=comma_token.span.start,
                    line=comma_token.span.line,
                    column=comma_token.span.column,
                )

        if self._peek().type != TokenType.EOF:
            tok = self._peek()
            raise RangeSyntaxError(
                f"Unexpected token '{tok.value}' after valid range terms",
                offset=tok.span.start,
                line=tok.span.line,
                column=tok.span.column,
            )

        return RangeAST(terms=terms, raw_expression=self.text)

    def _parse_term(self) -> TermNode:
        tok = self._peek()
        if tok.type == TokenType.KEYWORD:
            if tok.value in ("all", "odd", "even"):
                self._consume(TokenType.KEYWORD)
                return KeywordTerm(
                    keyword=tok.value,  # type: ignore[arg-type]
                    span=tok.span,
                )
            if tok.value == "last":
                index = self._parse_index()
                if self._peek().type == TokenType.HYPHEN:
                    self._consume(TokenType.HYPHEN)
                    end_index = self._parse_index()
                    span = SourceSpan(
                        index.span.start,
                        end_index.span.end,
                        index.span.line,
                        index.span.column,
                    )
                    return RangeTerm(start=index, end=end_index, span=span)
                return SingleIndexTerm(index=index, span=index.span)

        if tok.type == TokenType.NUMBER:
            start_index = self._parse_index()
            if self._peek().type == TokenType.HYPHEN:
                self._consume(TokenType.HYPHEN)
                end_index = self._parse_index()
                span = SourceSpan(
                    start_index.span.start,
                    end_index.span.end,
                    start_index.span.line,
                    start_index.span.column,
                )
                return RangeTerm(start=start_index, end=end_index, span=span)
            return SingleIndexTerm(index=start_index, span=start_index.span)

        raise RangeSyntaxError(
            f"Expected page index or keyword ('all', 'odd', 'even', 'last'), found '{tok.value}'",
            offset=tok.span.start,
            line=tok.span.line,
            column=tok.span.column,
        )

    def _parse_index(self) -> IndexNode:
        tok = self._peek()
        if tok.type == TokenType.NUMBER:
            self._consume(TokenType.NUMBER)
            return IndexNode(value=int(tok.value), span=tok.span)
        if tok.type == TokenType.KEYWORD and tok.value == "last":
            self._consume(TokenType.KEYWORD)
            return IndexNode(value="last", span=tok.span)
        raise RangeSyntaxError(
            f"Expected positive integer or 'last', found '{tok.value}'",
            offset=tok.span.start,
            line=tok.span.line,
            column=tok.span.column,
        )


def parse_range(expression: str) -> RangeAST:
    """Parse a page range expression string into an AST without opening files."""
    return Parser(expression).parse()


ResolveContext = Literal["sequence", "selection", "permutation"]


def resolve_range(
    expression_or_ast: str | RangeAST,
    page_count: int,
    context: ResolveContext = "sequence",
    input_id: str | None = None,
) -> list[int]:
    """Resolve a page range expression or AST against a specific page count.

    Contexts:
      - 'sequence': preserves resolved order and duplicates.
      - 'selection': returns unique sorted ascending indices.
      - 'permutation': strict 1-to-1 bijection of 1..page_count.
    """
    if isinstance(expression_or_ast, str):
        ast = parse_range(expression_or_ast)
    else:
        ast = expression_or_ast

    if page_count < 0:
        raise ValueError("page_count must be non-negative")

    resolved_indices: list[int] = []

    def resolve_index(node: IndexNode) -> int:
        if node.value == "last":
            if page_count == 0:
                raise PageBoundsError(
                    "Cannot resolve 'last' on a document with 0 pages",
                    page=None,
                    page_count=page_count,
                    input_id=input_id,
                )
            return page_count
        idx = node.value
        if page_count == 0 or idx < 1 or idx > page_count:
            raise PageBoundsError(
                f"Page {idx} does not exist (document has {page_count} pages)",
                page=idx,
                page_count=page_count,
                input_id=input_id,
            )
        return idx

    for term in ast.terms:
        if isinstance(term, SingleIndexTerm):
            resolved_indices.append(resolve_index(term.index))
        elif isinstance(term, RangeTerm):
            start = resolve_index(term.start)
            end = resolve_index(term.end)
            if start <= end:
                resolved_indices.extend(range(start, end + 1))
            else:
                # Descending range: e.g. 5-2 -> 5, 4, 3, 2
                resolved_indices.extend(range(start, end - 1, -1))
        elif isinstance(term, KeywordTerm):
            if term.keyword == "all":
                resolved_indices.extend(range(1, page_count + 1))
            elif term.keyword == "odd":
                resolved_indices.extend([p for p in range(1, page_count + 1) if p % 2 != 0])
            elif term.keyword == "even":
                resolved_indices.extend([p for p in range(1, page_count + 1) if p % 2 == 0])

        if len(resolved_indices) > MAX_RESOLVED_REFERENCES:
            raise PageBoundsError(
                f"Resolved page count exceeds maximum reference limit of {MAX_RESOLVED_REFERENCES}",
                page_count=page_count,
                input_id=input_id,
            )

    # Apply context semantics
    if context == "sequence":
        return resolved_indices

    if context == "selection":
        return sorted(set(resolved_indices))

    if context == "permutation":
        if len(resolved_indices) != page_count:
            raise PageBoundsError(
                f"Permutation requires exactly all {page_count} pages once, "
                f"but got {len(resolved_indices)} pages",
                page_count=page_count,
                input_id=input_id,
                hint="Ensure all pages from 1 to total pages are specified exactly once.",
            )
        counts: dict[int, int] = {}
        for p in resolved_indices:
            counts[p] = counts.get(p, 0) + 1
        duplicates = [p for p, c in counts.items() if c > 1]
        if duplicates:
            raise PageBoundsError(
                f"Permutation contains duplicate pages: {duplicates}",
                page=duplicates[0],
                page_count=page_count,
                input_id=input_id,
            )
        missing = [p for p in range(1, page_count + 1) if p not in counts]
        if missing:
            raise PageBoundsError(
                f"Permutation is missing pages: {missing}",
                page=missing[0],
                page_count=page_count,
                input_id=input_id,
            )
        return resolved_indices

    raise ValueError(f"Unknown context: {context}")
