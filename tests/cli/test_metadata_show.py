"""CLI tests for document metadata inspection (CMD-007).

Conforms to PLAN.md §12.6 C31, §1404.
"""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def pdf_with_metadata(tmp_path: Path) -> Path:
    """Create a PDF with both docinfo and XMP metadata."""
    pdf_path = tmp_path / "meta_doc.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()

    # XMP
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["dc:title"] = "Annual Report 2026"
        meta["dc:creator"] = ["Finance Team"]

    # Docinfo
    pdf.docinfo["/Title"] = "Annual Report 2026"
    pdf.docinfo["/Author"] = "Finance Team"
    pdf.docinfo["/CreationDate"] = "D:20260115120000Z"

    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


@pytest.fixture
def pdf_with_discrepancy(tmp_path: Path) -> Path:
    """Create a PDF with conflicting Info and XMP metadata."""
    pdf_path = tmp_path / "discrepant_doc.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()

    # XMP
    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["dc:title"] = "Title in XMP"

    # Conflicting Title in Info
    pdf.docinfo["/Title"] = "Title in Info"

    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


def test_metadata_show_default(pdf_with_metadata: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["metadata", "show", str(pdf_with_metadata)])
    assert res.exit_code == 0
    assert "Annual Report 2026" in res.output
    assert "Finance Team" in res.output


def test_metadata_show_json_mode(pdf_with_metadata: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "metadata", "show", str(pdf_with_metadata)])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "success"
    assert data["data"]["info"]["Title"] == "Annual Report 2026"
    assert data["data"]["info"]["CreationDate"]["normalized"] == "2026-01-15T12:00:00Z"
    assert data["data"]["has_xmp"] is True


def test_metadata_show_discrepancies(pdf_with_discrepancy: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "metadata", "show", str(pdf_with_discrepancy)])
    assert res.exit_code == 0
    data = json.loads(res.output)
    discrepancies = data["data"]["discrepancies"]
    assert len(discrepancies) >= 1
    d = discrepancies[0]
    assert d["field"] == "Title"
    assert d["info_value"] == "Title in Info"
    assert d["xmp_value"] == "Title in XMP"


def test_metadata_show_source_filter(pdf_with_metadata: Path) -> None:
    runner = CliRunner()
    # Info only
    res_info = runner.invoke(
        cli, ["--json", "metadata", "show", str(pdf_with_metadata), "--source", "info"]
    )
    assert res_info.exit_code == 0
    data_info = json.loads(res_info.output)
    assert data_info["data"]["info"]
    assert not data_info["data"]["xmp"]

    # XMP only
    res_xmp = runner.invoke(
        cli, ["--json", "metadata", "show", str(pdf_with_metadata), "--source", "xmp"]
    )
    assert res_xmp.exit_code == 0
    data_xmp = json.loads(res_xmp.output)
    assert not data_xmp["data"]["info"]
    assert data_xmp["data"]["xmp"]


def test_metadata_show_raw_xmp(pdf_with_metadata: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["metadata", "show", str(pdf_with_metadata), "--raw-xmp"])
    assert res.exit_code == 0
    assert "<?xpacket" in res.output or "<x:xmpmeta" in res.output
    assert "Annual Report 2026" in res.output


def test_metadata_raw_xmp_conflicts_with_json(pdf_with_metadata: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "metadata", "show", str(pdf_with_metadata), "--raw-xmp"])
    assert res.exit_code == 2  # USAGE_OR_SELECTION


def test_metadata_show_empty_pdf(tmp_path: Path) -> None:
    runner = CliRunner()
    blank = tmp_path / "plain_blank.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(blank)
    pdf.close()

    res = runner.invoke(cli, ["--json", "metadata", "show", str(blank)])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "success"
