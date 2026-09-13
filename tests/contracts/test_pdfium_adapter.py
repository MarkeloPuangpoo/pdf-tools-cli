"""Contract and integration tests for PdfiumBackend (PDF-002).

Conforms to PLAN.md §19, §26 (PDF-002).
"""

# ruff: noqa: S106

from __future__ import annotations

import io
import multiprocessing as mp
import os
from pathlib import Path
from typing import Any

import psutil
import pytest
from PIL import Image

from pdftoolscli.backends.pdfium_backend import PdfiumBackend
from pdftoolscli.contracts.rendering import RenderSpec
from pdftoolscli.contracts.text import TextExtractSpec
from pdftoolscli.domain.errors import (
    PageBoundsError,
    PDFEncryptedError,
    PDFInvalidError,
    ResourceLimitError,
)


@pytest.fixture
def backend() -> PdfiumBackend:
    return PdfiumBackend()


def test_render_single_and_multi_page(backend: PdfiumBackend, fixtures_dir: Path) -> None:
    single_pdf = fixtures_dir / "single_page.pdf"

    # Render at 150 DPI PNG
    spec = RenderSpec(dpi=150, format="png")
    result = backend.render_page(single_pdf, 0, spec)

    assert result.page_index == 0
    assert result.page_number == 1
    assert result.dpi == 150
    assert result.format == "png"
    assert result.width_px > 0
    assert result.height_px > 0
    assert result.image_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # Verify Pillow can open it
    img = Image.open(io.BytesIO(result.image_bytes))
    assert img.size == (result.width_px, result.height_px)
    assert img.mode == "RGB"

    # Multi-page render
    multi_pdf = fixtures_dir / "multi_page.pdf"
    results = backend.render_document(multi_pdf, [0, 1, 2], RenderSpec(dpi=72, format="png"))
    assert len(results) == 3
    assert [r.page_index for r in results] == [0, 1, 2]

    # Out of bounds render
    with pytest.raises(PageBoundsError):
        backend.render_page(single_pdf, 99, spec)


def test_render_formats_and_alpha(backend: PdfiumBackend, fixtures_dir: Path) -> None:
    single_pdf = fixtures_dir / "single_page.pdf"

    # 1. JPEG format
    jpg_spec = RenderSpec(dpi=72, format="jpeg")
    jpg_res = backend.render_page(single_pdf, 0, jpg_spec)
    assert jpg_res.image_bytes.startswith(b"\xff\xd8")
    assert jpg_res.format == "jpeg"

    # 2. WebP format
    webp_spec = RenderSpec(dpi=72, format="webp")
    webp_res = backend.render_page(single_pdf, 0, webp_spec)
    assert webp_res.image_bytes.startswith(b"RIFF")
    assert webp_res.format == "webp"

    # 3. TIFF format
    tiff_spec = RenderSpec(dpi=72, format="tiff")
    tiff_res = backend.render_page(single_pdf, 0, tiff_spec)
    assert tiff_res.image_bytes.startswith((b"II*\x00", b"MM\x00*"))
    assert tiff_res.format == "tiff"

    # 4. Transparent RGBA mode
    alpha_spec = RenderSpec(dpi=72, format="png", alpha=True)
    alpha_res = backend.render_page(single_pdf, 0, alpha_spec)
    alpha_img = Image.open(io.BytesIO(alpha_res.image_bytes))
    assert alpha_img.mode == "RGBA"


def test_render_dpi_bounds(backend: PdfiumBackend, fixtures_dir: Path) -> None:
    single_pdf = fixtures_dir / "single_page.pdf"

    # Lower DPI out of bounds (< 36)
    with pytest.raises(ValueError, match="DPI must be between"):
        RenderSpec(dpi=20)

    # Upper DPI out of bounds (> 2400)
    with pytest.raises(ValueError, match="DPI must be between"):
        RenderSpec(dpi=3000)

    # Pre-allocation limit guard: 2400 DPI on a standard Letter page exceeds 100M pixels
    large_spec = RenderSpec(dpi=2400, format="png")
    with pytest.raises(ResourceLimitError) as exc_info:
        backend.render_page(single_pdf, 0, large_spec)
    assert "exceeding maximum allowed" in str(exc_info.value)


