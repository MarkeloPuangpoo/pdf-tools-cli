"""Integration tests for shell completion script generation.

Conforms to PLAN.md CLI-002.
"""

from __future__ import annotations

import time

import pytest
from click.testing import CliRunner

from pdftoolscli.cli.main import cli


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish", "powershell"])
def test_completion_generation(shell: str) -> None:
    runner = CliRunner()
    t0 = time.monotonic()
    result = runner.invoke(cli, ["completion", shell])
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert result.exit_code == 0
    assert len(result.output) > 50
    # Must be under 50ms per PLAN.md acceptance criteria
    assert elapsed_ms < 50.0


def test_completion_invalid_shell() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "unknown_shell"])
    assert result.exit_code == 2
    assert "Invalid value for" in result.output or "Error" in result.output


def test_completion_rejects_json() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "completion", "bash"])
    assert result.exit_code == 2
    assert "not supported for shell completion" in result.output
