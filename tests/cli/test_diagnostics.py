"""Integration tests for discovery and diagnostics commands: inspect, validate, doctor (CMD-001).

Conforms to PLAN.md §12.2, §17.
"""

# ruff: noqa: S106

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


def test_inspect_healthy_document(fixtures_dir: Path) -> None:
    runner = CliRunner()
    single_pdf = fixtures_dir / "single_page.pdf"

    # Human output
    result = runner.invoke(cli, ["inspect", str(single_pdf)])
    assert result.exit_code == 0
    assert "Document: single_page.pdf" in result.output
    assert "Page Count" in result.output
    assert "PDF Version" in result.output

    # JSON output
    json_result = runner.invoke(cli, ["--json", "inspect", str(single_pdf)])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)
    assert payload["status"] == "ok"
    assert payload["data"]["page_count"] == 1
    assert payload["data"]["is_encrypted"] is False


def test_inspect_detail_all(fixtures_dir: Path) -> None:
    runner = CliRunner()
    outlines_pdf = fixtures_dir / "outlines_sample.pdf"

    json_result = runner.invoke(cli, ["--json", "inspect", str(outlines_pdf), "--detail", "all"])
    assert json_result.exit_code == 0
    data = json.loads(json_result.output)["data"]
    assert "outlines" in data
    assert len(data["outlines"]) == 3
    titles = [o["title"] for o in data["outlines"]]
    assert "Chapter 1" in titles


def test_inspect_section_filter(fixtures_dir: Path) -> None:
    runner = CliRunner()
    single_pdf = fixtures_dir / "single_page.pdf"

    json_result = runner.invoke(cli, ["--json", "inspect", str(single_pdf), "--section", "pages"])
    assert json_result.exit_code == 0
    data = json.loads(json_result.output)["data"]
    assert "pages" in data


def test_inspect_encrypted_without_password(fixtures_dir: Path) -> None:
    runner = CliRunner()
    enc_pdf = fixtures_dir / "encrypted_aes256.pdf"

    # Human mode -> exit code 4
    result = runner.invoke(cli, ["inspect", str(enc_pdf)])
    assert result.exit_code == 4
    assert "E_PASSWORD_REQUIRED" in result.output

    # JSON mode -> exit code 4, status error
    json_result = runner.invoke(cli, ["--json", "inspect", str(enc_pdf)])
    assert json_result.exit_code == 4
    payload = json.loads(json_result.output)
    assert payload["status"] == "error"
    assert payload["data"]["locked"] is True
    assert payload["errors"][0]["code"] == "E_PASSWORD_REQUIRED"


def test_inspect_encrypted_with_password(
    fixtures_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    enc_pdf = fixtures_dir / "encrypted_aes256.pdf"

    monkeypatch.setenv("TEST_INSPECT_PASS", "userpass123")

    result = runner.invoke(
        cli,
        ["--json", "inspect", str(enc_pdf), "--password-env", "TEST_INSPECT_PASS"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["data"]["is_encrypted"] is True
    assert payload["data"]["encryption_algorithm"] == "AES-256"


def test_validate_valid_file(fixtures_dir: Path) -> None:
    runner = CliRunner()
    single_pdf = fixtures_dir / "single_page.pdf"

    # Human mode
    res = runner.invoke(cli, ["validate", str(single_pdf)])
    assert res.exit_code == 0
    assert "syntactically valid" in res.output

    # JSON mode
    json_res = runner.invoke(cli, ["--json", "validate", str(single_pdf)])
    assert json_res.exit_code == 0
    payload = json.loads(json_res.output)
    assert payload["status"] == "ok"
    assert payload["data"]["valid"] is True


def test_validate_corrupted_file(tmp_path: Path) -> None:
    runner = CliRunner()
    corrupt = tmp_path / "corrupted.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nCorrupted garbage data here\n%%EOF")

    res = runner.invoke(cli, ["validate", str(corrupt)])
    assert res.exit_code == 5

    json_res = runner.invoke(cli, ["--json", "validate", str(corrupt)])
    assert json_res.exit_code == 5
    payload = json.loads(json_res.output)
    assert payload["status"] == "error"
    assert payload["data"]["valid"] is False


def test_doctor_command() -> None:
    runner = CliRunner()

    # Human mode
    res = runner.invoke(cli, ["doctor"])
    assert res.exit_code == 0
    assert "pikepdf" in res.output
    assert "pypdfium2" in res.output
    assert "Pillow" in res.output

    # JSON mode
    json_res = runner.invoke(cli, ["--json", "doctor"])
    assert json_res.exit_code == 0
    payload = json.loads(json_res.output)
    assert payload["status"] == "ok"
    data = payload["data"]
    assert data["libraries"]["pikepdf"]["status"] == "ready"
    assert data["libraries"]["pypdfium2"]["status"] == "ready"
    assert data["libraries"]["pillow"]["status"] == "ready"
    assert "enforcement" in data["limits"]

    # Paths option
    paths_res = runner.invoke(cli, ["doctor", "--paths"])
    assert paths_res.exit_code == 0
