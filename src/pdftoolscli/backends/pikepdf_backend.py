"""Pikepdf / libqpdf backend adapter implementation.

Conforms to PLAN.md §19, §26 (PDF-001).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

import pikepdf

from pdftoolscli.contracts.editing import (
    DocumentInfo,
    EncryptionSpec,
    OutlineNode,
    PageBox,
    PageInfo,
    SafeDocumentHandle,
)
from pdftoolscli.domain.errors import (
    PageBoundsError,
    PDFEncryptedError,
    PDFInvalidError,
)
from pdftoolscli.services.validation import CatalogValidator


class PikepdfDocumentHandle:
    """Safe handle wrapping a pikepdf.Pdf instance."""

    def __init__(self, path: Path | None, pdf: pikepdf.Pdf) -> None:
        self._path = path
        self._pdf: pikepdf.Pdf | None = pdf
        self._is_closed = False

    @property
    def path(self) -> Path | None:
        """Filesystem path if opened from disk."""
        return self._path

    @property
    def is_closed(self) -> bool:
        """True if the native resource handle has been released."""
        return self._is_closed

    @property
    def pdf(self) -> pikepdf.Pdf:
        """Access underlying pikepdf.Pdf object.

        Raises PDFInvalidError if closed.
        """
        if self._is_closed or self._pdf is None:
            raise PDFInvalidError("Attempted to access closed PDF document handle.")
        return self._pdf

    def close(self) -> None:
        """Release native C++ handles."""
        if not self._is_closed:
            if self._pdf is not None:
                with contextlib.suppress(Exception):
                    self._pdf.close()
                self._pdf = None
            self._is_closed = True

    def __enter__(self) -> PikepdfDocumentHandle:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


class PikepdfBackend:
    """Implementation of EditingBackend protocol wrapping pikepdf (libqpdf)."""

    def open_document(
        self,
        path: Path,
        password: str | None = None,
        recovery: bool = True,
    ) -> PikepdfDocumentHandle:
        """Open a PDF file safely with typed exception translation."""
        if not path.is_file():
            raise PDFInvalidError(f"PDF file not found: {path}")

        try:
            pdf = pikepdf.open(
                path,
                password=password or "",
                attempt_recovery=recovery,
            )
            return PikepdfDocumentHandle(path=path, pdf=pdf)
        except pikepdf.PasswordError as err:
            if password:
                raise PDFEncryptedError(
                    f"Invalid password for encrypted document '{path.name}'.",
                    code="E_PASSWORD_INVALID",
                    hint="Check that the password is correct.",
                ) from err
            raise PDFEncryptedError(
                f"Password required for encrypted document '{path.name}'.",
                code="E_PASSWORD_REQUIRED",
                hint=(
                    "Provide a password using --password-file, --password-env, or --password-stdin."
                ),
            ) from err
        except pikepdf.PdfError as err:
            raise PDFInvalidError(
                f"Failed to open PDF document '{path.name}': {err}",
                details={"path": str(path), "error": str(err)},
            ) from err

    def new_document(self) -> PikepdfDocumentHandle:
        """Create a new empty PDF document."""
        pdf = pikepdf.new()
        return PikepdfDocumentHandle(path=None, pdf=pdf)

    def _get_pdf(self, handle: SafeDocumentHandle) -> pikepdf.Pdf:
        if isinstance(handle, PikepdfDocumentHandle):
            return handle.pdf
        raise PDFInvalidError(f"Incompatible handle type: {type(handle)}")

    def get_document_info(self, handle: SafeDocumentHandle) -> DocumentInfo:
        """Extract high-level catalog structure and metadata."""
        pdf = self._get_pdf(handle)

        # 1. Encryption details
        is_encrypted = pdf.is_encrypted
        enc_algo: str | None = None
        if is_encrypted and "/Encrypt" in pdf.trailer:
            try:
                encrypt_dict = pdf.trailer["/Encrypt"]
                v_num = int(encrypt_dict.get("/V", 0))
                r_num = int(encrypt_dict.get("/R", 0))
                if r_num == 6 or v_num == 5:
                    enc_algo = "AES-256"
                elif r_num == 4 or v_num == 4:
                    enc_algo = "AES-128"
                elif r_num in (2, 3):
                    enc_algo = "RC4"
                else:
                    enc_algo = f"V{v_num}/R{r_num}"
            except Exception:  # noqa: BLE001
                enc_algo = "Standard"

        # 2. Metadata extraction
        metadata: dict[str, str] = {}
        if pdf.docinfo:
            for k, doc_val in pdf.docinfo.items():
                key_str = str(k).lstrip("/")
                val_str = str(doc_val)
                metadata[key_str] = val_str

        # 3. Catalog invariants
        has_signatures = CatalogValidator.has_digital_signatures(pdf)
        has_acroforms = CatalogValidator.has_acroforms(pdf)
        is_tagged = CatalogValidator.is_tagged_pdf(pdf)

        return DocumentInfo(
            path=handle.path,
            page_count=len(pdf.pages),
            pdf_version=pdf.pdf_version,
            is_encrypted=is_encrypted,
            encryption_algorithm=enc_algo,
            is_linearized=pdf.is_linearized,
            has_signatures=has_signatures,
            has_acroforms=has_acroforms,
            is_tagged=is_tagged,
            metadata=metadata,
        )

    def get_page_info(self, handle: SafeDocumentHandle, page_index: int) -> PageInfo:
        """Extract geometry and rotation for a 0-based page index."""
        pdf = self._get_pdf(handle)
        total = len(pdf.pages)
        if page_index < 0 or page_index >= total:
            raise PageBoundsError(
                f"Page index {page_index} out of bounds for document with {total} pages.",
                page=page_index + 1,
                page_count=total,
            )

        page = pdf.pages[page_index]
        mb = [float(v) for v in page.MediaBox]
        mediabox = PageBox(x0=mb[0], y0=mb[1], x1=mb[2], y1=mb[3])

        if "/CropBox" in page:
            cb = [float(v) for v in page["/CropBox"]]
            cropbox = PageBox(x0=cb[0], y0=cb[1], x1=cb[2], y1=cb[3])
        else:
            cropbox = mediabox

        rotation = int(page.get("/Rotate", 0)) % 360

        return PageInfo(
            page_number=page_index + 1,
            page_index=page_index,
            mediabox=mediabox,
            cropbox=cropbox,
            rotation=rotation,
        )

    def get_outlines(self, handle: SafeDocumentHandle) -> list[OutlineNode]:
        """Extract outline / bookmark hierarchy."""
        pdf = self._get_pdf(handle)
        nodes: list[OutlineNode] = []

        try:
            with pdf.open_outline() as outline:

                def _convert_item(item: Any) -> OutlineNode | None:
                    try:
                        title = str(item.title)
                        dest_page = item.destination
                        target_page = 1
                        if dest_page is not None:
                            try:
                                target_page = pdf.pages.index(dest_page) + 1
                            except (ValueError, KeyError, AttributeError):
                                target_page = 1
                        children: list[OutlineNode] = []
                        for child in getattr(item, "children", []):
                            c_node = _convert_item(child)
                            if c_node is not None:
                                children.append(c_node)
                        return OutlineNode(title=title, page_number=target_page, children=children)
                    except Exception:  # noqa: BLE001
                        return None

                for root_item in outline.root:
                    node = _convert_item(root_item)
                    if node is not None:
                        nodes.append(node)
        except Exception:  # noqa: BLE001
            return []

        return nodes

    def extract_pages(
        self,
        source_handle: SafeDocumentHandle,
        page_indices: list[int],
    ) -> PikepdfDocumentHandle:
        """Extract specific 0-based page indices into a new document."""
        source_pdf = self._get_pdf(source_handle)
        new_pdf = pikepdf.new()
        total = len(source_pdf.pages)

        for idx in page_indices:
            if idx < 0 or idx >= total:
                new_pdf.close()
                raise PageBoundsError(
                    f"Page index {idx} out of bounds (document has {total} pages).",
                    page=idx + 1,
                    page_count=total,
                )
            new_pdf.pages.append(source_pdf.pages[idx])

        return PikepdfDocumentHandle(path=None, pdf=new_pdf)

    def delete_pages(
        self,
        handle: SafeDocumentHandle,
        page_indices: list[int],
    ) -> None:
        """Delete specific 0-based page indices from document."""
        pdf = self._get_pdf(handle)
        total = len(pdf.pages)

        unique_indices = sorted(set(page_indices), reverse=True)
        for idx in unique_indices:
            if idx < 0 or idx >= total:
                raise PageBoundsError(
                    f"Page index {idx} out of bounds for document with {total} pages.",
                    page=idx + 1,
                    page_count=total,
                )

        if len(unique_indices) >= total:
            raise PageBoundsError(
                "Cannot delete all pages from document. A PDF must have at least one page.",
                page_count=total,
            )

        for idx in unique_indices:
            del pdf.pages[idx]

    def reorder_pages(
        self,
        handle: SafeDocumentHandle,
        new_order: list[int],
    ) -> None:
        """Reorder pages according to list of 0-based page indices."""
        pdf = self._get_pdf(handle)
        total = len(pdf.pages)

        for idx in new_order:
            if idx < 0 or idx >= total:
                raise PageBoundsError(
                    f"Page index {idx} out of bounds (document has {total} pages).",
                    page=idx + 1,
                    page_count=total,
                )

        pdf.pages[:] = [pdf.pages[i] for i in new_order]

    def rotate_pages(
        self,
        handle: SafeDocumentHandle,
        page_indices: list[int],
        angle: int,
        relative: bool = True,
    ) -> None:
        """Rotate specific page indices by angle (CW)."""
        pdf = self._get_pdf(handle)
        total = len(pdf.pages)
        norm_angle = angle % 360

        for idx in page_indices:
            if idx < 0 or idx >= total:
                raise PageBoundsError(
                    f"Page index {idx} out of bounds (document has {total} pages).",
                    page=idx + 1,
                    page_count=total,
                )
            if relative:
                current = int(pdf.pages[idx].get("/Rotate", 0))
                pdf.pages[idx].Rotate = (current + norm_angle) % 360
            else:
                pdf.pages[idx].Rotate = norm_angle

    def copy_foreign_pages(
        self,
        source_handle: SafeDocumentHandle,
        target_handle: SafeDocumentHandle,
        source_indices: list[int],
    ) -> None:
        """Copy foreign pages from source document into target document."""
        source_pdf = self._get_pdf(source_handle)
        target_pdf = self._get_pdf(target_handle)
        total = len(source_pdf.pages)

        for idx in source_indices:
            if idx < 0 or idx >= total:
                raise PageBoundsError(
                    f"Source page index {idx} out of bounds (source has {total} pages).",
                    page=idx + 1,
                    page_count=total,
                )
            target_pdf.pages.append(source_pdf.pages[idx])

    def save(
        self,
        handle: SafeDocumentHandle,
        target_path: Path,
        encryption: EncryptionSpec | None = None,
        linearize: bool = False,
    ) -> None:
        """Save document to filesystem with optional encryption and linearization."""
        pdf = self._get_pdf(handle)

        enc: pikepdf.Encryption | None = None
        if encryption is not None:
            r_val: Literal[2, 3, 4, 5, 6] = 6 if encryption.algorithm.lower() == "aes256" else 4
            perms = pikepdf.Permissions(
                accessibility=True,
                print_highres=encryption.allow_print,
                print_lowres=encryption.allow_print,
                extract=encryption.allow_copy,
                modify_annotation=encryption.allow_annotations,
                modify_form=encryption.allow_modify,
                modify_assembly=encryption.allow_modify,
                modify_other=encryption.allow_modify,
            )
            enc = pikepdf.Encryption(
                owner=encryption.owner_password or "",
                user=encryption.user_password or "",
                R=r_val,
                allow=perms,
            )

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if enc is not None:
                pdf.save(target_path, encryption=enc, linearize=linearize)
            else:
                pdf.save(target_path, linearize=linearize)
        except Exception as err:
            raise PDFInvalidError(
                f"Failed to save PDF to '{target_path.name}': {err}",
                details={"target_path": str(target_path), "error": str(err)},
            ) from err
