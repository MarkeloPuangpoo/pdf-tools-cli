"""Unit tests for output presenters, JSON v1 schema validation, and terminal formatting.

Conforms to PLAN.md §16, §17.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from pdftoolscli.domain.errors import ErrorDetail, PageBoundsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import format_json_result, render_json
from pdftoolscli.presentation.terminal import sanitize_terminal_text, should_use_color


def test_sanitize_terminal_text() -> None:
    # Strips ANSI escape codes
    ansi_text = "\x1b[31;1mDangerous Error\x1b[0m"
    assert sanitize_terminal_text(ansi_text) == "Dangerous Error"

    # Escapes unprintable control codes but preserves newline and tab
    raw = "Line 1\tTabbed\n\x00Null\x07Bell"
    sanitized = sanitize_terminal_text(raw)
    assert sanitized == "Line 1\tTabbed\n\\x00Null\\x07Bell"


def test_should_use_color() -> None:
    # NO_COLOR env overrides everything
    assert not should_use_color(color_pref="always", env={"NO_COLOR": "1"})

    # Explicit flags
    assert not should_use_color(color_pref="never", env={})
    assert should_use_color(color_pref="always", env={})


def test_json_result_format_and_schema() -> None:
    schema_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "pdftoolscli"
        / "schemas"
        / "result-v1.schema.json"
    )
    assert schema_path.is_file()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    err = ErrorDetail(
        code="E_PAGE_BOUNDS",
        category="selection",
        message="page 42 does not exist",
        page=42,
        hint="inspect page count",
    )
    json_str = format_json_result(
        command="pages.extract",
        status="error",
        data=None,
        errors=[err],
        elapsed_ms=45,
    )

    doc = json.loads(json_str)
    assert doc["schema_version"] == "1.0"
    assert doc["command"] == "pages.extract"
    assert doc["status"] == "error"
    assert doc["errors"][0]["code"] == "E_PAGE_BOUNDS"
    assert doc["metrics"]["elapsed_ms"] == 45

    # Check that required top-level keys from schema exist
    for required_prop in schema["required"]:
        assert required_prop in doc


def test_render_json_stream() -> None:
    stream = io.StringIO()
    render_json(command="inspect", status="ok", data={"pages": 10}, stream=stream)
    output = stream.getvalue()
    assert output.endswith("\n")
    data = json.loads(output)
    assert data["status"] == "ok"
    assert data["data"] == {"pages": 10}


def test_human_presenter(monkeypatch: pytest.MonkeyPatch) -> None:
    presenter = HumanPresenter(color="never", quiet=False, verbose=True)

    # Capture stdout and stderr
    stdout_io = io.StringIO()
    stderr_io = io.StringIO()
    monkeypatch.setattr(presenter.stdout_console, "file", stdout_io)
    monkeypatch.setattr(presenter.stderr_console, "file", stderr_io)

    # Render error
    err = PageBoundsError("Page 99 does not exist", page=99, hint="Check page count")
    presenter.render_error(err)
    err_out = stderr_io.getvalue()
    assert "E_PAGE_BOUNDS" in err_out
    assert "Page 99 does not exist" in err_out
    assert "Check page count" in err_out

    # Render data to stdout
    presenter.render_data("Primary document data")
    assert "Primary document data" in stdout_io.getvalue()


def test_human_presenter_quiet_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    presenter = HumanPresenter(color="never", quiet=True)
    stderr_io = io.StringIO()
    monkeypatch.setattr(presenter.stderr_console, "file", stderr_io)

    presenter.render_success("This should be suppressed in quiet mode")
    presenter.render_warning(
        ErrorDetail(code="W_TEST", category="test", message="Warning suppressed")
    )
    assert stderr_io.getvalue() == ""
