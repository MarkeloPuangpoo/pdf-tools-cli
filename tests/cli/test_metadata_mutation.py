"""Tests for metadata mutation and sanitization commands conforming to
PLAN.md §12.6 C32-C34 (CMD-012).
"""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def pdf_with_meta(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "meta_source.pdf"
    doc = pikepdf.Pdf.new()
    doc.add_blank_page()
    doc.docinfo["/Title"] = "Original Title"
    doc.docinfo["/Author"] = "Original Author"
    doc.docinfo["/Subject"] = "Original Subject"
    with doc.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["dc:title"] = "Original Title"
        meta["dc:creator"] = ["Original Author"]
        meta["dc:description"] = "Original Subject"
    doc.save(pdf_path, fix_metadata_version=False)
    return pdf_path


def test_metadata_set_basic(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "updated.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "set",
            str(pdf_with_meta),
            "--set",
            "title=New Title",
            "--set",
            "author=New Author",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    with pikepdf.open(out_pdf) as doc:
        assert str(doc.docinfo.get("/Title")) == "New Title"
        assert str(doc.docinfo.get("/Author")) == "New Author"
        with doc.open_metadata() as meta:
            assert meta.get("dc:title") == "New Title"
            assert meta.get("dc:creator") == ["New Author"]


def test_metadata_set_dates(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "dated.pdf"
    rfc_date = "2023-08-15T14:30:00Z"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "set",
            str(pdf_with_meta),
            "--set",
            f"creation-date={rfc_date}",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    with pikepdf.open(out_pdf) as doc:
        assert "20230815143000" in str(doc.docinfo.get("/CreationDate"))


def test_metadata_set_invalid_date_rejected(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "invalid_date.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "set",
            str(pdf_with_meta),
            "--set",
            "creation-date=not-a-valid-date",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 2
    assert "Invalid RFC3339 date format" in result.output


def test_metadata_set_unknown_key_rejected(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "unknown_key.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "set",
            str(pdf_with_meta),
            "--set",
            "nonexistent_field=Value",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 2
    assert "Unknown metadata key" in result.output


def test_metadata_set_duplicate_key_rejected(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "dup_key.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "set",
            str(pdf_with_meta),
            "--set",
            "title=First Title",
            "--set",
            "title=Second Title",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 2
    assert "Duplicate metadata key" in result.output


def test_metadata_set_xmp_file_malicious_entity(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    xmp_path = tmp_path / "bad.xml"
    xmp_path.write_bytes(b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><x:xmpmeta/>')
    out_pdf = tmp_path / "xxe.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "set",
            str(pdf_with_meta),
            "--xmp-file",
            str(xmp_path),
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 2
    assert "forbidden DOCTYPE or ENTITY" in result.output


def test_metadata_remove_keys(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "removed_keys.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "remove",
            str(pdf_with_meta),
            "--key",
            "title",
            "--key",
            "author",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    with pikepdf.open(out_pdf) as doc:
        assert "/Title" not in doc.docinfo
        assert "/Author" not in doc.docinfo
        # Subject should remain
        assert "/Subject" in doc.docinfo


def test_metadata_remove_all(pdf_with_meta: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_pdf = tmp_path / "removed_all.pdf"
    result = runner.invoke(
        cli,
        [
            "metadata",
            "remove",
            str(pdf_with_meta),
            "--all",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    with pikepdf.open(out_pdf) as doc:
        assert len(doc.docinfo) == 0
        assert "/Metadata" not in doc.Root


def test_metadata_sanitize(tmp_path: Path) -> None:
    runner = CliRunner()
    src_pdf = tmp_path / "to_sanitize.pdf"
    doc = pikepdf.Pdf.new()
    page = doc.add_blank_page()
    # Add Info
    doc.docinfo["/Title"] = "Secret Document"
    doc.docinfo["/Author"] = "Confidential Author"
    # Add Catalog XMP
    with doc.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["dc:title"] = "Secret Document"
    # Add object-level metadata on page
    page["/Metadata"] = doc.make_stream(b"<x:xmpmeta>Object Secret</x:xmpmeta>")
    doc.save(src_pdf, fix_metadata_version=False)

    out_pdf = tmp_path / "sanitized.pdf"
    result = runner.invoke(
        cli,
        [
            "--json",
            "metadata",
            "sanitize",
            str(src_pdf),
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["info_removed"] is True
    assert payload["data"]["catalog_xmp_removed"] is True
    assert payload["data"]["object_metadata_streams_removed"] >= 1

    with pikepdf.open(out_pdf) as clean_doc:
        assert len(clean_doc.docinfo) == 0
        assert "/Metadata" not in clean_doc.Root
        assert "/Metadata" not in clean_doc.pages[0]

    # Verify no residual strings in raw file bytes
    raw_content = out_pdf.read_bytes()
    assert b"Secret Document" not in raw_content
    assert b"Confidential Author" not in raw_content
    assert b"Object Secret" not in raw_content
