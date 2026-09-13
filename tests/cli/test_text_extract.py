"""CLI tests for plain text extraction (CMD-006).

Conforms to PLAN.md §12.5 C26, §1385.
"""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner
from reportlab.pdfgen import canvas

from pdftoolscli.cli.main import cli


@pytest.fixture
def pdf_with_text(tmp_path: Path) -> Path:
    """Create a 2-page PDF containing extractable text."""
    pdf_path = tmp_path / "text_doc.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(100, 700, "First Page Content")
    c.showPage()
    c.drawString(100, 700, "Second Page Content")
    c.showPage()
    c.save()
    return pdf_path


@pytest.fixture
def pdf_without_text(tmp_path: Path) -> Path:
    """Create a blank PDF containing no text layer."""
    pdf_path = tmp_path / "blank.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


def test_text_extract_stdout(pdf_with_text: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["text", "extract", str(pdf_with_text)])
    assert res.exit_code == 0
    assert "First Page Content" in res.output
    assert "Second Page Content" in res.output
    # Form-feed separator present between pages
    assert "\x0c" in res.output


def test_text_extract_to_file(pdf_with_text: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_txt = tmp_path / "extracted.txt"

    res = runner.invoke(cli, ["text", "extract", str(pdf_with_text), "-o", str(out_txt)])
    assert res.exit_code == 0
    assert "Extracted text" in res.output
    assert out_txt.is_file()

    content = out_txt.read_text(encoding="utf-8")
    assert "First Page Content" in content
    assert "Second Page Content" in content


def test_text_extract_page_range(pdf_with_text: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["text", "extract", str(pdf_with_text), "--pages", "2"])
    assert res.exit_code == 0
    assert "Second Page Content" in res.output
    assert "First Page Content" not in res.output


def test_text_extract_require_text_fails_on_blank(pdf_without_text: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["text", "extract", str(pdf_without_text), "--require-text"])
    assert res.exit_code == 5  # INVALID_DOCUMENT


def test_text_extract_require_text_succeeds_on_text(pdf_with_text: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["text", "extract", str(pdf_with_text), "--require-text"])
    assert res.exit_code == 0


def test_text_extract_same_file_rejected(pdf_with_text: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["text", "extract", str(pdf_with_text), "-o", str(pdf_with_text)])
    assert res.exit_code == 8  # SAFETY_CONFLICT


def test_text_extract_json_mode(pdf_with_text: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "text", "extract", str(pdf_with_text)])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "success"
    assert data["data"]["has_text"] is True
    assert data["data"]["total_pages"] == 2
    assert len(data["data"]["page_records"]) == 2
    assert "First Page Content" in data["data"]["page_records"][0]["text"]
