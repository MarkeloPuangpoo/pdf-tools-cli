"""Tests for annotations inspection and removal conforming to PLAN.md §12.7 C42-C43 (CMD-014)."""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli
from pdftoolscli.domain.errors import ExitCode


@pytest.fixture
def annotated_pdf(tmp_path: Path) -> Path:
    """Create a sample PDF containing Text, Popup, Highlight, and Widget annotations."""
    pdf_path = tmp_path / "annotated.pdf"
    pdf = pikepdf.new()
    p1 = pdf.add_blank_page(page_size=(300, 300))
    p2 = pdf.add_blank_page(page_size=(300, 300))

    # Page 1: Text note with Popup, plus a Widget (form field)
    note = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Text,
            Rect=[50, 50, 80, 80],
            Contents="Review Note 1",
            T="Alice",
            M="D:20260913120000Z",
        )
    )
    popup = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Popup,
            Rect=[80, 80, 200, 200],
            Parent=note,
        )
    )
    note.Popup = popup

    widget = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Widget,
            Rect=[10, 10, 50, 30],
            FT=pikepdf.Name.Tx,
            T="FormField1",
        )
    )
    p1.Annots = pdf.make_indirect(pikepdf.Array([note, popup, widget]))

    # Page 2: Highlight annotation
    hl = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Highlight,
            Rect=[100, 100, 250, 120],
            Contents="Important paragraph",
            T="Bob",
        )
    )
    p2.Annots = pdf.make_indirect(pikepdf.Array([hl]))

    pdf.save(pdf_path)
    return pdf_path


def test_annotations_list_empty(tmp_path: Path) -> None:
    """Verify listing annotations on clean PDF returns empty results."""
    clean_pdf = tmp_path / "clean.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(clean_pdf)

    runner = CliRunner()
    result = runner.invoke(cli, ["annotations", "list", str(clean_pdf)])
    assert result.exit_code == 0, result.output
    assert "No annotations found" in result.output


def test_annotations_list_with_content(annotated_pdf: Path) -> None:
    """Verify annotations list outputs IDs, types, rects, and content strings."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["annotations", "list", str(annotated_pdf), "--include-content"],
    )
    assert result.exit_code == 0, result.output
    assert "Text" in result.output
    assert "Popup" in result.output
    assert "Widget" in result.output
    assert "Highlight" in result.output
    assert "Alice" in result.output
    assert "Review Note" in result.output


def test_annotations_list_pages_filter(annotated_pdf: Path) -> None:
    """Verify --pages filters annotation inspection to designated pages."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--json", "annotations", "list", str(annotated_pdf), "--pages", "2"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    annots = data["data"]["annotations"]
    assert len(annots) == 1
    assert annots[0]["page"] == 2
    assert annots[0]["subtype"] == "Highlight"


def test_annotations_remove_all(annotated_pdf: Path, tmp_path: Path) -> None:
    """Verify --all removes non-widget annotations while preserving form widgets."""
    out_pdf = tmp_path / "removed_all.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["annotations", "remove", str(annotated_pdf), "--all", "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    with pikepdf.open(out_pdf) as pdf:
        # Page 1 should only have the Widget annotation remaining
        p1_annots = [str(a.Subtype).lstrip("/") for a in pdf.pages[0].Annots]
        assert p1_annots == ["Widget"]

        # Page 2 had only Highlight, so Annots is removed or empty
        if "/Annots" in pdf.pages[1]:
            assert len(pdf.pages[1].Annots) == 0


def test_annotations_remove_by_type(annotated_pdf: Path, tmp_path: Path) -> None:
    """Verify --type removes only specified subtypes and cascades to linked popups."""
    out_pdf = tmp_path / "removed_text.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["annotations", "remove", str(annotated_pdf), "--type", "Text", "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        # Text and linked Popup removed; Widget kept on page 1
        p1_annots = [str(a.Subtype).lstrip("/") for a in pdf.pages[0].Annots]
        assert "Text" not in p1_annots
        assert "Popup" not in p1_annots
        assert "Widget" in p1_annots

        # Highlight on page 2 preserved
        p2_annots = [str(a.Subtype).lstrip("/") for a in pdf.pages[1].Annots]
        assert "Highlight" in p2_annots


def test_annotations_remove_by_id(annotated_pdf: Path, tmp_path: Path) -> None:
    """Verify removing a specific annotation by ID."""
    out_pdf = tmp_path / "removed_id.pdf"
    runner = CliRunner()
    # Remove Highlight on page 2
    result = runner.invoke(
        cli,
        ["annotations", "remove", str(annotated_pdf), "--id", "ann-p2-0", "-o", str(out_pdf)],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        if "/Annots" in pdf.pages[1]:
            assert len(pdf.pages[1].Annots) == 0


def test_annotations_remove_unknown_id_rejected(annotated_pdf: Path, tmp_path: Path) -> None:
    """Verify unknown annotation ID is rejected with exit code 2."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["annotations", "remove", str(annotated_pdf), "--id", "nonexistent-id", "-o", str(out_pdf)],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_annotations_remove_widget_rejected(annotated_pdf: Path, tmp_path: Path) -> None:
    """Verify --type Widget is explicitly rejected with exit code 2."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["annotations", "remove", str(annotated_pdf), "--type", "Widget", "-o", str(out_pdf)],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_annotations_remove_invalid_options(annotated_pdf: Path, tmp_path: Path) -> None:
    """Verify specifying both --all and --type or none is rejected with exit code 2."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()

    # None specified
    r1 = runner.invoke(cli, ["annotations", "remove", str(annotated_pdf), "-o", str(out_pdf)])
    assert r1.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    # Both --all and --type
    r2 = runner.invoke(
        cli,
        [
            "annotations",
            "remove",
            str(annotated_pdf),
            "--all",
            "--type",
            "Text",
            "-o",
            str(out_pdf),
        ],
    )
    assert r2.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_annotations_remove_in_place_refusal(annotated_pdf: Path) -> None:
    """Verify input == output is rejected with exit code 8."""
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["annotations", "remove", str(annotated_pdf), "--all", "-o", str(annotated_pdf)],
    )
    assert res.exit_code == int(ExitCode.SAFETY_CONFLICT)
