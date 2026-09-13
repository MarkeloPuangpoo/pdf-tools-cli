"""Rendering backend domain contracts, specs, and protocols.

Conforms to PLAN.md §19, §26 (PDF-002).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

# Default upper limit for decoded/rasterized pixels per page (100 Megapixels per PLAN.md §31)
MAX_PIXELS_PER_PAGE = 100_000_000
MIN_DPI = 36
MAX_DPI = 2400


@dataclass(frozen=True)
class RenderSpec:
    """Configuration for page rasterization."""

    dpi: int = 150
    format: str = "png"
    alpha: bool = False
    bg_color: tuple[int, int, int] = (255, 255, 255)
    scale: float | None = None
    quality: int = 85
    colorspace: str = "rgb"

    def __post_init__(self) -> None:
        if not (MIN_DPI <= self.dpi <= MAX_DPI):
            raise ValueError(f"DPI must be between {MIN_DPI} and {MAX_DPI}, got {self.dpi}")
        if self.colorspace not in ("rgb", "gray"):
            raise ValueError(f"Unsupported colorspace '{self.colorspace}'. Allowed: rgb, gray.")
        if not (0 <= self.quality <= 100):
            raise ValueError(f"Quality must be between 0 and 100, got {self.quality}")


@dataclass(frozen=True)
class RenderResult:
    """Rasterized page output record."""

    page_index: int
    page_number: int
    width_px: int
    height_px: int
    dpi: int
    format: str
    image_bytes: bytes


@runtime_checkable
class Renderer(Protocol):
    """Protocol for document page rasterization engines."""

    def render_page(
        self,
        path: Path,
        page_index: int,
        spec: RenderSpec,
        password: str | None = None,
    ) -> RenderResult:
        """Render a single page to bitmap image bytes."""
        ...

    def render_document(
        self,
        path: Path,
        page_indices: list[int],
        spec: RenderSpec,
        password: str | None = None,
    ) -> list[RenderResult]:
        """Render multiple pages in sequence."""
        ...
