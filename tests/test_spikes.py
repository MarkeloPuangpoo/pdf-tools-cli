"""Test suite verifying backend spikes and native library functionality (ARCH-002)."""

from __future__ import annotations

from scripts.spike_pdfium import (
    test_basic_pdfium_rendering,
    test_process_isolation_concurrency,
    test_text_page_extraction,
)
from scripts.spike_pikepdf import (
    test_basic_creation_and_pages,
    test_encryption_decryption,
    test_foreign_page_copy,
    test_malformed_stream_handling,
)


def test_pikepdf_spikes() -> None:
    """Run all pikepdf spike tests."""
    test_basic_creation_and_pages()
    test_foreign_page_copy()
    test_encryption_decryption()
    test_malformed_stream_handling()


def test_pdfium_spikes() -> None:
    """Run all pypdfium2 spike tests."""
    test_basic_pdfium_rendering()
    test_text_page_extraction()
    test_process_isolation_concurrency()
