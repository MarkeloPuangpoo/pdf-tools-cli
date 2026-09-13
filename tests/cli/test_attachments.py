"""Tests for document attachments management conforming to PLAN.md §12.7 C45-C48 (CMD-015)."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pikepdf
import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli
from pdftoolscli.domain.errors import ExitCode


@pytest.fixture
def clean_pdf(tmp_path: Path) -> Path:
    """Create a minimal PDF without attachments."""
    pdf_path = tmp_path / "base.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(300, 300))
    pdf.save(pdf_path)
    return pdf_path


@pytest.fixture
def sample_file1(tmp_path: Path) -> Path:
    """Create a sample data file."""
    fpath = tmp_path / "data.csv"
    fpath.write_text("id,val\n1,alpha\n2,beta\n", encoding="utf-8")
    return fpath


@pytest.fixture
def sample_file2(tmp_path: Path) -> Path:
    """Create a second sample text file."""
    fpath = tmp_path / "notes.txt"
    fpath.write_text("Meeting notes and actions.\n", encoding="utf-8")
    return fpath


@pytest.fixture
def attached_pdf(clean_pdf: Path, sample_file1: Path, sample_file2: Path, tmp_path: Path) -> Path:
    """Create a PDF containing two attachments."""
    out_pdf = tmp_path / "packet.pdf"
    with pikepdf.open(clean_pdf) as pdf:
        spec1 = pikepdf.AttachedFileSpec(pdf, sample_file1.read_bytes(), description="Data CSV")
        pdf.attachments["data.csv"] = spec1

        spec2 = pikepdf.AttachedFileSpec(pdf, sample_file2.read_bytes(), description="Notes")
        pdf.attachments["notes.txt"] = spec2

        pdf.save(out_pdf)
    return out_pdf


def test_attachments_list_empty(clean_pdf: Path) -> None:
    """Verify attachments list on empty PDF returns no attachments."""
    runner = CliRunner()
    result = runner.invoke(cli, ["attachments", "list", str(clean_pdf)])
    assert result.exit_code == 0, result.output
    assert "No attachments found" in result.output


def test_attachments_list_json(attached_pdf: Path) -> None:
    """Verify attachments list in JSON mode produces structured manifest."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "attachments", "list", str(attached_pdf)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["data"]["count"] == 2
    names = [a["name"] for a in data["data"]["attachments"]]
    assert "data.csv" in names
    assert "notes.txt" in names


def test_attachments_add_single(clean_pdf: Path, sample_file1: Path, tmp_path: Path) -> None:
    """Verify adding a single file attachment."""
    out_pdf = tmp_path / "added1.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "add",
            str(clean_pdf),
            str(sample_file1),
            "-o",
            str(out_pdf),
            "--description",
            "Customer data",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out_pdf.exists()

    with pikepdf.open(out_pdf) as pdf:
        assert "data.csv" in pdf.attachments
        assert pdf.attachments["data.csv"].get_file().read_bytes() == sample_file1.read_bytes()


def test_attachments_add_multiple(
    clean_pdf: Path, sample_file1: Path, sample_file2: Path, tmp_path: Path
) -> None:
    """Verify adding multiple files at once."""
    out_pdf = tmp_path / "added_multi.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "add",
            str(clean_pdf),
            str(sample_file1),
            str(sample_file2),
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        assert len(pdf.attachments) == 2
        assert "data.csv" in pdf.attachments
        assert "notes.txt" in pdf.attachments


def test_attachments_add_collision_rejected(
    attached_pdf: Path, sample_file1: Path, tmp_path: Path
) -> None:
    """Verify adding file with existing name without --replace-name is rejected with exit code 2."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "add",
            str(attached_pdf),
            str(sample_file1),
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_attachments_add_with_replace_name(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify replacing an existing attachment using --replace-name."""
    new_data = tmp_path / "data_new.csv"
    new_data.write_text("new content here", encoding="utf-8")
    out_pdf = tmp_path / "replaced.pdf"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "add",
            str(attached_pdf),
            str(new_data),
            "--replace-name",
            "data.csv",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        assert "data.csv" in pdf.attachments
        assert pdf.attachments["data.csv"].get_file().read_bytes() == b"new content here"


