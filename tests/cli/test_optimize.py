"""CLI tests for lossless PDF stream and object optimization (CMD-005).

Conforms to PLAN.md §12.4 C20, §1366.
"""

from __future__ import annotations

import json
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """Create a sample 5-page unoptimized PDF."""
    pdf_path = tmp_path / "sample.pdf"
    pdf = pikepdf.new()
    for _ in range(5):
        pdf.add_blank_page()
    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


def test_optimize_default(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "opt_default.pdf"

    res = runner.invoke(cli, ["optimize", str(sample_pdf), "-o", str(out)])
    assert res.exit_code == 0
    assert "Optimized sample.pdf" in res.output

    with pikepdf.open(out) as p:
        assert len(p.pages) == 5


def test_optimize_generate_object_streams(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "opt_generate.pdf"

    res = runner.invoke(
        cli,
        [
            "optimize",
            str(sample_pdf),
            "-o",
            str(out),
            "--object-streams",
            "generate",
        ],
    )
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 5


def test_optimize_disable_object_streams(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "opt_disable.pdf"

    res = runner.invoke(
        cli,
        [
            "optimize",
            str(sample_pdf),
            "-o",
            str(out),
            "--object-streams",
            "disable",
        ],
    )
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 5


def test_optimize_linearize(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "opt_linear.pdf"

    res = runner.invoke(
        cli,
        ["optimize", str(sample_pdf), "-o", str(out), "--linearize"],
    )
    assert res.exit_code == 0

    with pikepdf.open(out) as p:
        assert len(p.pages) == 5


def test_optimize_same_file_rejected(sample_pdf: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(cli, ["optimize", str(sample_pdf), "-o", str(sample_pdf)])
    assert res.exit_code == 8  # SAFETY_CONFLICT


def test_optimize_json_mode(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "opt.json.pdf"

    res = runner.invoke(cli, ["--json", "optimize", str(sample_pdf), "-o", str(out)])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "success"
    assert "original_size_bytes" in data["data"]
    assert "output_size_bytes" in data["data"]
    assert "savings_percent" in data["data"]
