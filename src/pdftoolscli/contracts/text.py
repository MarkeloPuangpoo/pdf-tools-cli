"""Plain text extraction domain contracts, specs, and protocols.

Conforms to PLAN.md §19, §26 (PDF-002).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TextBox:
    """Bounding box for an extracted character or text segment."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class TextExtractSpec:
    """Configuration for plain text extraction."""

    include_page_breaks: bool = True  # Standard PDF form-feed (\x0c) delimiter
    include_boxes: bool = False


@dataclass(frozen=True)
class TextPageResult:
    """Extracted text result for a single document page."""

    page_index: int
    page_number: int
    text: str
    char_count: int
    boxes: list[TextBox] = field(default_factory=list)


@runtime_checkable
class TextExtractor(Protocol):
    """Protocol for plain text extraction engines."""

    def extract_page_text(
        self,
        path: Path,
        page_index: int,
        spec: TextExtractSpec,
        password: str | None = None,
    ) -> TextPageResult:
        """Extract UTF-8 text from a single page."""
        ...

    def extract_document_text(
        self,
        path: Path,
        page_indices: list[int],
        spec: TextExtractSpec,
        password: str | None = None,
    ) -> list[TextPageResult]:
        """Extract UTF-8 text from multiple pages."""
        ...
