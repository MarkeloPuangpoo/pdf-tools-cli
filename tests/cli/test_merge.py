"""CLI and integration tests for document concatenation / merge (CMD-003).

Conforms to PLAN.md §12.3 C05, §1330.
"""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def make_pdf(tmp_path: Path):
    """Factory fixture to create test PDFs with specified page count and optional outlines."""

    def _factory(name: str, pages: int, bookmarks: list[str] | None = None) -> Path:
        pdf_path = tmp_path / name
        pdf = pikepdf.new()
        for _ in range(pages):
            pdf.add_blank_page()
        if bookmarks:
            with pdf.open_outline() as outline:
                for idx, title in enumerate(bookmarks):
                    target_page = min(idx, pages - 1)
                    outline.root.append(pikepdf.OutlineItem(title, target_page))
        pdf.save(pdf_path)
        pdf.close()
        return pdf_path

    return _factory


def test_merge_two_documents(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 2)
    doc2 = make_pdf("doc2.pdf", 3)
    out = tmp_path / "merged2.pdf"

    res = runner.invoke(cli, ["merge", str(doc1), str(doc2), "-o", str(out)])
    assert res.exit_code == 0
    assert "Merged 2 documents (5 pages total)" in res.output

    with pikepdf.open(out) as p:
        assert len(p.pages) == 5


def test_merge_identical_file_multiple_times(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 2)
    out = tmp_path / "doubled.pdf"

    # Legal per PLAN.md §1341: merging identical file multiple times doubles pages
    res = runner.invoke(cli, ["merge", str(doc1), str(doc1), "-o", str(out)])
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 4


def test_merge_fewer_than_two_files_fails(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 2)
    out = tmp_path / "out.pdf"

    # Only 1 input file
    res = runner.invoke(cli, ["merge", str(doc1), "-o", str(out)])
    assert res.exit_code == 2


def test_merge_document_policy_first_with_outlines(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 2, bookmarks=["Chapter 1", "Chapter 2"])
    doc2 = make_pdf("doc2.pdf", 3, bookmarks=["Chapter 3"])
    out = tmp_path / "with_outlines.pdf"

    res = runner.invoke(
        cli,
        [
            "merge",
            str(doc1),
            str(doc2),
            "-o",
            str(out),
            "--document-policy",
            "first",
        ],
    )
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 5
        with p.open_outline() as outline:
            titles = [item.title for item in outline.root]
            assert titles == ["Chapter 1", "Chapter 2", "Chapter 3"]


def test_merge_document_policy_none(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 2, bookmarks=["B1"])
    doc2 = make_pdf("doc2.pdf", 2, bookmarks=["B2"])
    out = tmp_path / "clean_policy.pdf"

    res = runner.invoke(
        cli,
        [
            "merge",
            str(doc1),
            str(doc2),
            "-o",
            str(out),
            "--document-policy",
            "none",
        ],
    )
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 4
        with p.open_outline() as outline:
            assert len(outline.root) == 0


def test_merge_50_documents_no_fd_exhaustion(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    # Create 50 1-page documents
    doc_paths: list[str] = []
    for i in range(50):
        doc_paths.append(str(make_pdf(f"part_{i:03d}.pdf", 1)))

    out = tmp_path / "merged50.pdf"
    args = ["merge"] + doc_paths + ["-o", str(out)]
    res = runner.invoke(cli, args)
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 50


def test_merge_same_file_prevention(make_pdf) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 2)
    doc2 = make_pdf("doc2.pdf", 2)

    # Output matches one of the inputs
    res = runner.invoke(cli, ["merge", str(doc1), str(doc2), "-o", str(doc1)])
    assert res.exit_code == 8  # SAFETY_CONFLICT


def test_merge_json_output(make_pdf, tmp_path: Path) -> None:
    runner = CliRunner()
    doc1 = make_pdf("doc1.pdf", 1)
    doc2 = make_pdf("doc2.pdf", 2)
    out = tmp_path / "out.json.pdf"

    res = runner.invoke(cli, ["--json", "merge", str(doc1), str(doc2), "-o", str(out)])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "success"
    assert data["data"]["total_pages"] == 3
    assert data["data"]["input_count"] == 2
