"""Tests for embedded image management commands conforming to PLAN.md §12.5 (CMD-009)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pikepdf
import PIL.Image
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def pdf_with_image(tmp_path: Path) -> tuple[Path, int, int]:
    # Generate test image
    width, height = 120, 80
    img = PIL.Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    jpeg_bytes = buf.getvalue()

    pdf_path = tmp_path / "doc_with_image.pdf"
    pdf = pikepdf.new()
    page = pdf.add_blank_page()

    # Embed Image XObject
    img_stream = pdf.make_stream(jpeg_bytes)
    img_stream["/Type"] = pikepdf.Name("/XObject")
    img_stream["/Subtype"] = pikepdf.Name("/Image")
    img_stream["/Width"] = width
    img_stream["/Height"] = height
    img_stream["/ColorSpace"] = pikepdf.Name("/DeviceRGB")
    img_stream["/BitsPerComponent"] = 8
    img_stream["/Filter"] = pikepdf.Name("/DCTDecode")

    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary({"/Im0": img_stream}))
    pdf.save(pdf_path)
    pdf.close()

    return pdf_path, width, height


@pytest.fixture
def blank_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "blank.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(p)
    pdf.close()
    return p


def test_images_list_no_images(blank_pdf: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["images", "list", str(blank_pdf)])
    assert result.exit_code == 0
    assert "0 unique image" in result.output


def test_images_list_with_image(pdf_with_image: tuple[Path, int, int]) -> None:
    pdf_path, width, height = pdf_with_image
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "images", "list", str(pdf_path)])
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["data"]["total_unique_images"] == 1
    assert data["data"]["images"][0]["width"] == width
    assert data["data"]["images"][0]["height"] == height
    assert "/DCTDecode" in data["data"]["images"][0]["filters"]


def test_images_extract_original(pdf_with_image: tuple[Path, int, int], tmp_path: Path) -> None:
    pdf_path, width, height = pdf_with_image
    out_dir = tmp_path / "extracted_orig"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "images",
            "extract",
            str(pdf_path),
            "--output-dir",
            str(out_dir),
            "--mode",
            "original",
        ],
    )
    assert result.exit_code == 0
    assert out_dir.exists()

    manifest_file = out_dir / "manifest.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text())
    assert manifest["total_extracted"] == 1
    assert manifest["images"][0]["width"] == width

    # Check extracted image file
    extracted_filename = manifest["images"][0]["filename"]
    extracted_path = out_dir / extracted_filename
    assert extracted_path.exists()
    with PIL.Image.open(extracted_path) as im:
        assert im.size == (width, height)


def test_images_extract_decoded(pdf_with_image: tuple[Path, int, int], tmp_path: Path) -> None:
    pdf_path, width, height = pdf_with_image
    out_dir = tmp_path / "extracted_decoded"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "images",
            "extract",
            str(pdf_path),
            "--output-dir",
            str(out_dir),
            "--mode",
            "decoded",
            "--to",
            "png",
        ],
    )
    assert result.exit_code == 0

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["total_extracted"] == 1
    extracted_filename = manifest["images"][0]["filename"]
    assert extracted_filename.endswith(".png")


def test_images_extract_asset_filter(pdf_with_image: tuple[Path, int, int], tmp_path: Path) -> None:
    pdf_path, _, _ = pdf_with_image
    out_dir = tmp_path / "extracted_filter"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "images",
            "extract",
            str(pdf_path),
            "--output-dir",
            str(out_dir),
            "--asset",
            "nonexistent-id",
        ],
    )
    assert result.exit_code == 0
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["total_extracted"] == 0
