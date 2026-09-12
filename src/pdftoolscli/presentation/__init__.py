"""Output presentation subsystem: Human, Quiet, JSON v1, and interactive TUI."""

from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import format_json_result, render_json
from pdftoolscli.presentation.terminal import sanitize_terminal_text, should_use_color
from pdftoolscli.presentation.tui import TerminalUI, launch_tui

__all__ = [
    "HumanPresenter",
    "TerminalUI",
    "format_json_result",
    "launch_tui",
    "render_json",
    "sanitize_terminal_text",
    "should_use_color",
]
