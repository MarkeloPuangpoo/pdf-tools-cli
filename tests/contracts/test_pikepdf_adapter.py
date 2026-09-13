"""Contract and integration tests for PikepdfBackend (PDF-001).

Conforms to PLAN.md §19, §26 (PDF-001).
"""

# ruff: noqa: S106

from __future__ import annotations

import os
from pathlib import Path

import psutil
import pytest

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.contracts.editing import EncryptionSpec
from pdftoolscli.domain.errors import (
    PageBoundsError,
    PDFCorruptionError,
    PDFEncryptedError,
    PDFInvalidError,
)
from pdftoolscli.services.validation import (
    CandidateOutputValidator,
    CatalogValidator,
)


@pytest.fixture
def backend() -> PikepdfBackend:
    return PikepdfBackend()


def test_open_valid_fixtures(backend: PikepdfBackend, fixtures_dir: Path) -> None:
    # 1. Single page fixture
    single_pdf = fixtures_dir / "single_page.pdf"
    with backend.open_document(single_pdf) as handle:
        info = backend.get_document_info(handle)
        assert info.page_count == 1
        assert not info.is_encrypted
        assert info.pdf_version.startswith("1.")

        page_info = backend.get_page_info(handle, 0)
        assert page_info.page_number == 1
        assert page_info.page_index == 0
        assert page_info.rotation == 0
        assert page_info.mediabox.width > 0
        assert page_info.mediabox.height > 0

    # 2. Multi-page fixture
    multi_pdf = fixtures_dir / "multi_page.pdf"
    with backend.open_document(multi_pdf) as handle:
        info = backend.get_document_info(handle)
        assert info.page_count == 5

    # 3. Rotated pages fixture (0, 90, 180, 270)
    rotated_pdf = fixtures_dir / "rotated_pages.pdf"
    with backend.open_document(rotated_pdf) as handle:
        info = backend.get_document_info(handle)
        assert info.page_count == 4
        assert backend.get_page_info(handle, 0).rotation == 0
        assert backend.get_page_info(handle, 1).rotation == 90
        assert backend.get_page_info(handle, 2).rotation == 180
        assert backend.get_page_info(handle, 3).rotation == 270

    # 4. Outlines fixture
    outlines_pdf = fixtures_dir / "outlines_sample.pdf"
    with backend.open_document(outlines_pdf) as handle:
        outlines = backend.get_outlines(handle)
        titles = [node.title for node in outlines]
        assert "Chapter 1" in titles
        assert "Chapter 2" in titles
        assert "Chapter 3" in titles

    # 5. Metadata fixture
    meta_pdf = fixtures_dir / "metadata_sample.pdf"
    with backend.open_document(meta_pdf) as handle:
        info = backend.get_document_info(handle)
        assert "Title" in info.metadata
        assert "Jane Doe" in info.metadata.get("Author", "")


def test_password_protected_document(backend: PikepdfBackend, fixtures_dir: Path) -> None:
    enc_pdf = fixtures_dir / "encrypted_aes256.pdf"

    # Opening without password should raise PDFEncryptedError with code E_PASSWORD_REQUIRED
    with pytest.raises(PDFEncryptedError) as exc_info:
        backend.open_document(enc_pdf)
    assert exc_info.value.code == "E_PASSWORD_REQUIRED"

    # Opening with wrong password should raise PDFEncryptedError with code E_PASSWORD_INVALID
    with pytest.raises(PDFEncryptedError) as exc_info2:
        backend.open_document(enc_pdf, password="incorrect_pass")
    assert exc_info2.value.code == "E_PASSWORD_INVALID"

    # Opening with correct password should succeed
    with backend.open_document(enc_pdf, password="userpass123") as handle:
        info = backend.get_document_info(handle)
        assert info.is_encrypted
        assert info.encryption_algorithm == "AES-256"
        assert info.page_count == 1


def test_malformed_document_handling(backend: PikepdfBackend, tmp_path: Path) -> None:
    # 1. Non-existent file
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(PDFInvalidError) as exc_info:
        backend.open_document(missing)
    assert "not found" in str(exc_info.value)

    # 2. Garbage corrupted file
    corrupt = tmp_path / "corrupted.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nRandom unparseable binary garbage data here\n%%EOF")
    with pytest.raises(PDFInvalidError) as exc_info2:
        backend.open_document(corrupt)
    assert exc_info2.value.code == "E_PDF_INVALID"


def test_page_topology_operations(backend: PikepdfBackend, fixtures_dir: Path) -> None:
    multi_pdf = fixtures_dir / "multi_page.pdf"

    # 1. Extract pages (0, 2, 4 -> pages 1, 3, 5)
    with backend.open_document(multi_pdf) as handle:
        extracted = backend.extract_pages(handle, [0, 2, 4])
        assert backend.get_document_info(extracted).page_count == 3
        extracted.close()

        # Out of bounds extract
        with pytest.raises(PageBoundsError):
            backend.extract_pages(handle, [0, 99])

    # 2. Delete pages
    doc = backend.new_document()
    # Populate with 3 blank pages from single_page
    with backend.open_document(fixtures_dir / "single_page.pdf") as src:
        backend.copy_foreign_pages(src, doc, [0])
        backend.copy_foreign_pages(src, doc, [0])
        backend.copy_foreign_pages(src, doc, [0])
    assert backend.get_document_info(doc).page_count == 3

    # Delete middle page
    backend.delete_pages(doc, [1])
    assert backend.get_document_info(doc).page_count == 2

    # Attempt to delete remaining all pages -> error
    with pytest.raises(PageBoundsError):
        backend.delete_pages(doc, [0, 1])

    # 3. Rotate pages
    backend.rotate_pages(doc, [0], 90)
    assert backend.get_page_info(doc, 0).rotation == 90
    backend.rotate_pages(doc, [0], 90)
    assert backend.get_page_info(doc, 0).rotation == 180

    doc.close()


