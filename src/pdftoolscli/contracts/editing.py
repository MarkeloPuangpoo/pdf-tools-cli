"""Editing backend domain contracts, data models, and protocols.

Conforms to PLAN.md §19, §26 (PDF-001).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PageBox:
    """PDF rectangle boundary representation (e.g. MediaBox, CropBox)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        """Width of the page box."""
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        """Height of the page box."""
        return abs(self.y1 - self.y0)


@dataclass(frozen=True)
class PageInfo:
    """Structural and geometric metadata for a single PDF page."""

    page_number: int  # 1-based human indexing
    page_index: int  # 0-based internal indexing
    mediabox: PageBox
    cropbox: PageBox
    rotation: int  # 0, 90, 180, or 270


@dataclass(frozen=True)
class OutlineNode:
    """A bookmark or outline hierarchy element."""

    title: str
    page_number: int  # 1-based target page
    children: list[OutlineNode] = field(default_factory=list)


@dataclass(frozen=True)
class DocumentInfo:
    """Complete document-level inspection and structural catalog summary."""

    path: Path | None
    page_count: int
    pdf_version: str
    is_encrypted: bool
    encryption_algorithm: str | None = None
    is_linearized: bool = False
    has_signatures: bool = False
    has_acroforms: bool = False
    is_tagged: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EncryptionSpec:
    """Target encryption parameters for document saving."""

    user_password: str | None = None
    owner_password: str | None = None
    algorithm: str = "aes256"  # "aes256" or "aes128"
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = False
    allow_annotations: bool = True


@runtime_checkable
class SafeDocumentHandle(Protocol):
    """Lifetime-safe handle to an open PDF document resource."""

    @property
    def path(self) -> Path | None:
        """Filesystem source path if opened from disk, or None if in-memory."""
        ...

    @property
    def is_closed(self) -> bool:
        """True if the native resource handle has been released."""
        ...

    def close(self) -> None:
        """Explicitly release native C++ and file descriptor resources."""
        ...

    def __enter__(self) -> SafeDocumentHandle:
        """Enter context manager scope."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager scope and close resource."""
        ...


@runtime_checkable
class EditingBackend(Protocol):
    """Protocol for structural PDF manipulation and catalog operations."""

    def open_document(
        self,
        path: Path,
        password: str | None = None,
        recovery: bool = True,
    ) -> SafeDocumentHandle:
        """Open a PDF document safely with error mapping and lifetime tracking."""
        ...

    def new_document(self) -> SafeDocumentHandle:
        """Create a new empty in-memory PDF document."""
        ...

    def get_document_info(self, handle: SafeDocumentHandle) -> DocumentInfo:
        """Extract high-level catalog structure and metadata."""
        ...

    def get_page_info(self, handle: SafeDocumentHandle, page_index: int) -> PageInfo:
        """Extract geometry and rotation for a specific 0-based page index."""
        ...

    def get_outlines(self, handle: SafeDocumentHandle) -> list[OutlineNode]:
        """Extract bookmark / outline hierarchy."""
        ...

    def extract_pages(
        self,
        source_handle: SafeDocumentHandle,
        page_indices: list[int],
    ) -> SafeDocumentHandle:
        """Extract a sequence of pages into a new document handle."""
        ...

    def delete_pages(
        self,
        handle: SafeDocumentHandle,
        page_indices: list[int],
    ) -> None:
        """Delete specific 0-based page indices from the document."""
        ...

    def reorder_pages(
        self,
        handle: SafeDocumentHandle,
        new_order: list[int],
    ) -> None:
        """Reorder document pages according to a new index mapping."""
        ...

    def rotate_pages(
        self,
        handle: SafeDocumentHandle,
        page_indices: list[int],
        angle: int,
    ) -> None:
        """Rotate specified 0-based page indices by angle (90, 180, 270 degrees CW)."""
        ...

    def copy_foreign_pages(
        self,
        source_handle: SafeDocumentHandle,
        target_handle: SafeDocumentHandle,
        source_indices: list[int],
    ) -> None:
        """Copy foreign pages from source document into target document safely."""
        ...

    def save(
        self,
        handle: SafeDocumentHandle,
        target_path: Path,
        encryption: EncryptionSpec | None = None,
        linearize: bool = False,
    ) -> None:
        """Save document to filesystem with optional encryption and linearization."""
        ...
