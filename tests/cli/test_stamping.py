"""Tests for stamping, watermarking, and dynamic page numbering conforming to
PLAN.md §12.7 C37-C38 (CMD-013).
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pypdfium2
import pytest
from click.testing import CliRunner
from PIL import Image as PILImage

from pdftoolscli.cli.main import cli
from pdftoolscli.domain.errors import ExitCode


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a multi-page sample PDF."""
    pdf_path = tmp_path / "sample.pdf"
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page(page_size=(300, 300))
    pdf.save(pdf_path)
    return pdf_path


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    """Create a sample PNG image."""
    img_path = tmp_path / "logo.png"
    img = PILImage.new("RGBA", (64, 64), color=(255, 0, 0, 200))
    img.save(img_path)
    return img_path


@pytest.fixture
def watermark_pdf(tmp_path: Path) -> Path:
    """Create a sample watermark PDF."""
    wm_path = tmp_path / "watermark.pdf"
    pdf = pikepdf.new()
    p = pdf.add_blank_page(page_size=(100, 100))
    p.contents_add(b"1 0 0 rg 0 0 100 100 re f\n")
    pdf.save(wm_path)
    return wm_path


def test_stamp_text_basic(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify stamping text with default options creates valid PDF with visible text."""
    out_pdf = tmp_path / "stamped.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["stamp", str(sample_pdf), "--text", "CONFIDENTIAL", "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    # Verify text was embedded using pypdfium2
    doc = pypdfium2.PdfDocument(out_pdf)
    page = doc.get_page(0)
    text = page.get_textpage().get_text_range()
    assert "CONFIDENTIAL" in text


def test_stamp_text_options(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify stamping text with custom rotation, position, color, layer, opacity, and scale."""
    out_pdf = tmp_path / "stamped_opt.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--text",
            "DRAFT",
            "-o",
            str(out_pdf),
            "--rotation",
            "-30",
            "--position",
            "top-left",
            "--color",
            "#FF0000",
            "--opacity",
            "0.5",
            "--scale",
            "1.5",
            "--layer",
            "background",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    doc = pypdfium2.PdfDocument(out_pdf)
    text = doc.get_page(0).get_textpage().get_text_range()
    assert "DRAFT" in text


def test_stamp_image(sample_pdf: Path, sample_image: Path, tmp_path: Path) -> None:
    """Verify stamping an image onto pages."""
    out_pdf = tmp_path / "stamped_img.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--image",
            str(sample_image),
            "-o",
            str(out_pdf),
            "--position",
            "center",
            "--scale",
            "0.5",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    # Verify image XObject is attached
    with pikepdf.open(out_pdf) as pdf:
        page = pdf.pages[0]
        assert "/XObject" in page.Resources


def test_stamp_pdf_watermark(sample_pdf: Path, watermark_pdf: Path, tmp_path: Path) -> None:
    """Verify stamping another PDF's page as a watermark."""
    out_pdf = tmp_path / "stamped_pdf.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--pdf",
            str(watermark_pdf),
            "--source-page",
            "1",
            "-o",
            str(out_pdf),
            "--layer",
            "background",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    with pikepdf.open(out_pdf) as pdf:
        assert len(pdf.pages) == 3
        page = pdf.pages[0]
        assert "/XObject" in page.Resources


def test_stamp_tile(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify tiling across the page grid."""
    out_pdf = tmp_path / "stamped_tiled.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--text",
            "WATERMARK",
            "--tile",
            "100pt,100pt",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    doc = pypdfium2.PdfDocument(out_pdf)
    text = doc.get_page(0).get_textpage().get_text_range()
    assert text.count("WATERMARK") >= 4


def test_stamp_pages_selection(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify stamping only selected pages."""
    out_pdf = tmp_path / "stamped_p2.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--text",
            "ONLY_PAGE_TWO",
            "--pages",
            "2",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output

    doc = pypdfium2.PdfDocument(out_pdf)
    assert "ONLY_PAGE_TWO" not in doc.get_page(0).get_textpage().get_text_range()
    assert "ONLY_PAGE_TWO" in doc.get_page(1).get_textpage().get_text_range()
    assert "ONLY_PAGE_TWO" not in doc.get_page(2).get_textpage().get_text_range()


def test_stamp_custom_position_requires_offset(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify position custom without explicit offset is rejected."""
    out_pdf = tmp_path / "stamped_err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--text",
            "ERR",
            "--position",
            "custom",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_stamp_mutually_exclusive_sources(
    sample_pdf: Path, sample_image: Path, tmp_path: Path
) -> None:
    """Verify specifying multiple or no stamp sources is rejected with exit code 2."""
    out_pdf = tmp_path / "stamped_err.pdf"
    runner = CliRunner()
    # No source
    res1 = runner.invoke(cli, ["stamp", str(sample_pdf), "-o", str(out_pdf)])
    assert res1.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    # Multiple sources
    res2 = runner.invoke(
        cli,
        [
            "stamp",
            str(sample_pdf),
            "--text",
            "HELLO",
            "--image",
            str(sample_image),
            "-o",
            str(out_pdf),
        ],
    )
    assert res2.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_stamp_in_place_refusal(sample_pdf: Path) -> None:
    """Verify input == output is rejected with exit code 8."""
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["stamp", str(sample_pdf), "--text", "INPLACE", "-o", str(sample_pdf)],
    )
    assert res.exit_code == int(ExitCode.SAFETY_CONFLICT)


def test_number_basic(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify basic page numbering with default '{page} / {pages}' format."""
    out_pdf = tmp_path / "numbered.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["number", str(sample_pdf), "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    doc = pypdfium2.PdfDocument(out_pdf)
    assert len(doc) == 3
    assert "1 / 3" in doc.get_page(0).get_textpage().get_text_range()
    assert "2 / 3" in doc.get_page(1).get_textpage().get_text_range()
    assert "3 / 3" in doc.get_page(2).get_textpage().get_text_range()


def test_number_roman_style(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify roman and ROMAN page numbering styles."""
    out_pdf = tmp_path / "numbered_roman.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "number",
            str(sample_pdf),
            "-o",
            str(out_pdf),
            "--style",
            "roman",
            "--format",
            "Page {page} of {pages}",
        ],
    )
    assert result.exit_code == 0, result.output

    doc = pypdfium2.PdfDocument(out_pdf)
    assert "Page i of iii" in doc.get_page(0).get_textpage().get_text_range()
    assert "Page ii of iii" in doc.get_page(1).get_textpage().get_text_range()
    assert "Page iii of iii" in doc.get_page(2).get_textpage().get_text_range()


def test_number_roman_rejects_zero_or_negative(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify Roman numerals reject start < 1 with exit code 2 (PLAN.md Q3)."""
    out_pdf = tmp_path / "numbered_err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "number",
            str(sample_pdf),
            "-o",
            str(out_pdf),
            "--style",
            "roman",
            "--start",
            "0",
        ],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_number_header_footer_and_format(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify distinct header, footer, and position-configured format render without collision."""
    out_pdf = tmp_path / "numbered_full.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "number",
            str(sample_pdf),
            "-o",
            str(out_pdf),
            "--header",
            "HEADER TITLE",
            "--footer",
            "FOOTER NOTICE",
            "--format",
            "{page}",
            "--position",
            "bottom-right",
        ],
    )
    assert result.exit_code == 0, result.output

    doc = pypdfium2.PdfDocument(out_pdf)
    text = doc.get_page(0).get_textpage().get_text_range()
    assert "HEADER TITLE" in text
    assert "FOOTER NOTICE" in text
    assert "1" in text


def test_number_collision_preflight_rejection(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify preflight rejection when header/footer collide with format position."""
    out_pdf = tmp_path / "numbered_coll.pdf"
    runner = CliRunner()

    # Collision at top
    res1 = runner.invoke(
        cli,
        [
            "number",
            str(sample_pdf),
            "-o",
            str(out_pdf),
            "--header",
            "TOP_HEADER",
            "--position",
            "top",
        ],
    )
    assert res1.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    # Collision at bottom
    res2 = runner.invoke(
        cli,
        [
            "number",
            str(sample_pdf),
            "-o",
            str(out_pdf),
            "--footer",
            "BOTTOM_FOOTER",
            "--position",
            "bottom",
        ],
    )
    assert res2.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_number_date_variable(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify {date} variable expansion and requirement for --date."""
    out_pdf = tmp_path / "numbered_date.pdf"
    runner = CliRunner()

    # Fails when --date omitted
    res_fail = runner.invoke(
        cli,
        ["number", str(sample_pdf), "-o", str(out_pdf), "--format", "{page} - {date}"],
    )
    assert res_fail.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    # Succeeds when --date provided
    res_ok = runner.invoke(
        cli,
        [
            "number",
            str(sample_pdf),
            "-o",
            str(out_pdf),
            "--format",
            "{page} - {date}",
            "--date",
            "2026-09-13",
        ],
    )
    assert res_ok.exit_code == 0, res_ok.output

    doc = pypdfium2.PdfDocument(out_pdf)
    assert "1 - 2026-09-13" in doc.get_page(0).get_textpage().get_text_range()


def test_number_unknown_template_variable(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify unknown template variables are rejected with exit code 2."""
    out_pdf = tmp_path / "numbered_var_err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["number", str(sample_pdf), "-o", str(out_pdf), "--format", "{page} of {unsupported}"],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_stamp_on_rotated_page(tmp_path: Path) -> None:
    """Verify stamping respects rotated page orientation."""
    pdf_path = tmp_path / "rotated.pdf"
    out_pdf = tmp_path / "stamped_rot.pdf"
    pdf = pikepdf.new()
    p = pdf.add_blank_page(page_size=(300, 600))
    p.Rotate = 90
    pdf.save(pdf_path)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["stamp", str(pdf_path), "--text", "ROT_STAMP", "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as res:
        assert res.pages[0].Rotate == 90
    doc = pypdfium2.PdfDocument(out_pdf)
    text = doc.get_page(0).get_textpage().get_text_range()
    assert "ROT_STAMP" in text


def test_stamp_json_output(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify stamp command supports structured JSON output."""
    out_pdf = tmp_path / "stamped_json.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--json", "stamp", str(sample_pdf), "--text", "JSON_STAMP", "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output
    import json

    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["command"] == "stamp"
    assert data["data"]["pages_modified"] == 3


def test_number_start_decimal_zero_and_negative(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify decimal numbering accepts start=0 and rejects start < 0."""
    out_pdf = tmp_path / "num_zero.pdf"
    runner = CliRunner()

    # start=0 is valid for decimal
    res0 = runner.invoke(
        cli,
        ["number", str(sample_pdf), "-o", str(out_pdf), "--start", "0"],
    )
    assert res0.exit_code == 0, res0.output
    doc = pypdfium2.PdfDocument(out_pdf)
    assert "0 / 3" in doc.get_page(0).get_textpage().get_text_range()

    # start=-1 is invalid
    out_pdf_neg = tmp_path / "num_neg.pdf"
    res_neg = runner.invoke(
        cli,
        ["number", str(sample_pdf), "-o", str(out_pdf_neg), "--start", "-1"],
    )
    assert res_neg.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_stamp_invalid_parameters_rejected(sample_pdf: Path, tmp_path: Path) -> None:
    """Verify validation on color, opacity, and scale."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()

    # Invalid color
    r_col = runner.invoke(
        cli,
        ["stamp", str(sample_pdf), "--text", "X", "-o", str(out_pdf), "--color", "not_a_color"],
    )
    assert r_col.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    # Invalid opacity
    r_op = runner.invoke(
        cli,
        ["stamp", str(sample_pdf), "--text", "X", "-o", str(out_pdf), "--opacity", "1.5"],
    )
    assert r_op.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    # Invalid scale
    r_sc = runner.invoke(
        cli,
        ["stamp", str(sample_pdf), "--text", "X", "-o", str(out_pdf), "--scale", "-1.0"],
    )
    assert r_sc.exit_code == int(ExitCode.USAGE_OR_SELECTION)