def test_attachments_add_directory_rejected(clean_pdf: Path, tmp_path: Path) -> None:
    """Verify directory inputs are rejected with exit code 2."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "add",
            str(clean_pdf),
            str(tmp_path),
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code != 0


def test_attachments_extract_all(attached_pdf: Path, sample_file1: Path, tmp_path: Path) -> None:
    """Verify extracting all attachments produces mode 0600 files and manifest.json."""
    extract_dir = tmp_path / "extracted"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["attachments", "extract", str(attached_pdf), "--output-dir", str(extract_dir)],
    )
    assert result.exit_code == 0, result.output
    assert extract_dir.is_dir()

    manifest_file = extract_dir / "manifest.json"
    assert manifest_file.exists()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["extracted_count"] == 2

    # Check extracted file permissions (0600) and SHA-256 hash match
    extracted_csv = extract_dir / "attachment-0001-data.csv"
    assert extracted_csv.exists()
    file_stat = os.stat(extracted_csv)
    mode = stat.S_IMODE(file_stat.st_mode)
    assert mode == 0o600

    expected_hash = hashlib.sha256(sample_file1.read_bytes()).hexdigest()
    assert manifest["attachments"][0]["sha256"] == expected_hash


def test_attachments_extract_by_id(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify extracting only specific attachment by ID."""
    extract_dir = tmp_path / "extracted_single"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "extract",
            str(attached_pdf),
            "--output-dir",
            str(extract_dir),
            "--id",
            "att-0001",
        ],
    )
    assert result.exit_code == 0, result.output

    manifest = json.loads((extract_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["extracted_count"] == 1
    assert manifest["attachments"][0]["id"] == "att-0001"


def test_attachments_extract_unknown_id_rejected(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify unknown attachment ID is rejected with exit code 2."""
    extract_dir = tmp_path / "err_dir"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "extract",
            str(attached_pdf),
            "--output-dir",
            str(extract_dir),
            "--id",
            "att-9999",
        ],
    )
    assert result.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_attachments_extract_sanitizes_path_traversal(clean_pdf: Path, tmp_path: Path) -> None:
    """Verify malicious attachment names containing ../ are neutralized."""
    malicious_pdf = tmp_path / "malicious.pdf"
    with pikepdf.open(clean_pdf) as pdf:
        spec = pikepdf.AttachedFileSpec(pdf, b"pwned", description="exploit")
        pdf.attachments["../../../../etc/passwd"] = spec
        pdf.save(malicious_pdf)

    extract_dir = tmp_path / "safe_extract"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["attachments", "extract", str(malicious_pdf), "--output-dir", str(extract_dir)],
    )
    assert result.exit_code == 0, result.output

    # Verify no file escaped outside extract_dir
    extracted_files = list(extract_dir.glob("attachment-*"))
    assert len(extracted_files) == 1
    assert "passwd" in extracted_files[0].name
    assert extracted_files[0].parent == extract_dir


def test_attachments_remove_by_name(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify removing an attachment by name."""
    out_pdf = tmp_path / "rem_name.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "remove",
            str(attached_pdf),
            "--name",
            "data.csv",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        assert "data.csv" not in pdf.attachments
        assert "notes.txt" in pdf.attachments


def test_attachments_remove_by_id(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify removing an attachment by ID."""
    out_pdf = tmp_path / "rem_id.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "remove",
            str(attached_pdf),
            "--id",
            "att-0001",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        assert len(pdf.attachments) == 1


def test_attachments_remove_all(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify removing all attachments."""
    out_pdf = tmp_path / "rem_all.pdf"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "attachments",
            "remove",
            str(attached_pdf),
            "--all",
            "-o",
            str(out_pdf),
        ],
    )
    assert result.exit_code == 0, result.output

    with pikepdf.open(out_pdf) as pdf:
        assert len(pdf.attachments) == 0


def test_attachments_remove_unknown_target_rejected(attached_pdf: Path, tmp_path: Path) -> None:
    """Verify unknown name or ID to remove is rejected with exit code 2."""
    out_pdf = tmp_path / "err.pdf"
    runner = CliRunner()
    res1 = runner.invoke(
        cli,
        [
            "attachments",
            "remove",
            str(attached_pdf),
            "--name",
            "nonexistent.xyz",
            "-o",
            str(out_pdf),
        ],
    )
    assert res1.exit_code == int(ExitCode.USAGE_OR_SELECTION)

    res2 = runner.invoke(
        cli,
        ["attachments", "remove", str(attached_pdf), "--id", "att-9999", "-o", str(out_pdf)],
    )
    assert res2.exit_code == int(ExitCode.USAGE_OR_SELECTION)


def test_attachments_in_place_refusal(attached_pdf: Path, sample_file1: Path) -> None:
    """Verify input == output is rejected with exit code 8."""
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["attachments", "add", str(attached_pdf), str(sample_file1), "-o", str(attached_pdf)],
    )
    assert res.exit_code == int(ExitCode.SAFETY_CONFLICT)
