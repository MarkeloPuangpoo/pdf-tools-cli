"""Comprehensive CLI and subprocess tests for core page operations (CMD-002).

Tests C09 (split), C10 (pages extract), C11 (pages remove),
C12 (pages reorder), C13 (pages reverse), and C14 (pages rotate).
"""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def multi_page_pdf(tmp_path: Path) -> Path:
    """Create a standard 5-page PDF fixture."""
    pdf_path = tmp_path / "multi5.pdf"
    pdf = pikepdf.new()
    for _ in range(5):
        pdf.add_blank_page()
    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


@pytest.fixture
def sample_pdf_with_bookmarks(tmp_path: Path) -> Path:
    """Create a 3-page PDF with bookmarks."""
    pdf_path = tmp_path / "bookmarked.pdf"
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page()
    with pdf.open_outline() as outline:
        outline.root.append(pikepdf.OutlineItem("Chapter 1", 0))
        outline.root.append(pikepdf.OutlineItem("Chapter 2", 1))
        outline.root.append(pikepdf.OutlineItem("Chapter 3", 2))
    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


def test_split_default_every_1(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "split_parts"
    res = runner.invoke(cli, ["split", str(multi_page_pdf), "--output-dir", str(out_dir)])
    assert res.exit_code == 0
    assert "Successfully split" in res.output

    # Verify 5 files were generated
    parts = sorted(out_dir.glob("*.pdf"))
    assert len(parts) == 5
    assert parts[0].name == "multi5-part-0001.pdf"
    assert parts[4].name == "multi5-part-0005.pdf"

    # Verify each part has 1 page
    with pikepdf.open(parts[0]) as p:
        assert len(p.pages) == 1


def test_split_every_n(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "split_every2"
    res = runner.invoke(
        cli, ["split", str(multi_page_pdf), "--output-dir", str(out_dir), "--every", "2"]
    )
    assert res.exit_code == 0

    parts = sorted(out_dir.glob("*.pdf"))
    assert len(parts) == 3  # 2 + 2 + 1 = 5
    with pikepdf.open(parts[0]) as p:
        assert len(p.pages) == 2
    with pikepdf.open(parts[2]) as p:
        assert len(p.pages) == 1  # short last part


def test_split_ranges(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "split_ranges"
    res = runner.invoke(
        cli,
        [
            "split",
            str(multi_page_pdf),
            "--output-dir",
            str(out_dir),
            "--ranges",
            "1-2;3-last",
        ],
    )
    assert res.exit_code == 0

    parts = sorted(out_dir.glob("*.pdf"))
    assert len(parts) == 2
    with pikepdf.open(parts[0]) as p:
        assert len(p.pages) == 2
    with pikepdf.open(parts[1]) as p:
        assert len(p.pages) == 3


def test_split_json_mode(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "split_json"
    res = runner.invoke(
        cli,
        ["--json", "split", str(multi_page_pdf), "--output-dir", str(out_dir), "--every", "3"],
    )
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "success"
    assert data["data"]["total_parts"] == 2
    assert len(data["data"]["parts"]) == 2


def test_split_invalid_options(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "split_err"

    # Both --every and --ranges
    res = runner.invoke(
        cli,
        [
            "split",
            str(multi_page_pdf),
            "--output-dir",
            str(out_dir),
            "--every",
            "2",
            "--ranges",
            "1-2",
        ],
    )
    assert res.exit_code == 2

    # Negative or zero --every
    res2 = runner.invoke(
        cli,
        ["split", str(multi_page_pdf), "--output-dir", str(out_dir), "--every", "0"],
    )
    assert res2.exit_code == 2


def test_pages_extract_sequence(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "extracted.pdf"
    # Extract with repetitions and non-trivial order
    res = runner.invoke(
        cli,
        ["pages", "extract", str(multi_page_pdf), "4,2,4,1", "-o", str(out_pdf)],
    )
    assert res.exit_code == 0
    assert "Extracted 4 pages" in res.output

    with pikepdf.open(out_pdf) as p:
        assert len(p.pages) == 4


def test_pages_extract_out_of_bounds(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "out_bounds.pdf"
    res = runner.invoke(
        cli,
        ["pages", "extract", str(multi_page_pdf), "1,99", "-o", str(out_pdf)],
    )
    assert res.exit_code == 2


def test_pages_remove_pages(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "survivors.pdf"
    res = runner.invoke(
        cli,
        ["pages", "remove", str(multi_page_pdf), "2,4", "-o", str(out_pdf)],
    )
    assert res.exit_code == 0
    assert "Removed 2 pages" in res.output

    with pikepdf.open(out_pdf) as p:
        assert len(p.pages) == 3


def test_pages_remove_all_pages_fails(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "empty.pdf"
    res = runner.invoke(
        cli,
        ["pages", "remove", str(multi_page_pdf), "1-5", "-o", str(out_pdf)],
    )
    assert res.exit_code == 2


def test_pages_reorder_valid(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "reordered.pdf"
    res = runner.invoke(
        cli,
        ["pages", "reorder", str(multi_page_pdf), "5,4,3,2,1", "-o", str(out_pdf)],
    )
    assert res.exit_code == 0

    with pikepdf.open(out_pdf) as p:
        assert len(p.pages) == 5


def test_pages_reorder_missing_or_duplicate_fails(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "invalid_reorder.pdf"

    # Missing page 5
    res = runner.invoke(
        cli,
        ["pages", "reorder", str(multi_page_pdf), "1,2,3,4", "-o", str(out_pdf)],
    )
    assert res.exit_code == 2

    # Duplicate page 1
    res2 = runner.invoke(
        cli,
        ["pages", "reorder", str(multi_page_pdf), "1,1,2,3,4", "-o", str(out_pdf)],
    )
    assert res2.exit_code == 2


def test_pages_reverse(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "reversed.pdf"
    res = runner.invoke(cli, ["pages", "reverse", str(multi_page_pdf), "-o", str(out_pdf)])
    assert res.exit_code == 0
    assert "Reversed 5 pages" in res.output

    with pikepdf.open(out_pdf) as p:
        assert len(p.pages) == 5


def test_pages_rotate_relative_and_absolute(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf1 = tmp_path / "rotated90.pdf"

    # Relative 90 degrees on even pages
    res = runner.invoke(
        cli,
        [
            "pages",
            "rotate",
            str(multi_page_pdf),
            "90",
            "-o",
            str(out_pdf1),
            "--pages",
            "even",
        ],
    )
    assert res.exit_code == 0

    with pikepdf.open(out_pdf1) as p:
        assert p.pages[0].get("/Rotate", 0) == 0
        assert p.pages[1].get("/Rotate", 0) == 90
        assert p.pages[2].get("/Rotate", 0) == 0
        assert p.pages[3].get("/Rotate", 0) == 90

    # Absolute 180 degrees
    out_pdf2 = tmp_path / "rotated_abs.pdf"
    res2 = runner.invoke(
        cli,
        [
            "pages",
            "rotate",
            str(out_pdf1),
            "180",
            "-o",
            str(out_pdf2),
            "--absolute",
        ],
    )
    assert res2.exit_code == 0

    with pikepdf.open(out_pdf2) as p:
        for page in p.pages:
            assert page.get("/Rotate", 0) == 180


def test_pages_rotate_invalid_angle(multi_page_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "invalid_angle.pdf"
    res = runner.invoke(
        cli,
        ["pages", "rotate", str(multi_page_pdf), "45", "-o", str(out_pdf)],
    )
    assert res.exit_code == 2


def test_same_file_prevention_on_write(multi_page_pdf: Path) -> None:
    runner = CliRunner()
    # Attempt in-place write
    res = runner.invoke(
        cli,
        ["pages", "reverse", str(multi_page_pdf), "-o", str(multi_page_pdf)],
    )
    assert res.exit_code == 8  # SAFETY_CONFLICT
