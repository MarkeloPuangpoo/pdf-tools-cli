"""Tests for storage/naming.py conforming to PLAN.md §14, §18, §29."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdftoolscli.domain.errors import FileSafetyError
from pdftoolscli.storage.naming import (
    CollisionTracker,
    assert_not_nested,
    default_batch_output_name,
    normalize_name_for_comparison,
    render_template,
    sanitize_filename,
    validate_safe_filename,
)


def test_validate_safe_filename_valid() -> None:
    validate_safe_filename("document.pdf")
    validate_safe_filename("my-file_01.txt")
    validate_safe_filename("รายงานประจำปี2026.pdf")


def test_validate_safe_filename_invalid() -> None:
    # Empty or whitespace
    with pytest.raises(FileSafetyError):
        validate_safe_filename("")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("   ")

    # Directory components
    with pytest.raises(FileSafetyError):
        validate_safe_filename(".")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("..")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("sub/file.pdf")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("sub\\file.pdf")

    # Forbidden characters
    with pytest.raises(FileSafetyError):
        validate_safe_filename("doc:1.pdf")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("test*.pdf")

    # Trailing dot or space
    with pytest.raises(FileSafetyError):
        validate_safe_filename("doc.pdf.")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("doc.pdf ")

    # Reserved DOS names
    with pytest.raises(FileSafetyError):
        validate_safe_filename("CON.pdf")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("nul")
    with pytest.raises(FileSafetyError):
        validate_safe_filename("aux.txt")


def test_sanitize_filename() -> None:
    assert sanitize_filename("my/unsafe:doc?.pdf") == "my_unsafe_doc_.pdf"
    assert sanitize_filename("CON.pdf") == "file_CON.pdf"
    assert sanitize_filename("   ") == "unnamed"
    assert sanitize_filename("...test...") == "test"


def test_assert_not_nested(tmp_path: Path) -> None:
    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()

    # Disjoint directories are valid
    assert_not_nested(in_dir, out_dir)

    # Identical directory
    with pytest.raises(FileSafetyError):
        assert_not_nested(in_dir, in_dir)

    # Output nested in input
    nested_out = in_dir / "sub_out"
    nested_out.mkdir()
    with pytest.raises(FileSafetyError):
        assert_not_nested(in_dir, nested_out)

    # Input nested in output
    nested_in = out_dir / "sub_in"
    nested_in.mkdir()
    with pytest.raises(FileSafetyError):
        assert_not_nested(nested_in, out_dir)


def test_render_template() -> None:
    rendered = render_template(
        "{relparent}/{stem}-p{page:04d}.{ext}",
        stem="report",
        page=3,
        ext="pdf",
        relparent="sub/dir",
    )
    assert rendered == "sub/dir/report-p0003.pdf"

    rendered_simple = render_template(
        "{stem}-{index:02d}.{ext}",
        stem="scan",
        index=1,
        ext="jpg",
    )
    assert rendered_simple == "scan-01.jpg"

    # Traversal in template rejected
    with pytest.raises(FileSafetyError):
        render_template("../{stem}.pdf", stem="test")

    # Forbidden token rejected
    with pytest.raises(FileSafetyError):
        render_template("{secret}-{stem}.pdf", stem="test")


def test_default_batch_output_name() -> None:
    name = default_batch_output_name("annual_report", "optimize")
    assert name == "annual_report-optimize.pdf"

    name_txt = default_batch_output_name("invoices", "extract", ext=".txt")
    assert name_txt == "invoices-extract.txt"


def test_collision_tracker(tmp_path: Path) -> None:
    tracker = CollisionTracker()
    p1 = tmp_path / "output.pdf"
    p2 = tmp_path / "other.pdf"
    p1_case = tmp_path / "OUTPUT.PDF"

    tracker.register(p1)
    tracker.register(p2)

    # Case collision detected
    with pytest.raises(FileSafetyError):
        tracker.register(p1_case)


def test_normalize_name_for_comparison() -> None:
    assert normalize_name_for_comparison("FILE.PDF") == normalize_name_for_comparison("file.pdf")
