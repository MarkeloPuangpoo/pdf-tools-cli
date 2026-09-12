"""Property-based testing and fuzzing for page range parser using Hypothesis."""

from __future__ import annotations

import contextlib

from hypothesis import given, settings
from hypothesis import strategies as st

from pdftoolscli.domain.errors import PageBoundsError, RangeSyntaxError
from pdftoolscli.domain.ranges import parse_range, resolve_range

# Strategy for valid single indices
index_strategy = st.one_of(
    st.integers(min_value=1, max_value=100).map(str),
    st.just("last"),
)

# Strategy for valid terms
term_strategy = st.one_of(
    index_strategy,
    st.tuples(index_strategy, index_strategy).map(lambda pair: f"{pair[0]}-{pair[1]}"),
    st.sampled_from(["all", "odd", "even"]),
)

# Strategy for valid range expressions
valid_range_strategy = st.lists(term_strategy, min_size=1, max_size=10).map(
    lambda terms: ",".join(terms)
)


@given(valid_range_strategy)
@settings(max_examples=100)
def test_valid_ranges_roundtrip(expr: str) -> None:
    ast = parse_range(expr)
    formatted = ast.format()
    # Formatting canonical AST and parsing again must yield the exact same format
    ast2 = parse_range(formatted)
    assert ast2.format() == formatted


@given(valid_range_strategy, st.integers(min_value=1, max_value=50))
@settings(max_examples=100)
def test_resolve_sequence_valid_bounds(expr: str, page_count: int) -> None:
    try:
        pages = resolve_range(expr, page_count=page_count, context="sequence")
        # Every resolved page must be within 1..page_count
        assert all(1 <= p <= page_count for p in pages)
    except PageBoundsError:
        # Out-of-bounds pages are expected and should be typed PageBoundsError
        pass


@given(st.text())
@settings(max_examples=200)
def test_fuzz_parser_never_crashes_unexpectedly(raw_input: str) -> None:
    with contextlib.suppress(RangeSyntaxError):
        parse_range(raw_input)
