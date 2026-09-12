"""Password providers, credential mapping, and secret boundary validation.

Conforms to PLAN.md §28.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from pdftoolscli.contracts.secrets import SecretProvider, SecretValue
from pdftoolscli.domain.errors import FileSafetyError, SecretError

MAX_SECRET_FILE_BYTES = 4096  # 4 KiB
MAX_PASSWORD_BYTES = 127  # PDF 2.0 / revision 6 max bytes for UTF-8 passwords


def validate_password_string(raw: str, source_description: str = "password") -> SecretValue:
    """Validate and sanitize a raw password string.

    Rules:
      - Strip exactly one trailing LF or CRLF (\n or \r\n).
      - Reject embedded NUL bytes (\x00).
      - Reject embedded newlines.
      - Enforce UTF-8 byte length <= 127 bytes.
    """
    if raw.endswith("\r\n"):
        raw = raw[:-2]
    elif raw.endswith("\n"):
        raw = raw[:-1]

    if "\x00" in raw:
        raise SecretError(
            f"Invalid {source_description}: embedded NUL bytes are not permitted.",
            code="E_PASSWORD_INVALID",
        )

    if "\n" in raw or "\r" in raw:
        raise SecretError(
            f"Invalid {source_description}: multi-line passwords are not permitted.",
            code="E_PASSWORD_INVALID",
        )

    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        msg = (
            f"{source_description.capitalize()} exceeds "
            f"maximum length of {MAX_PASSWORD_BYTES} bytes."
        )
        raise SecretError(
            msg,
            code="E_PASSWORD_INVALID",
            hint="Ensure password is at most 127 UTF-8 bytes.",
        )

    return SecretValue(raw)


class PasswordFileProvider(SecretProvider):
    """Acquires a password from a local regular file with strict permissions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def get_password(self) -> SecretValue:
        # Reject symlinks / reparse points before resolving
        if self.path.is_symlink():
            raise FileSafetyError(
                f"Refusing to read password from symlink: {self.path}",
                code="E_SAFETY_CONFLICT",
            )

        resolved = self.path.resolve()

        if not resolved.exists():
            raise SecretError(
                f"Password file not found: {self.path}",
                code="E_PASSWORD_REQUIRED",
            )

        if not resolved.is_file():
            raise SecretError(
                f"Password file is not a regular file: {self.path}",
                code="E_PASSWORD_REQUIRED",
            )

        st = resolved.stat()

        # Enforce file size limit
        if st.st_size > MAX_SECRET_FILE_BYTES:
            raise SecretError(
                f"Password file {self.path} exceeds maximum size of {MAX_SECRET_FILE_BYTES} bytes.",
                code="E_PASSWORD_INVALID",
            )

        # On POSIX: verify no group or world read/write/execute permissions (mode 0600 or stricter)
        if sys.platform != "win32":
            mode = st.st_mode & 0o777
            if mode & 0o077:
                raise SecretError(
                    f"Password file {self.path} has unsafe permissions ({oct(mode)}). "
                    "Group and world access must be removed (chmod 600 or stricter required).",
                    code="E_SAFETY_CONFLICT",
                    hint="Run `chmod 600 <password-file>` to secure the file.",
                )

        try:
            raw = self.path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise SecretError(
                f"Password file {self.path} contains non-UTF-8 characters: {e}",
                code="E_PASSWORD_INVALID",
            ) from e

        return validate_password_string(
            raw, source_description=f"password from file {self.path.name}"
        )


class PasswordEnvProvider(SecretProvider):
    """Acquires a password from an explicitly named environment variable."""

    def __init__(self, env_var: str, env: dict[str, str] | None = None) -> None:
        self.env_var = env_var
        self.env = env if env is not None else dict(os.environ)

    def get_password(self) -> SecretValue:
        val = self.env.get(self.env_var)
        if val is None:
            raise SecretError(
                f"Environment variable '{self.env_var}' requested by --password-env is not set.",
                code="E_PASSWORD_REQUIRED",
                hint=f"Set the '{self.env_var}' environment variable before running the command.",
            )

        return validate_password_string(
            val, source_description=f"password from env '{self.env_var}'"
        )


class PasswordStdinProvider(SecretProvider):
    """Acquires a password by reading a single line from standard input."""

    def __init__(self, stream: Any = None) -> None:
        self.stream = stream or sys.stdin

    def get_password(self) -> SecretValue:
        try:
            line = self.stream.readline()
        except OSError as e:
            raise SecretError(
                f"Failed to read password from stdin: {e}",
                code="E_PASSWORD_REQUIRED",
            ) from e

        if not line:
            raise SecretError(
                "Password requested from stdin, but standard input reached EOF.",
                code="E_PASSWORD_REQUIRED",
            )

        return validate_password_string(line, source_description="password from stdin")


