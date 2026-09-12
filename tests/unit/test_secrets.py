"""Unit tests for secret management, password providers, and credential hygiene.

Conforms to PLAN.md §28.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from pdftoolscli.config.secrets import (
    CredentialMap,
    InteractivePasswordProvider,
    PasswordEnvProvider,
    PasswordFileProvider,
    PasswordStdinProvider,
    assert_no_raw_password_cli_argument,
    validate_password_string,
)
from pdftoolscli.contracts.secrets import SecretValue
from pdftoolscli.domain.errors import FileSafetyError, SecretError
from pdftoolscli.runtime.subprocesses import sanitize_environment


def test_secret_value_redaction() -> None:
    secret = SecretValue("super-secret-password")  # noqa: S105
    assert repr(secret) == "<SecretValue: ***REDACTED***>"
    assert str(secret) == "***REDACTED***"
    assert "super-secret-password" not in repr(secret)
    assert "super-secret-password" not in str(secret)
    assert secret.get_secret() == "super-secret-password"  # noqa: S105
    assert secret == "super-secret-password"  # noqa: S105
    assert secret == SecretValue("super-secret-password")  # noqa: S105


def test_validate_password_string() -> None:
    # Trailing newline stripping
    assert validate_password_string("hello\n").get_secret() == "hello"
    assert validate_password_string("hello\r\n").get_secret() == "hello"
    assert validate_password_string(" hello ").get_secret() == " hello "

    # Embedded NUL rejected
    with pytest.raises(SecretError, match="embedded NUL"):
        validate_password_string("bad\x00pass")

    # Multi-line rejected
    with pytest.raises(SecretError, match="multi-line"):
        validate_password_string("first\nsecond")

    # Over 127 bytes rejected
    long_pass = "a" * 128
    with pytest.raises(SecretError, match="exceeds maximum length"):
        validate_password_string(long_pass)


def test_password_file_provider(tmp_path: Path) -> None:
    p_file = tmp_path / "pass.txt"
    p_file.write_text("my-secret-pass\n", encoding="utf-8")

    if sys.platform != "win32":
        p_file.chmod(0o600)

    provider = PasswordFileProvider(p_file)
    sec = provider.get_password()
    assert sec.get_secret() == "my-secret-pass"

    # Unsafe permissions on POSIX
    if sys.platform != "win32":
        p_file.chmod(0o644)
        with pytest.raises(SecretError, match="unsafe permissions"):
            provider.get_password()
        p_file.chmod(0o600)

    # Missing file
    with pytest.raises(SecretError, match="not found"):
        PasswordFileProvider(tmp_path / "missing.txt").get_password()

    # Symlink rejection
    if sys.platform != "win32":
        sym_file = tmp_path / "pass_sym.txt"
        sym_file.symlink_to(p_file)
        with pytest.raises(FileSafetyError, match="symlink"):
            PasswordFileProvider(sym_file).get_password()


def test_password_env_provider() -> None:
    provider = PasswordEnvProvider("TEST_PDF_PASS", env={"TEST_PDF_PASS": "env-pass\n"})
    assert provider.get_password().get_secret() == "env-pass"

    # Missing env var
    with pytest.raises(SecretError, match="not set"):
        PasswordEnvProvider("MISSING_VAR", env={}).get_password()


def test_password_stdin_provider() -> None:
    stream = io.StringIO("stdin-pass\n")
    provider = PasswordStdinProvider(stream=stream)
    assert provider.get_password().get_secret() == "stdin-pass"

    # EOF on stdin
    empty_stream = io.StringIO("")
    provider_empty = PasswordStdinProvider(stream=empty_stream)
    with pytest.raises(SecretError, match="EOF"):
        provider_empty.get_password()


def test_interactive_provider_fails_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    # When stdin is not a TTY, fail immediately without hanging
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    provider = InteractivePasswordProvider()
    with pytest.raises(SecretError) as exc_info:
        provider.get_password()
    assert exc_info.value.code == "E_PASSWORD_REQUIRED"
    assert exc_info.value.exit_code == 4


def test_credential_map(tmp_path: Path) -> None:
    p1 = tmp_path / "p1.txt"
    p1.write_text("p1-pass")
    if sys.platform != "win32":
        p1.chmod(0o600)

    map_file = tmp_path / "credentials.json"
    map_file.write_text(
        f"""
{{
    "1": {{"source": "file", "path": "{p1.name}"}},
    "input2.pdf": {{"source": "env", "name": "DOC2_PASS"}}
}}
"""
    )

    cmap = CredentialMap(map_file)
    prov1 = cmap.get_provider(1)
    assert prov1 is not None
    assert prov1.get_password().get_secret() == "p1-pass"

    prov2 = cmap.get_provider(tmp_path / "input2.pdf")
    assert prov2 is not None


def test_assert_no_raw_password_cli_argument() -> None:
    # Valid arguments
    assert_no_raw_password_cli_argument(["ptc", "inspect", "doc.pdf", "--password-env", "PASS"])

    # Forbidden raw --password
    with pytest.raises(SecretError, match="strictly prohibited"):
        assert_no_raw_password_cli_argument(["ptc", "inspect", "doc.pdf", "--password", "secret"])

    with pytest.raises(SecretError, match="strictly prohibited"):
        assert_no_raw_password_cli_argument(["ptc", "inspect", "--password=secret"])


def test_sanitize_environment() -> None:
    env = {
        "PATH": "/usr/bin",
        "SECRET_VAR": "my-secret",
        "PASSWORD": "leak",
        "USER": "testuser",
    }
    cleaned = sanitize_environment(env, requested_secret_vars=["SECRET_VAR"])
    assert "SECRET_VAR" not in cleaned
    assert "PASSWORD" not in cleaned
    assert cleaned["PATH"] == "/usr/bin"
    assert cleaned["USER"] == "testuser"