def test_text_extraction(backend: PdfiumBackend, fixtures_dir: Path) -> None:
    text_pdf = fixtures_dir / "text_sample.pdf"

    # Standard plain text extraction
    spec = TextExtractSpec(include_page_breaks=True, include_boxes=False)
    res = backend.extract_page_text(text_pdf, 0, spec)

    assert res.page_index == 0
    assert res.page_number == 1
    assert "Quarterly Financial Report" in res.text
    assert res.text.endswith("\x0c")
    assert res.char_count == len(res.text)
    assert len(res.boxes) == 0

    # Text extraction with bounding boxes
    box_spec = TextExtractSpec(include_page_breaks=False, include_boxes=True)
    box_res = backend.extract_page_text(text_pdf, 0, box_spec)
    assert not box_res.text.endswith("\x0c")
    assert len(box_res.boxes) > 0

    first_box = box_res.boxes[0]
    assert first_box.text != ""
    assert first_box.x1 > first_box.x0
    assert first_box.y1 > first_box.y0

    # Multi-page extraction
    all_pages = backend.extract_document_text(text_pdf, [0, 1], spec)
    assert len(all_pages) == 2


def test_encrypted_document_handling(backend: PdfiumBackend, fixtures_dir: Path) -> None:
    enc_pdf = fixtures_dir / "encrypted_aes256.pdf"

    # Without password -> E_PASSWORD_REQUIRED
    with pytest.raises(PDFEncryptedError) as exc_info:
        backend.render_page(enc_pdf, 0, RenderSpec(dpi=72))
    assert exc_info.value.code == "E_PASSWORD_REQUIRED"

    # With incorrect password -> E_PASSWORD_INVALID
    with pytest.raises(PDFEncryptedError) as exc_info2:
        backend.render_page(enc_pdf, 0, RenderSpec(dpi=72), password="wrong_password")
    assert exc_info2.value.code == "E_PASSWORD_INVALID"

    # With correct password -> renders and extracts text successfully
    res = backend.render_page(enc_pdf, 0, RenderSpec(dpi=72), password="userpass123")
    assert res.width_px > 0

    txt_res = backend.extract_page_text(enc_pdf, 0, TextExtractSpec(), password="userpass123")
    assert txt_res.char_count > 0


def test_malformed_file_handling(backend: PdfiumBackend, tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.pdf"
    with pytest.raises(PDFInvalidError) as exc_info:
        backend.render_page(missing, 0, RenderSpec(dpi=72))
    assert "not found" in str(exc_info.value)

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"garbage not a valid pdf at all")
    with pytest.raises(PDFInvalidError) as exc_info2:
        backend.render_page(corrupt, 0, RenderSpec(dpi=72))
    assert exc_info2.value.code == "E_PDF_INVALID"


def _isolated_worker_render(pdf_path_str: str, page_idx: int, dpi: int, out_queue: Any) -> None:
    """Isolated process function for concurrency testing."""
    try:
        b = PdfiumBackend()
        r = b.render_page(Path(pdf_path_str), page_idx, RenderSpec(dpi=dpi, format="png"))
        out_queue.put({"success": True, "size": (r.width_px, r.height_px)})
    except Exception as exc:  # noqa: BLE001
        out_queue.put({"success": False, "error": str(exc)})


def test_process_isolation_concurrency(fixtures_dir: Path) -> None:
    """Verify concurrent spawned worker processes running PDFium without crashes."""
    pdf_path = fixtures_dir / "multi_page.pdf"
    ctx = mp.get_context("spawn")
    queue: Any = ctx.Queue()

    processes: list[Any] = []
    # Spawn 4 concurrent processes rendering different pages & DPIs
    configs = [(0, 72), (1, 100), (2, 150), (3, 72)]
    for page_idx, dpi in configs:
        p = ctx.Process(
            target=_isolated_worker_render,
            args=(str(pdf_path), page_idx, dpi, queue),
        )
        processes.append(p)
        p.start()

    for p in processes:
        p.join(timeout=10.0)
        assert p.exitcode == 0

    results: list[dict[str, Any]] = []
    while not queue.empty():
        results.append(queue.get_nowait())

    assert len(results) == 4
    for r in results:
        assert r["success"] is True
        assert r["size"][0] > 0


def test_zero_handle_leakage(backend: PdfiumBackend, fixtures_dir: Path) -> None:
    """Verify repeated rendering cycles do not leak memory or native handles."""
    pdf_path = fixtures_dir / "single_page.pdf"
    spec = RenderSpec(dpi=72, format="png")

    process = psutil.Process(os.getpid())
    initial_rss = process.memory_info().rss

    for _ in range(50):
        res = backend.render_page(pdf_path, 0, spec)
        assert len(res.image_bytes) > 0

    final_rss = process.memory_info().rss
    rss_growth_mb = (final_rss - initial_rss) / (1024 * 1024)
    # Memory growth must remain under 20 MB across 50 render cycles
    assert rss_growth_mb < 20.0
