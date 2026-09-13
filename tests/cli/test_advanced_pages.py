"""Tests for advanced page assembly and geometry operations (CMD-008).

Conforms to PLAN.md §12.3 (C06, C07, C08, C15, C16, C17, C18).
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def pdf_3pages(tmp_path: Path) -> Path:
    p = tmp_path / "three_pages.pdf"
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page()
    pdf.save(p)
    pdf.close()
    return p


@pytest.fixture
def pdf_2pages(tmp_path: Path) -> Path:
    p = tmp_path / "two_pages.pdf"
    pdf = pikepdf.new()
    for _ in range(2):
        pdf.add_blank_page()
    pdf.save(p)
    pdf.close()
    return p


def test_assemble_basic(pdf_3pages: Path, pdf_2pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "assembled.pdf"
    result = runner.invoke(
        cli,
        [
            "assemble",
            "--source",
            str(pdf_3pages),
            "1-2",
            "--source",
            str(pdf_2pages),
            "last,1",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    assert out.exists()

    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 4  # 2 from doc1 + 2 from doc2


def test_assemble_same_file_error(pdf_3pages: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "assemble",
            "--source",
            str(pdf_3pages),
            "1",
            "-o",
            str(pdf_3pages),
        ],
    )
    assert result.exit_code == 8


def test_insert_anchor_last_and_prepend(pdf_3pages: Path, pdf_2pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out1 = tmp_path / "inserted_last.pdf"
    result1 = runner.invoke(
        cli,
        [
            "insert",
            str(pdf_3pages),
            str(pdf_2pages),
            "--after",
            "last",
            "-o",
            str(out1),
        ],
    )
    assert result1.exit_code == 0
    with pikepdf.open(out1) as pdf:
        assert len(pdf.pages) == 5

    out2 = tmp_path / "inserted_prepend.pdf"
    result2 = runner.invoke(
        cli,
        [
            "insert",
            str(pdf_3pages),
            str(pdf_2pages),
            "--after",
            "0",
            "-o",
            str(out2),
        ],
    )
    assert result2.exit_code == 0
    with pikepdf.open(out2) as pdf:
        assert len(pdf.pages) == 5


def test_insert_invalid_after(pdf_3pages: Path, pdf_2pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "out.pdf"
    result = runner.invoke(
        cli,
        [
            "insert",
            str(pdf_3pages),
            str(pdf_2pages),
            "--after",
            "99",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 2


def test_interleave_append_and_error(pdf_3pages: Path, pdf_2pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "interleaved.pdf"

    # Unequal lengths with default append succeeds
    result = runner.invoke(
        cli,
        [
            "interleave",
            str(pdf_3pages),
            str(pdf_2pages),
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 5

    # Unequal lengths with remainder=error fails with exit code 2
    out_err = tmp_path / "interleaved_err.pdf"
    result_err = runner.invoke(
        cli,
        [
            "interleave",
            str(pdf_3pages),
            str(pdf_2pages),
            "--remainder",
            "error",
            "-o",
            str(out_err),
        ],
    )
    assert result_err.exit_code == 2


def test_interleave_reverse_even_inputs(pdf_2pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "interleaved_rev.pdf"
    result = runner.invoke(
        cli,
        [
            "interleave",
            str(pdf_2pages),
            str(pdf_2pages),
            "--reverse-even-inputs",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 4


def test_pages_duplicate(pdf_3pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "duplicated.pdf"
    result = runner.invoke(
        cli,
        [
            "pages",
            "duplicate",
            str(pdf_3pages),
            "1-2",
            "--after",
            "last",
            "--copies",
            "2",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    with pikepdf.open(out) as pdf:
        # Original 3 + (2 pages * 2 copies) = 7 pages
        assert len(pdf.pages) == 7
        # Ensure duplicated pages have independent object identities
        objgens = [p.objgen for p in pdf.pages]
        assert len(objgens) == len(set(objgens))


def test_pages_crop(pdf_3pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "cropped.pdf"
    result = runner.invoke(
        cli,
        [
            "pages",
            "crop",
            str(pdf_3pages),
            "--margins",
            "10mm,10mm,10mm,10mm",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    with pikepdf.open(out) as pdf:
        cb = pdf.pages[0].cropbox
        mb = pdf.pages[0].mediabox
        # CropBox must be strictly smaller than MediaBox
        assert float(cb[0]) > float(mb[0])
        assert float(cb[2]) < float(mb[2])


def test_pages_crop_oversized_margins(pdf_3pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "oversized.pdf"
    result = runner.invoke(
        cli,
        [
            "pages",
            "crop",
            str(pdf_3pages),
            "--margins",
            "1000pt,1000pt,1000pt,1000pt",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 2


def test_pages_resize(pdf_3pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "resized_a4.pdf"
    result = runner.invoke(
        cli,
        [
            "pages",
            "resize",
            str(pdf_3pages),
            "--size",
            "A4",
            "--fit",
            "contain",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    with pikepdf.open(out) as pdf:
        mb = [float(c) for c in pdf.pages[0].mediabox]
        assert pytest.approx(mb[2], 0.1) == 595.28
        assert pytest.approx(mb[3], 0.1) == 841.89


def test_pages_boxes(pdf_3pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "boxed.pdf"
    result = runner.invoke(
        cli,
        [
            "pages",
            "boxes",
            str(pdf_3pages),
            "--set",
            "crop=10pt,10pt,500pt,700pt",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 0
    with pikepdf.open(out) as pdf:
        cb = [float(c) for c in pdf.pages[0].cropbox]
        assert cb == [10.0, 10.0, 500.0, 700.0]


def test_pages_boxes_containment_violation(pdf_3pages: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "bad_box.pdf"
    # CropBox larger than default MediaBox (default MediaBox is 595.28 x 841.89 or 612 x 792)
    result = runner.invoke(
        cli,
        [
            "pages",
            "boxes",
            str(pdf_3pages),
            "--set",
            "crop=0pt,0pt,2000pt,2000pt",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 2
