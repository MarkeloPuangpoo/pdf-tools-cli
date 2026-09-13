"""CLI tests for encryption and decryption commands (CMD-004).

Conforms to PLAN.md §12.6 C35, C36, §1348.
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
    """Create a sample 3-page unencrypted PDF."""
    pdf_path = tmp_path / "sample.pdf"
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page()
    pdf.save(pdf_path)
    pdf.close()
    return pdf_path


def test_encrypt_and_decrypt_roundtrip(sample_pdf: Path, tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    encrypted_pdf = tmp_path / "encrypted.pdf"
    decrypted_pdf = tmp_path / "decrypted.pdf"

    monkeypatch.setenv("TEST_OWNER_PW", "SecretOwnerPass123!")
    monkeypatch.setenv("TEST_USER_PW", "SecretUserPass456!")

    # 1. Encrypt with AES-256
    res = runner.invoke(
        cli,
        [
            "encrypt",
            str(sample_pdf),
            "-o",
            str(encrypted_pdf),
            "--owner-password-env",
            "TEST_OWNER_PW",
            "--user-password-env",
            "TEST_USER_PW",
            "--print",
            "full",
            "--modify",
            "none",
            "--copy",
            "deny",
        ],
    )
    assert res.exit_code == 0
    assert "Encrypted sample.pdf (AES-256)" in res.output

    # Verify that inspect detects encrypted file
    res_inspect = runner.invoke(cli, ["--json", "inspect", str(encrypted_pdf)])
    assert res_inspect.exit_code == 4  # Locked without password
    inspect_data = json.loads(res_inspect.output)
    assert inspect_data["status"] == "error"

    # Verify that inspect with password succeeds
    res_inspect_pw = runner.invoke(
        cli,
        [
            "--json",
            "inspect",
            str(encrypted_pdf),
            "--password-env",
            "TEST_USER_PW",
        ],
    )
    assert res_inspect_pw.exit_code == 0
    assert json.loads(res_inspect_pw.output)["data"]["is_encrypted"] is True

    # 2. Decrypt with valid password
    res_dec = runner.invoke(
        cli,
        [
            "decrypt",
            str(encrypted_pdf),
            "-o",
            str(decrypted_pdf),
            "--password-env",
            "TEST_USER_PW",
        ],
    )
    assert res_dec.exit_code == 0
    assert "Decrypted encrypted.pdf" in res_dec.output

    # 3. Verify decrypted PDF can be opened with no credentials
    with pikepdf.open(decrypted_pdf) as p:
        assert p.is_encrypted is False
        assert len(p.pages) == 3


def test_encrypt_allow_empty_user(sample_pdf: Path, tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    encrypted_pdf = tmp_path / "empty_user.pdf"

    monkeypatch.setenv("TEST_OWNER_PW", "OwnerSecret999!")

    res = runner.invoke(
        cli,
        [
            "encrypt",
            str(sample_pdf),
            "-o",
            str(encrypted_pdf),
            "--owner-password-env",
            "TEST_OWNER_PW",
            "--allow-empty-user",
            "--modify",
            "annotate",
        ],
    )
    assert res.exit_code == 0

    # Opens without password
    with pikepdf.open(encrypted_pdf) as p:
        assert p.is_encrypted is True
        assert len(p.pages) == 3


def test_encrypt_same_user_and_owner_fails(sample_pdf: Path, tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    encrypted_pdf = tmp_path / "fail.pdf"

    monkeypatch.setenv("TEST_SAME_PW", "IdenticalPass123!")

    res = runner.invoke(
        cli,
        [
            "encrypt",
            str(sample_pdf),
            "-o",
            str(encrypted_pdf),
            "--owner-password-env",
            "TEST_SAME_PW",
            "--user-password-env",
            "TEST_SAME_PW",
        ],
    )
    assert res.exit_code == 2


def test_decrypt_unencrypted_fails(sample_pdf: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "should_fail.pdf"

    # Attempt to decrypt an already plain PDF
    res = runner.invoke(cli, ["decrypt", str(sample_pdf), "-o", str(out)])
    assert res.exit_code == 2


def test_decrypt_wrong_password_fails(sample_pdf: Path, tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    encrypted_pdf = tmp_path / "enc.pdf"
    out = tmp_path / "out.pdf"

    monkeypatch.setenv("TEST_OWNER", "CorrectOwner123")
    monkeypatch.setenv("TEST_USER", "CorrectUser123")
    monkeypatch.setenv("WRONG_PW", "WrongPassword123")

    runner.invoke(
        cli,
        [
            "encrypt",
            str(sample_pdf),
            "-o",
            str(encrypted_pdf),
            "--owner-password-env",
            "TEST_OWNER",
            "--user-password-env",
            "TEST_USER",
        ],
    )

    # Decrypt with wrong password
    res = runner.invoke(
        cli,
        [
            "decrypt",
            str(encrypted_pdf),
            "-o",
            str(out),
            "--password-env",
            "WRONG_PW",
        ],
    )
    assert res.exit_code == 4  # AUTHENTICATION_REQUIRED


def test_encrypt_rejects_same_file(sample_pdf: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("TEST_OWNER", "Owner123")

    # In-place write
    res = runner.invoke(
        cli,
        [
            "encrypt",
            str(sample_pdf),
            "-o",
            str(sample_pdf),
            "--owner-password-env",
            "TEST_OWNER",
            "--allow-empty-user",
        ],
    )
    assert res.exit_code == 8  # SAFETY_CONFLICT
