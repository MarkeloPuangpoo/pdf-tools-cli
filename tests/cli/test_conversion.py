"""Tests for conversion CLI commands conforming to PLAN.md §12.4 C23, C24 (CMD-010)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import PIL.Image
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def image_files(tmp_path: Path) -> list[Path]:
    paths = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        p = tmp_path / f"img_{i}.png"
        im = PIL.Image.new("RGB", (100, 150), color=color)
        im.save(p, format="PNG")
        paths.append(p)
    return paths


def test_convert_images_basic(image_files: list[Path], tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "converted.pdf"
    result = runner.invoke(
        cli,
        ["convert", "images", *[str(p) for p in image_files], "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()
    with pikepdf.open(out_pdf) as doc:
        assert len(doc.pages) == 3


def test_convert_images_custom_size_and_fit(image_files: list[Path], tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "a4.pdf"
    result = runner.invoke(
        cli,
        [
            "--json",
            "convert",
            "images",
            *[str(p) for p in image_files],
            "-o",
            str(out_pdf),
            "--size",
            "A4",
            "--fit",
            "contain",
        ],
    )
    assert result.exit_code == 0, result.output
    with pikepdf.open(out_pdf) as doc:
        assert len(doc.pages) == 3
        page = doc.pages[0]
        # A4: 595.28 x 841.89
        assert abs(float(page.mediabox[2]) - 595.28) < 1.0
        assert abs(float(page.mediabox[3]) - 841.89) < 1.0


def test_convert_images_reject_empty_image(tmp_path: Path) -> None:
    runner = CliRunner()
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    out_pdf = tmp_path / "empty.pdf"
    result = runner.invoke(
        cli,
        ["convert", "images", str(empty_file), "-o", str(out_pdf)],
    )
    assert result.exit_code == 2
    assert "empty (zero bytes)" in result.output


def test_convert_images_multi_frame_handling(tmp_path: Path) -> None:
    runner = CliRunner()
    multi_frame = tmp_path / "animated.gif"
    f1 = PIL.Image.new("RGB", (50, 50), (255, 0, 0))
    f2 = PIL.Image.new("RGB", (50, 50), (0, 255, 0))
    f1.save(multi_frame, save_all=True, append_images=[f2])

    out_pdf = tmp_path / "multi.pdf"
    # Should fail without --all-frames
    result = runner.invoke(
        cli,
        ["convert", "images", str(multi_frame), "-o", str(out_pdf)],
    )
    assert result.exit_code == 2
    assert "contains 2 frames" in result.output

    # Should succeed with --all-frames
    result_ok = runner.invoke(
        cli,
        ["convert", "images", str(multi_frame), "-o", str(out_pdf), "--all-frames"],
    )
    assert result_ok.exit_code == 0, result_ok.output
    with pikepdf.open(out_pdf) as doc:
        assert len(doc.pages) == 2


def test_convert_rasterize(tmp_path: Path) -> None:
    runner = CliRunner()
    # Create sample vector/text PDF
    src_pdf = tmp_path / "vector.pdf"
    doc = pikepdf.Pdf.new()
    doc.add_blank_page(page_size=(300, 400))
    doc.add_blank_page(page_size=(300, 400))
    doc.save(src_pdf)

    out_pdf = tmp_path / "rasterized.pdf"
    result = runner.invoke(
        cli,
        [
            "--json",
            "convert",
            "rasterize",
            str(src_pdf),
            "-o",
            str(out_pdf),
            "--dpi",
            "72",
            "--colorspace",
            "gray",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()
    with pikepdf.open(out_pdf) as flat_doc:
        assert len(flat_doc.pages) == 2
