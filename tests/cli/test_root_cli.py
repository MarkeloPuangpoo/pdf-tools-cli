"""Integration tests for Click root command, options, and error boundary.

Conforms to PLAN.md §10, §16, §17.
"""

from __future__ import annotations

import time

from click.testing import CliRunner

from pdftoolscli import __version__
from pdftoolscli.cli.main import cli
from pdftoolscli.cli.registry import get_command_catalog


def test_cli_help_performance() -> None:
    runner = CliRunner()
    t0 = time.monotonic()
    result = runner.invoke(cli, ["--help"])
    elapsed_ms = (time.monotonic() - t0) * 1000

    assert result.exit_code == 0
    assert "PDF Tools CLI (ptc)" in result.output
    # Must be under 200ms per PLAN.md acceptance criteria
    assert elapsed_ms < 200.0


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_mutual_exclusion_json_quiet() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "--quiet"])
    assert result.exit_code == 2
    assert "Cannot combine '--json' and '--quiet'" in result.output


def test_mutual_exclusion_color_no_color() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--color", "--no-color"])
    assert result.exit_code == 2
    assert "Cannot combine '--color' and '--no-color'" in result.output


def test_mutual_exclusion_config_no_config() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", "custom.toml", "--no-config"])
    assert result.exit_code == 2
    assert "Cannot combine '--config' and '--no-config'" in result.output


def test_non_interactive_no_subcommand_prints_help() -> None:
    # CliRunner is non-interactive by default
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "PDF Tools CLI (ptc)" in result.output


def test_command_catalog() -> None:
    catalog = get_command_catalog(cli)
    assert catalog["name"] == "cli"
    assert "completion" in catalog["commands"]
