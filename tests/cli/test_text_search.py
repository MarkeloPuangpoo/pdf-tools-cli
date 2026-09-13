"""Tests for in-document text search conforming to PLAN.md §12.5 C27 (CMD-011)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from reportlab.pdfgen import canvas

from pdftoolscli.cli.main import cli


@pytest.fixture
def search_doc(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "search_doc.pdf"
    c = canvas.Canvas(str(pdf_path))
    c.drawString(100, 700, "Invoice Number: INV-10023 for John Doe")
    c.drawString(100, 650, "Order items: Apple, Banana, Orange")
    c.showPage()
    c.drawString(100, 700, "Second Invoice: INV-99441 for Jane Smith")
    c.drawString(100, 650, "Total paid in full.")
    c.showPage()
    c.save()
    return pdf_path


def test_text_search_literal_match(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["text", "search", str(search_doc), "John Doe"],
    )
    assert result.exit_code == 0, result.output
    assert "John Doe" in result.output
    assert f"{search_doc}:1:" in result.output


def test_text_search_case_sensitivity(search_doc: Path) -> None:
    runner = CliRunner()
    # Case sensitive by default: should not match "john doe"
    miss = runner.invoke(
        cli,
        ["text", "search", str(search_doc), "john doe"],
    )
    assert miss.exit_code == 1

    # Case insensitive flag -i: should match
    hit = runner.invoke(
        cli,
        ["text", "search", str(search_doc), "john doe", "-i"],
    )
    assert hit.exit_code == 0
    assert "John Doe" in hit.output


def test_text_search_regex_pattern(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["text", "search", str(search_doc), r"INV-\d+", "--regex"],
    )
    assert result.exit_code == 0, result.output
    assert "INV-10023" in result.output
    assert "INV-99441" in result.output


def test_text_search_count_only(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["text", "search", str(search_doc), r"INV-\d+", "--regex", "-c"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "2"


def test_text_search_pages_filter(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["text", "search", str(search_doc), r"INV-\d+", "--regex", "--pages", "1", "-c"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "1"


def test_text_search_no_matches(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["text", "search", str(search_doc), "NonExistentString12345"],
    )
    assert result.exit_code == 1


def test_text_search_invalid_regex(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["text", "search", str(search_doc), "[unclosed", "--regex"],
    )
    assert result.exit_code == 2
    assert "Invalid regular expression" in result.output


def test_text_search_json_output(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--json", "text", "search", str(search_doc), "INV-10023"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["data"]["count"] == 1
    assert payload["data"]["matches"][0]["page"] == 1
    assert "INV-10023" in payload["data"]["matches"][0]["snippet"]


def test_text_search_max_matches_truncation(search_doc: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--json",
            "text",
            "search",
            str(search_doc),
            r"INV-\d+",
            "--regex",
            "--max-matches",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"]["count"] == 2
    assert len(payload["data"]["matches"]) == 1
    assert payload["data"]["truncated"] is True


def test_text_search_redos_timeout(tmp_path: Path) -> None:
    runner = CliRunner()
    redos_pdf = tmp_path / "redos.pdf"
    c = canvas.Canvas(str(redos_pdf))
    c.drawString(100, 700, "a" * 32 + "!")
    c.showPage()
    c.save()

    result = runner.invoke(
        cli,
        ["text", "search", str(redos_pdf), r"(a+)+$", "--regex"],
    )
    # Catastrophic backtracking regex should trigger timeout and exit with 7 (ResourceLimitError)
    assert result.exit_code == 7
    assert "timed out" in result.output
