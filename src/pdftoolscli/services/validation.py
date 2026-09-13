"""Document catalog invariants, digital signature detection, and candidate verification.

Conforms to PLAN.md §19, §26 (PDF-001).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.domain.errors import (
    PDFCorruptionError,
    PDFInvalidError,
)


class CatalogValidator:
    """Validator for PDF document catalog structures and invariant preservation."""

    @staticmethod
    def has_digital_signatures(pdf: pikepdf.Pdf) -> bool:
        """Detect digital signatures, approval signatures, or DocMDP locks."""
        root = pdf.Root

        # 1. Check Root Permissions dictionary (/Perms)
        if "/Perms" in root:
            perms = root["/Perms"]
            if any(key in perms for key in ("/DocMDP", "/UR", "/UR3", "/SigPerms")):
                return True

        # 2. Check SigFlags in AcroForm
        if "/AcroForm" in root:
            acro = root["/AcroForm"]
            sig_flags = int(acro.get("/SigFlags", 0))
            # Bit 1 (value 1) indicates document contains at least one signature field
            if sig_flags & 1:
                return True

            # 3. Check Fields for signature field type (/FT /Sig)
            if "/Fields" in acro:
                for field_ref in acro["/Fields"]:
                    try:
                        field_obj = field_ref
                        if field_obj.get("/FT") == pikepdf.Name("/Sig") and "/V" in field_obj:
                            return True
                    except (pikepdf.PdfError, AttributeError, KeyError):
                        continue

        # 4. Check Annots on pages for Widget with Sig
        for page in pdf.pages:
            if "/Annots" in page:
                for annot_ref in page["/Annots"]:
                    try:
                        annot_obj = annot_ref
                        if (
                            annot_obj.get("/Subtype") == pikepdf.Name("/Widget")
                            and annot_obj.get("/FT") == pikepdf.Name("/Sig")
                            and "/V" in annot_obj
                        ):
                            return True
                    except (pikepdf.PdfError, AttributeError, KeyError):
                        continue

        return False

    @staticmethod
    def is_tagged_pdf(pdf: pikepdf.Pdf) -> bool:
        """Check whether the PDF catalog indicates a Tagged PDF."""
        root = pdf.Root
        if "/MarkInfo" in root:
            try:
                mark_info = root["/MarkInfo"]
                return bool(mark_info.get("/Marked", False))
            except (pikepdf.PdfError, AttributeError):
                return False
        return False

    @staticmethod
    def has_acroforms(pdf: pikepdf.Pdf) -> bool:
        """Check whether the document contains AcroForm interactive form fields."""
        root = pdf.Root
        if "/AcroForm" in root:
            try:
                acro = root["/AcroForm"]
                fields: Any = acro.get("/Fields", [])
                return len(fields) > 0
            except (pikepdf.PdfError, AttributeError):
                return False
        return False

    @staticmethod
    def has_layers(pdf: pikepdf.Pdf) -> bool:
        """Check whether the document contains Optional Content Groups (layers)."""
        return "/OCProperties" in pdf.Root


class CandidateOutputValidator:
    """Re-opens candidate output files to verify xref integrity and invariants."""

    @staticmethod
    def verify_candidate_output(
        path: Path,
        expected_page_count: int | None = None,
        expected_encrypted: bool | None = None,
        password: str | None = None,
    ) -> None:
        """Reopen a staged output file with recovery disabled to verify integrity."""
        if not path.is_file():
            raise PDFInvalidError(f"Candidate output file not found: {path}")

        try:
            # Reopen with attempt_recovery=False to detect damaged xref or structure
            pdf = pikepdf.open(path, password=password or "", attempt_recovery=False)
        except pikepdf.PasswordError:
            # If expected_encrypted is True and password wasn't passed, this is expected
            if expected_encrypted is False:
                raise PDFCorruptionError(
                    f"Candidate output at {path} is unexpectedly encrypted.",
                    details={"path": str(path)},
                ) from None
            return
        except pikepdf.PdfError as err:
            raise PDFCorruptionError(
                f"Candidate output verification failed: {err}",
                details={"path": str(path), "error": str(err)},
            ) from err

        try:
            actual_pages = len(pdf.pages)
            if expected_page_count is not None and actual_pages != expected_page_count:
                raise PDFCorruptionError(
                    f"Candidate output page count mismatch: expected {expected_page_count}, "
                    f"got {actual_pages}",
                    details={
                        "path": str(path),
                        "expected_pages": expected_page_count,
                        "actual_pages": actual_pages,
                    },
                )

            if expected_encrypted is not None and pdf.is_encrypted != expected_encrypted:
                raise PDFCorruptionError(
                    f"Candidate output encryption mismatch: expected {expected_encrypted}, "
                    f"got {pdf.is_encrypted}",
                    details={
                        "path": str(path),
                        "expected_encrypted": expected_encrypted,
                        "actual_encrypted": pdf.is_encrypted,
                    },
                )
        finally:
            pdf.close()
