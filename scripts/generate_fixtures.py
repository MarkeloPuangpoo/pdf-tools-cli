"""Deterministic PDF test fixture generator for pdftoolscli (TEST-001).

Generates synthetic PDF fixtures adhering to the taxonomy defined in PLAN.md §35:
- single_page.pdf: Minimal 1-page document (Letter)
- multi_page.pdf: 5-page document with page numbers and text
- rotated_pages.pdf: Multi-page document with 90° and 180° page rotations
- text_sample.pdf: Document with search-friendly English paragraphs
- metadata_sample.pdf: Document with Info and XMP metadata fields
- outlines_sample.pdf: Document with hierarchical bookmarks/outlines
- encrypted_aes256.pdf: AES-256 protected PDF (user: userpass123, owner: ownerpass123)
- encrypted_empty_user.pdf: AES-256 protected with empty user password (owner: ownerpass123)
- malformed_corrupt_xref.pdf: Deliberately broken xref table for recovery tests

Outputs all PDFs into tests/fixtures/generated/ and updates tests/fixtures/manifest.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pikepdf
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_single_page(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.setTitle("Single Page Test Document")
    c.drawString(100, 700, "PDF Tools CLI - Single Page Test Document")
    c.save()

    return {
        "id": "single_page",
        "filename": out_path.name,
        "page_count": 1,
        "encrypted": False,
        "description": "Minimal 1-page Letter document with single text line",
    }


def generate_multi_page(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    for i in range(1, 6):
        c.drawString(100, 700, f"Document Page {i}")
        c.drawString(100, 650, f"This is page {i} of a 5-page document.")
        c.showPage()
    c.save()

    return {
        "id": "multi_page",
        "filename": out_path.name,
        "page_count": 5,
        "encrypted": False,
        "description": "Standard 5-page Letter document with page content",
    }


def generate_rotated_pages(out_path: Path) -> dict[str, object]:
    # Generate 4 pages with different rotations
    c = canvas.Canvas(str(out_path), pagesize=letter)
    for i in range(1, 5):
        c.drawString(100, 700, f"Page {i} before rotation")
        c.showPage()
    c.save()

    # Apply rotations via pikepdf
    with pikepdf.open(out_path, allow_overwriting_input=True) as pdf:
        pdf.pages[0].Rotate = 0
        pdf.pages[1].Rotate = 90
        pdf.pages[2].Rotate = 180
        pdf.pages[3].Rotate = 270
        pdf.save(out_path)

    return {
        "id": "rotated_pages",
        "filename": out_path.name,
        "page_count": 4,
        "encrypted": False,
        "rotations": [0, 90, 180, 270],
        "description": "4-page document containing 0, 90, 180, and 270 degree page rotations",
    }


def generate_text_sample(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawString(100, 720, "Quarterly Financial Report")
    c.drawString(100, 700, "Invoice Number: INV-2026-0901")
    c.drawString(100, 680, "Customer: Acme Corporation")
    c.drawString(100, 660, "Total Amount Due: $1,250.00")
    c.drawString(100, 640, "Status: PAID")
    c.showPage()
    c.drawString(100, 720, "Page 2: Summary of Accounts")
    c.drawString(100, 700, "Keyword: CONFIDENTIAL-AUDIT-RECORD")
    c.showPage()
    c.save()

    return {
        "id": "text_sample",
        "filename": out_path.name,
        "page_count": 2,
        "encrypted": False,
        "description": "2-page document with invoice text, amounts, and audit keywords",
    }


def generate_metadata_sample(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawString(100, 700, "Metadata Sample Document")
    c.save()

    with pikepdf.open(out_path, allow_overwriting_input=True) as pdf:
        pdf.docinfo["/Title"] = "Quarterly Strategic Plan"
        pdf.docinfo["/Author"] = "Jane Doe"
        pdf.docinfo["/Subject"] = "Corporate Strategy"
        pdf.docinfo["/Keywords"] = "strategy, finance, planning"
        pdf.docinfo["/Creator"] = "PDF Tools CLI Test Suite"

        with pdf.open_metadata() as meta:
            meta["dc:title"] = "Quarterly Strategic Plan"
            meta["dc:creator"] = ["Jane Doe"]
            meta["dc:description"] = "Corporate Strategy"

        pdf.save(out_path)

    return {
        "id": "metadata_sample",
        "filename": out_path.name,
        "page_count": 1,
        "encrypted": False,
        "metadata": {
            "title": "Quarterly Strategic Plan",
            "author": "Jane Doe",
            "subject": "Corporate Strategy",
        },
        "description": "Document containing both Info dictionary and XMP metadata",
    }


def generate_outlines_sample(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    for i in range(1, 4):
        c.drawString(100, 700, f"Chapter {i}")
        c.showPage()
    c.save()

    with pikepdf.open(out_path, allow_overwriting_input=True) as pdf:
        with pdf.open_outline() as outline:
            item1 = pikepdf.OutlineItem("Chapter 1", 0)
            item2 = pikepdf.OutlineItem("Chapter 2", 1)
            item3 = pikepdf.OutlineItem("Chapter 3", 2)
            outline.root.extend([item1, item2, item3])
        pdf.save(out_path)

    return {
        "id": "outlines_sample",
        "filename": out_path.name,
        "page_count": 3,
        "encrypted": False,
        "outlines": ["Chapter 1", "Chapter 2", "Chapter 3"],
        "description": "3-page document with document outlines (bookmarks)",
    }


def generate_encrypted_aes256(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawString(100, 700, "Secret Encrypted Content")
    c.save()

    with pikepdf.open(out_path, allow_overwriting_input=True) as pdf:
        enc = pikepdf.Encryption(
            owner="ownerpass123",
            user="userpass123",
            R=6,  # AES-256
            allow=pikepdf.Permissions(accessibility=True, print_highres=True),
        )
        pdf.save(out_path, encryption=enc)

    return {
        "id": "encrypted_aes256",
        "filename": out_path.name,
        "page_count": 1,
        "encrypted": True,
        "cipher": "AES-256",
        "user_password": "userpass123",
        "owner_password": "ownerpass123",
        "description": "AES-256 encrypted document with separate user and owner passwords",
    }


def generate_encrypted_empty_user(out_path: Path) -> dict[str, object]:
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawString(100, 700, "Document with Protected Permissions but Open Reading")
    c.save()

    with pikepdf.open(out_path, allow_overwriting_input=True) as pdf:
        enc = pikepdf.Encryption(
            owner="ownerpass123",
            user="",  # Empty user password
            R=6,  # AES-256
            allow=pikepdf.Permissions(accessibility=True, print_highres=False),
        )
        pdf.save(out_path, encryption=enc)

    return {
        "id": "encrypted_empty_user",
        "filename": out_path.name,
        "page_count": 1,
        "encrypted": True,
        "cipher": "AES-256",
        "user_password": "",
        "owner_password": "ownerpass123",
        "description": "AES-256 encrypted document readable without password, protected owner",
    }


def generate_malformed_corrupt_xref(out_path: Path) -> dict[str, object]:
    # Start with a valid single page PDF
    c = canvas.Canvas(str(out_path), pagesize=letter)
    c.drawString(100, 700, "Original Content Before Corruption")
    c.save()

    raw_bytes = out_path.read_bytes()
    # Deliberately corrupt the startxref pointer at the end of the file
    corrupted = raw_bytes.replace(b"startxref", b"startxxxx")
    out_path.write_bytes(corrupted)

    return {
        "id": "malformed_corrupt_xref",
        "filename": out_path.name,
        "page_count": 1,
        "encrypted": False,
        "is_malformed": True,
        "description": "Corrupted PDF with mutilated startxref token for recovery testing",
    }


def generate_all_fixtures() -> Path:
    out_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir.parent / "manifest.json"

    generators = [
        ("single_page.pdf", generate_single_page),
        ("multi_page.pdf", generate_multi_page),
        ("rotated_pages.pdf", generate_rotated_pages),
        ("text_sample.pdf", generate_text_sample),
        ("metadata_sample.pdf", generate_metadata_sample),
        ("outlines_sample.pdf", generate_outlines_sample),
        ("encrypted_aes256.pdf", generate_encrypted_aes256),
        ("encrypted_empty_user.pdf", generate_encrypted_empty_user),
        ("malformed_corrupt_xref.pdf", generate_malformed_corrupt_xref),
    ]

    manifest_records: list[dict[str, object]] = []

    for filename, gen_fn in generators:
        file_path = out_dir / filename
        meta = gen_fn(file_path)
        meta["sha256"] = _compute_sha256(file_path)
        meta["size_bytes"] = file_path.stat().st_size
        meta["license"] = "CC0-1.0"
        manifest_records.append(meta)
        sha_short = str(meta["sha256"])[:8]
        print(f"Generated fixture: {filename} ({meta['size_bytes']} bytes, SHA: {sha_short}...)")

    manifest = {
        "$schema": "./manifest.schema.json",
        "version": "1.0.0",
        "generator": "scripts/generate_fixtures.py",
        "fixtures": manifest_records,
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nManifest successfully written to: {manifest_path}")
    return manifest_path


if __name__ == "__main__":
    generate_all_fixtures()
