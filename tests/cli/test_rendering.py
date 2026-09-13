"""Tests for rendering CLI command conforming to PLAN.md §12.4 C22 (CMD-010)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import PIL.Image
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample.pdf"
    doc = pikepdf.Pdf.new()
    for _ in range(3):
        doc.add_blank_page(page_size=(200, 300))
    doc.save(pdf_path)
    return pdf_path


def test_render_single_page_file(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_png = tmp_path / "page1.png"
    result = runner.invoke(
        cli,
        [
            "render",
            str(sample_pdf),
            "--pages",
            "1",
            "-o",
            str(out_png),
            "--to",
            "png",
            "--dpi",
            "72",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_png.exists()
    with PIL.Image.open(out_png) as img:
        assert img.format == "PNG"
        assert img.width == 200
        assert img.height == 300


def test_render_single_page_stdout(sample_pdf: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["render", str(sample_pdf), "--pages", "2", "-o", "-", "--to", "png", "--dpi", "72"],
    )
    assert result.exit_code == 0
    # Output buffer contains PNG magic header: \x89PNG
    assert result.stdout_bytes.startswith(b"\x89PNG")


def test_render_multiple_pages_directory(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "rendered"
    result = runner.invoke(
        cli,
        [
            "--json",
            "render",
            str(sample_pdf),
            "--output-dir",
            str(out_dir),
            "--to",
            "jpeg",
            "--dpi",
            "72",
            "--quality",
            "90",
        ],
    )
    assert result.exit_code == 0, result.output
    files = list(out_dir.glob("*.jpeg"))
    assert len(files) == 3


def test_render_transparent_rejected_for_jpeg(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "rendered_invalid"
    result = runner.invoke(
        cli,
        [
            "render",
            str(sample_pdf),
            "--output-dir",
            str(out_dir),
            "--to",
            "jpeg",
            "--background",
            "transparent",
        ],
    )
    assert result.exit_code == 2
    assert "Transparent background is not supported" in result.output


def test_render_grayscale_colorspace(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_png = tmp_path / "gray.png"
    result = runner.invoke(
        cli,
        [
            "render",
            str(sample_pdf),
            "--pages",
            "1",
            "-o",
            str(out_png),
            "--colorspace",
            "gray",
            "--dpi",
            "72",
        ],
    )
    assert result.exit_code == 0, result.output
    with PIL.Image.open(out_png) as img:
        assert img.mode == "L"


def test_render_reject_multi_page_with_single_output_flag(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_png = tmp_path / "bad.png"
    result = runner.invoke(
        cli,
        ["render", str(sample_pdf), "--pages", "1-2", "-o", str(out_png)],
    )
    assert result.exit_code == 2
    assert "can only be used when exactly one page is selected" in result.output