class InteractivePasswordProvider(SecretProvider):
    """Prompts for a password on the controlling terminal using masked input."""

    def __init__(self, prompt: str = "Enter PDF password: ") -> None:
        self.prompt = prompt

    def get_password(self) -> SecretValue:
        # Check if stdin or controlling terminal is interactive
        if not sys.stdin.isatty():
            raise SecretError(
                "Authentication required, but no interactive terminal is available. "
                "Specify a password using --password-file, --password-env, or --password-stdin.",
                code="E_PASSWORD_REQUIRED",
            )

        try:
            val = getpass.getpass(self.prompt)
        except (EOFError, KeyboardInterrupt):
            raise SecretError(
                "Password prompt cancelled by user.",
                code="E_PASSWORD_REQUIRED",
            ) from None

        return validate_password_string(val, source_description="interactive password")


class CredentialMap:
    """Parses and manages multi-file credential mappings from --credentials FILE."""

    def __init__(self, map_file: Path | str) -> None:
        self.map_file = Path(map_file).resolve()
        self._providers: dict[str, SecretProvider] = {}
        self._load()

    def _load(self) -> None:
        if not self.map_file.is_file():
            raise SecretError(
                f"Credentials map file not found: {self.map_file}",
                code="E_PASSWORD_REQUIRED",
            )

        try:
            with open(self.map_file, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise SecretError(
                f"Invalid JSON in credentials map file {self.map_file}: {e}",
                code="E_CONFIG_INVALID",
            ) from e

        if not isinstance(data, dict):
            raise SecretError(
                f"Credentials map file {self.map_file} must contain a JSON object.",
                code="E_CONFIG_INVALID",
            )

        base_dir = self.map_file.parent

        for key, spec in data.items():
            if not isinstance(spec, dict) or "source" not in spec:
                msg = (
                    f"Invalid credential specification for '{key}': "
                    "expected {'source': 'file'|'env', ...}"
                )
                raise SecretError(msg, code="E_CONFIG_INVALID")

            src = spec["source"]
            provider: SecretProvider
            if src == "file":
                if "path" not in spec:
                    raise SecretError(
                        f"Credential spec for '{key}' missing required 'path' property.",
                        code="E_CONFIG_INVALID",
                    )
                p = Path(spec["path"])
                if not p.is_absolute():
                    p = base_dir / p
                provider = PasswordFileProvider(p)
            elif src == "env":
                if "name" not in spec:
                    raise SecretError(
                        f"Credential spec for '{key}' missing required 'name' property.",
                        code="E_CONFIG_INVALID",
                    )
                provider = PasswordEnvProvider(spec["name"])
            else:
                msg = (
                    f"Unsupported credential source '{src}' for key '{key}'. "
                    "Must be 'file' or 'env'."
                )
                raise SecretError(msg, code="E_CONFIG_INVALID")

            self._providers[str(key)] = provider

            # If key is a filename/path, also index it by resolved/normalized path
            try:
                int(key)
            except ValueError:
                raw_kp = Path(key)
                kp = (base_dir / raw_kp).resolve() if not raw_kp.is_absolute() else raw_kp.resolve()
                self._providers[os.path.normcase(str(kp))] = provider

    def get_provider(self, key_or_path: str | Path | int) -> SecretProvider | None:
        """Lookup provider by ordinal (e.g. 1, '1') or path."""
        s_key = str(key_or_path)
        if s_key in self._providers:
            return self._providers[s_key]

        # Normalized path comparison
        if isinstance(key_or_path, (str, Path)):
            norm = os.path.normcase(str(Path(key_or_path).resolve()))
            for k, provider in self._providers.items():
                try:
                    if os.path.normcase(str(Path(k).resolve())) == norm:
                        return provider
                except OSError:
                    pass

        return None


def assert_no_raw_password_cli_argument(argv: list[str]) -> None:
    """Assert that no raw --password flag was supplied in command-line arguments.

    Strict safety invariant: NEVER accept raw passwords on argv!
    """
    msg = (
        "Passing raw passwords via '--password' is strictly prohibited. "
        "Use --password-file, --password-env, --password-stdin, or interactive prompt."
    )
    for arg in argv:
        if arg == "--password" or arg.startswith("--password="):
            raise SecretError(msg, code="E_PASSWORD_INVALID")