def test_reorder_pages(backend: PikepdfBackend, fixtures_dir: Path) -> None:
    multi_pdf = fixtures_dir / "multi_page.pdf"
    with backend.open_document(multi_pdf) as handle:
        extracted = backend.extract_pages(handle, [0, 1, 2])
        # Reorder to [2, 0, 1]
        backend.reorder_pages(extracted, [2, 0, 1])
        assert backend.get_document_info(extracted).page_count == 3

        # Invalid index in reorder
        with pytest.raises(PageBoundsError):
            backend.reorder_pages(extracted, [0, 1, 5])

        extracted.close()


def test_foreign_page_copy_and_save(
    backend: PikepdfBackend, fixtures_dir: Path, tmp_path: Path
) -> None:
    doc1 = backend.open_document(fixtures_dir / "single_page.pdf")
    doc2 = backend.open_document(fixtures_dir / "rotated_pages.pdf")
    target = backend.new_document()

    # Copy 1 page from doc1 and 2 pages from doc2
    backend.copy_foreign_pages(doc1, target, [0])
    backend.copy_foreign_pages(doc2, target, [0, 1])

    out_file = tmp_path / "combined.pdf"
    backend.save(target, out_file)

    doc1.close()
    doc2.close()
    target.close()

    # Verify saved file
    CandidateOutputValidator.verify_candidate_output(out_file, expected_page_count=3)

    with backend.open_document(out_file) as reopened:
        info = backend.get_document_info(reopened)
        assert info.page_count == 3
        assert backend.get_page_info(reopened, 2).rotation == 90


def test_save_with_encryption(backend: PikepdfBackend, fixtures_dir: Path, tmp_path: Path) -> None:
    src_file = fixtures_dir / "single_page.pdf"
    enc_out = tmp_path / "encrypted_output.pdf"

    with backend.open_document(src_file) as handle:
        spec = EncryptionSpec(
            user_password="userSecret123",
            owner_password="ownerSecret456",
            algorithm="aes256",
            allow_print=True,
            allow_copy=False,
        )
        backend.save(handle, enc_out, encryption=spec)

    # Candidate validation
    CandidateOutputValidator.verify_candidate_output(
        enc_out,
        expected_page_count=1,
        expected_encrypted=True,
        password="userSecret123",
    )

    # Verify locked without password
    with pytest.raises(PDFEncryptedError):
        backend.open_document(enc_out)

    # Verify unlocked with user password
    with backend.open_document(enc_out, password="userSecret123") as handle2:
        info = backend.get_document_info(handle2)
        assert info.is_encrypted
        assert info.encryption_algorithm == "AES-256"


def test_catalog_invariants_and_candidate_validation(fixtures_dir: Path, tmp_path: Path) -> None:
    # 1. Check digital signature detection on unsigned document
    single_pdf = fixtures_dir / "single_page.pdf"
    backend = PikepdfBackend()
    with backend.open_document(single_pdf) as handle:
        assert not CatalogValidator.has_digital_signatures(handle.pdf)
        assert not CatalogValidator.has_acroforms(handle.pdf)

    # 2. Candidate output validator on valid file
    CandidateOutputValidator.verify_candidate_output(single_pdf, expected_page_count=1)

    # 3. Candidate output validator with mismatch page count
    with pytest.raises(PDFCorruptionError) as exc_info:
        CandidateOutputValidator.verify_candidate_output(single_pdf, expected_page_count=99)
    assert "page count mismatch" in str(exc_info.value)

    # 4. Candidate output validator on corrupted file
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"corrupt junk data")
    with pytest.raises(PDFCorruptionError):
        CandidateOutputValidator.verify_candidate_output(bad_pdf)


def test_handle_lifecycle_and_memory_stability(backend: PikepdfBackend, fixtures_dir: Path) -> None:
    sample = fixtures_dir / "multi_page.pdf"

    # Context manager cleans up handle
    handle = backend.open_document(sample)
    with handle:
        assert not handle.is_closed
        assert handle.pdf is not None
    assert handle.is_closed

    # Accessing closed handle raises
    with pytest.raises(PDFInvalidError):
        _ = handle.pdf

    # Stress test: Open & close 100 documents in a loop and verify RSS memory remains stable
    process = psutil.Process(os.getpid())
    initial_rss = process.memory_info().rss

    for _ in range(100):
        with backend.open_document(sample) as doc:
            _ = backend.get_document_info(doc)
            _ = backend.get_page_info(doc, 0)

    final_rss = process.memory_info().rss
    # Allow maximum 25 MB RSS variance across 100 cycles to account for Python GC
    rss_growth_mb = (final_rss - initial_rss) / (1024 * 1024)
    assert rss_growth_mb < 25.0
