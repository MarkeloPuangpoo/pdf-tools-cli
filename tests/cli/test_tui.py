"""Tests for Interactive Terminal UI (TUI) Mode.

Conforms to PLAN.md CLI-003 and refimage/ specifications.
"""

from __future__ import annotations

import io

from click.testing import CliRunner
from rich.console import Console

from pdftoolscli.cli.main import cli
from pdftoolscli.presentation.tui import (
    MENU_ACTIONS,
    Screen,
    TerminalUI,
    launch_tui,
)


def test_tui_render_dashboard() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    ui = TerminalUI(console=console)

    ui.render_dashboard()
    rendered = output.getvalue()

    # Assert ASCII Pixel Banner elements
    assert "█▀█" in rendered
    # Assert Tagline and Category line
    assert "fast. safe. offline. terminal pdf toolkit." in rendered
    assert "inspect" in rendered
    assert "render" in rendered
    assert "doctor" in rendered

    # Assert Selected item is highlighted with arrow
    assert "› ▶ inspect" in rendered
    # Assert Shortcut bar
    assert "choose" in rendered
    assert "select" in rendered
    assert "quit" in rendered


def test_tui_menu_navigation() -> None:
    ui = TerminalUI()
    assert ui.selected_action_index == 0
    assert ui.get_current_action_name() == "inspect"

    # Arrow down
    ui.handle_key("DOWN")
    assert ui.selected_action_index == 1
    assert ui.get_current_action_name() == "merge"

    # Arrow up
    ui.handle_key("UP")
    assert ui.selected_action_index == 0
    assert ui.get_current_action_name() == "inspect"

    # Wrap around up
    ui.handle_key("UP")
    assert ui.selected_action_index == len(MENU_ACTIONS) - 1
    assert ui.get_current_action_name() == "doctor"

    # Vim keys (j / k)
    ui.handle_key("j")
    assert ui.selected_action_index == 0
    ui.handle_key("k")
    assert ui.selected_action_index == len(MENU_ACTIONS) - 1


def test_tui_file_picker_workflow() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    ui = TerminalUI(console=console)

    # In menu, select 'render'
    ui.selected_action_index = 8
    assert ui.get_current_action_name() == "render"

    # Press enter -> file picker screen
    ui.handle_key("ENTER")
    assert ui.current_screen == Screen.FILE_PICKER

    ui.render_file_picker()
    rendered = output.getvalue()
    assert "Select a PDF" in rendered
    assert "RENDER" in rendered

    # Clear and type a path
    ui.file_path = ""
    for char in "my_test.pdf":
        ui.handle_key(char)
    assert ui.file_path == "my_test.pdf"

    # Backspace
    ui.handle_key("BACKSPACE")
    assert ui.file_path == "my_test.pd"

    # ESC goes back to menu
    ui.handle_key("ESC")
    assert ui.current_screen == Screen.MENU


def test_tui_options_screen_and_command_synthesis() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    ui = TerminalUI(console=console)

    # Select 'render'
    ui.selected_action_index = 8
    ui.file_path = "document.pdf"

    # Transition to OPTIONS
    ui.handle_key("ENTER")  # FILE_PICKER
    ui.handle_key("ENTER")  # OPTIONS
    assert ui.current_screen == Screen.OPTIONS

    # Render options screen
    ui.render_options()
    rendered = output.getvalue()
    assert "OPTIONS" in rendered
    assert "Resolution" in rendered
    assert "Pages" in rendered
    assert "Format" in rendered
    assert "Generated CLI Command:" in rendered

    # Verify cycling choices (SPACE / RIGHT / LEFT)
    categories = ui.get_current_options()
    res_cat = categories[0]
    assert res_cat.name == "Resolution"
    assert res_cat.selected_index == 0  # Standard (150 DPI)

    ui.handle_key("SPACE")
    assert res_cat.selected_index == 1  # High Print (300 DPI)

    # Down to 'Pages' category
    ui.handle_key("DOWN")
    assert ui.active_category_index == 1
    pages_cat = categories[1]
    ui.handle_key("RIGHT")
    assert pages_cat.selected_index == 1  # First page only (1)

    # Down to 'Format' category
    ui.handle_key("DOWN")
    assert ui.active_category_index == 2
    fmt_cat = categories[2]
    ui.handle_key("SPACE")
    assert fmt_cat.selected_index == 1  # JPEG (jpg)

    # Press Enter to finalize and view execution preview
    ui.handle_key("ENTER")
    assert ui.current_screen == Screen.RESULT
    assert ui.last_command == "ptc render document.pdf --dpi 300 --pages 1 --format jpg"

    output.truncate(0)
    output.seek(0)
    ui.render_result()
    res_rendered = output.getvalue()
    assert "Command Ready to Execute" in res_rendered
    assert "ptc render document.pdf --dpi 300 --pages 1 --format jpg" in res_rendered

    # ESC returns to menu
    ui.handle_key("ESC")
    assert ui.current_screen == Screen.MENU


def test_tui_doctor_direct_options() -> None:
    ui = TerminalUI()
    # Find doctor
    for i, (action, _) in enumerate(MENU_ACTIONS):
        if action == "doctor":
            ui.selected_action_index = i
            break

    # Doctor skips file picker directly to options
    ui.handle_key("ENTER")
    assert ui.current_screen == Screen.OPTIONS

    # Press Enter to synthesize command
    ui.handle_key("ENTER")
    assert ui.current_screen == Screen.RESULT
    assert ui.last_command == "ptc doctor"


def test_tui_run_with_key_provider() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100)
    ui = TerminalUI(console=console)

    # Simulate key sequence: move down, select, accept file, accept options, quit
    keys = ["DOWN", "ENTER", "ENTER", "ENTER", "q"]
    exit_code = ui.run(key_provider=keys)
    assert exit_code == 0


def test_launch_tui_non_interactive_fallback(monkeypatch: object) -> None:
    # In non-interactive environment, launch_tui returns 0
    err = io.StringIO()
    import sys

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)  # type: ignore[union-attr]
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)  # type: ignore[union-attr]
    monkeypatch.setattr(sys, "stderr", err)

    code = launch_tui()
    assert code == 0
    assert "Interactive TUI requires a controlling TTY" in err.getvalue()


def test_cli_runner_ui_flag_fallback() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--ui"])
    assert result.exit_code == 0
    assert "Interactive TUI requires a controlling TTY terminal." in result.stderr
