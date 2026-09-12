"""Unit tests for EBNF page range grammar parser, AST, and resolvers."""

from __future__ import annotations

import pytest

from pdftoolscli.domain.errors import PageBoundsError, RangeSyntaxError
from pdftoolscli.domain.ranges import (
    KeywordTerm,
    RangeTerm,
    SingleIndexTerm,
    parse_range,
    resolve_range,
)


def test_parse_single_index() -> None:
    ast = parse_range("5")
    assert len(ast.terms) == 1
    term = ast.terms[0]
    assert isinstance(term, SingleIndexTerm)
    assert term.index.value == 5
    assert ast.format() == "5"


def test_parse_last_keyword() -> None:
    ast = parse_range("last")
    assert len(ast.terms) == 1
    term = ast.terms[0]
    assert isinstance(term, SingleIndexTerm)
    assert term.index.value == "last"
    assert ast.format() == "last"


def test_parse_range_term() -> None:
    ast = parse_range("1-5")
    assert len(ast.terms) == 1
    term = ast.terms[0]
    assert isinstance(term, RangeTerm)
    assert term.start.value == 1
    assert term.end.value == 5
    assert ast.format() == "1-5"


def test_parse_keywords() -> None:
    for kw in ("all", "odd", "even"):
        ast = parse_range(kw)
        assert len(ast.terms) == 1
        term = ast.terms[0]
        assert isinstance(term, KeywordTerm)
        assert term.keyword == kw
        assert ast.format() == kw


def test_parse_composite_expression_with_whitespace() -> None:
    ast = parse_range(" 1 - 3 , 5 , 8 - last , odd ")
    assert len(ast.terms) == 4
    assert isinstance(ast.terms[0], RangeTerm)
    assert isinstance(ast.terms[1], SingleIndexTerm)
    assert isinstance(ast.terms[2], RangeTerm)
    assert isinstance(ast.terms[3], KeywordTerm)
    assert ast.format() == "1-3,5,8-last,odd"


@pytest.mark.parametrize(
    ("invalid_expr", "expected_msg"),
    [
        ("", "cannot be empty"),
        ("   ", "cannot be empty"),
        ("0", "leading zeros and 0 are invalid"),
        ("01", "leading zeros and 0 are invalid"),
        ("-5", "found '-'"),
        ("+1", "Unexpected character '+'"),
        ("1 2", "Whitespace inside numbers is rejected"),
        ("1,", "Trailing comma is not permitted"),
        (",1", "Expected page index or keyword"),
        ("1,,2", "Empty term between consecutive commas"),
        ("1-", "Expected positive integer or 'last'"),
        ("1-5-9", "Unexpected token '-'"),
        ("ALL", "Unknown keyword or identifier 'ALL'"),
        ("LAST", "Unknown keyword or identifier 'LAST'"),
        ("evenn", "Unknown keyword or identifier 'evenn'"),
        ("1,abc", "Unknown keyword or identifier 'abc'"),
        ("1;2", "Unexpected character ';'"),
    ],
)
def test_parse_syntax_errors(invalid_expr: str, expected_msg: str) -> None:
    with pytest.raises(RangeSyntaxError) as exc_info:
        parse_range(invalid_expr)
    assert expected_msg in str(exc_info.value)
    assert exc_info.value.code == "E_PAGE_BOUNDS"
    assert exc_info.value.exit_code == 2


def test_resolve_sequence() -> None:
    # Preserves duplicates and order
    res = resolve_range("3, 1, 3, 2-4", page_count=5, context="sequence")
    assert res == [3, 1, 3, 2, 3, 4]


def test_resolve_selection() -> None:
    # Sorted and unique
    res = resolve_range("3, 1, 3, 2-4", page_count=5, context="selection")
    assert res == [1, 2, 3, 4]


def test_resolve_descending_range() -> None:
    # Descending 5-2 resolves 5, 4, 3, 2
    res = resolve_range("5-2", page_count=5, context="sequence")
    assert res == [5, 4, 3, 2]


def test_resolve_last_descending() -> None:
    # last-1 means descending last through 1
    res = resolve_range("last-1", page_count=4, context="sequence")
    assert res == [4, 3, 2, 1]


def test_resolve_keywords() -> None:
    assert resolve_range("all", page_count=3) == [1, 2, 3]
    assert resolve_range("odd", page_count=5) == [1, 3, 5]
    assert resolve_range("even", page_count=5) == [2, 4]
    assert resolve_range("all", page_count=0) == []
    assert resolve_range("even", page_count=1) == []


def test_resolve_permutation() -> None:
    # Valid permutation
    res = resolve_range("3,1,2", page_count=3, context="permutation")
    assert res == [3, 1, 2]

    # Missing page (wrong count)
    with pytest.raises(PageBoundsError) as exc_info:
        resolve_range("1,2", page_count=3, context="permutation")
    assert "requires exactly all 3 pages once" in str(exc_info.value).lower()

    # Duplicate page
    with pytest.raises(PageBoundsError) as exc_info:
        resolve_range("1,2,2", page_count=3, context="permutation")
    assert "duplicate" in str(exc_info.value).lower()


def test_resolve_out_of_bounds() -> None:
    with pytest.raises(PageBoundsError) as exc_info:
        resolve_range("6", page_count=5)
    assert "Page 6 does not exist" in str(exc_info.value)
    assert exc_info.value.exit_code == 2

    with pytest.raises(PageBoundsError) as exc_info:
        resolve_range("last", page_count=0)
    assert "Cannot resolve 'last' on a document with 0 pages" in str(exc_info.value)


def test_limit_expression_size() -> None:
    large_expr = "1," * 33000 + "1"
    with pytest.raises(RangeSyntaxError) as exc_info:
        parse_range(large_expr)
    assert "exceeds maximum size" in str(exc_info.value)


def test_limit_terms() -> None:
    expr = ",".join(["1"] * 4097)
    with pytest.raises(RangeSyntaxError) as exc_info:
        parse_range(expr)
    assert "exceeds maximum limit of 4096 terms" in str(exc_info.value)


def test_parse_with_newlines() -> None:
    ast = parse_range("1,\n2")
    assert len(ast.terms) == 2
    assert resolve_range(ast, 2) == [1, 2]


def test_resolve_invalid_context_or_page_count() -> None:
    with pytest.raises(ValueError, match="page_count must be non-negative"):
        resolve_range("1", page_count=-1)

    with pytest.raises(ValueError, match="Unknown context: invalid"):
        resolve_range("1", page_count=5, context="invalid")  # type: ignore[arg-type]


def test_resolve_permutation_duplicate_same_length() -> None:
    with pytest.raises(PageBoundsError) as exc_info:
        resolve_range("1,1,3", page_count=3, context="permutation")
    assert "duplicate" in str(exc_info.value).lower()


def test_resolve_max_resolved_references_limit() -> None:
    # 1000 * 1001 resolved pages > 1_000_000
    expr = ",".join(["1-1001"] * 1000)
    with pytest.raises(PageBoundsError) as exc_info:
        resolve_range(expr, page_count=2000)
    assert "exceeds maximum reference limit" in str(exc_info.value)
