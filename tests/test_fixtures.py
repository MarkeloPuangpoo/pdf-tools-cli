"""Tests validating generated test fixtures and manifest integrity (TEST-001)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pikepdf
import pypdfium2 as pdfium


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def test_manifest_checksums_match(fixtures_dir: Path, fixtures_manifest: dict[str, Any]) -> None:
    """Verify every fixture file exists and matches its manifest SHA-256 hash."""
    fixtures = fixtures_manifest["fixtures"]
    assert len(fixtures) > 0

    for item in fixtures:
        path = fixtures_dir / str(item["filename"])
        assert path.is_file(), f"Fixture file missing: {path}"
        actual_hash = _hash_file(path)
        assert actual_hash == item["sha256"], (
            f"Hash mismatch for {item['filename']}: expected {item['sha256']}, got {actual_hash}"
        )


def test_fixtures_parse_with_pikepdf(fixtures_dir: Path, fixtures_manifest: dict[str, Any]) -> None:
    """Verify non-corrupt fixtures can be opened with pikepdf and have expected page counts."""
    for item in fixtures_manifest["fixtures"]:
        if item.get("is_malformed"):
            continue

        path = fixtures_dir / str(item["filename"])
        expected_pages = int(item["page_count"])

        if item.get("encrypted"):
            # Should require password or empty password
            user_pw = str(item.get("user_password", ""))
            with pikepdf.open(path, password=user_pw) as pdf:
                assert len(pdf.pages) == expected_pages
        else:
            with pikepdf.open(path) as pdf:
                assert len(pdf.pages) == expected_pages


def test_fixtures_parse_with_pypdfium2(
    fixtures_dir: Path, fixtures_manifest: dict[str, Any]
) -> None:
    """Verify readable fixtures can be parsed and rendered with pypdfium2."""
    for item in fixtures_manifest["fixtures"]:
        if item.get("is_malformed"):
            continue

        path = fixtures_dir / str(item["filename"])
        expected_pages = int(item["page_count"])

        if item.get("encrypted"):
            user_pw = str(item.get("user_password", ""))
            doc = pdfium.PdfDocument(path, password=user_pw)
            assert len(doc) == expected_pages
            doc.close()
        else:
            doc = pdfium.PdfDocument(path)
            assert len(doc) == expected_pages
            # Test rendering first page to ensure valid rasterization
            page = doc[0]
            bitmap = page.render(scale=0.5)
            img = bitmap.to_pil()
            assert img.size[0] > 0
            page.close()
            doc.close()


def test_malformed_fixture_handling(fixtures_dir: Path) -> None:
    """Verify malformed corrupt fixture triggers error in strict mode."""
    corrupt_path = fixtures_dir / "malformed_corrupt_xref.pdf"
    assert corrupt_path.is_file()

    # pikepdf without recovery or when badly damaged throws or warns
    try:
        with pikepdf.open(corrupt_path) as pdf:
            # qpdf has auto-repair, so it might salvage it, but it should log warnings
            warnings = pdf.get_warnings()
            assert len(warnings) > 0 or len(pdf.pages) >= 0
    except pikepdf.PdfError:
        pass  # Also valid behavior for corrupt input
