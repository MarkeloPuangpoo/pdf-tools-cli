"""Output presentation subsystem: Human, Quiet, and JSON v1 modes."""

from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import format_json_result, render_json
from pdftoolscli.presentation.terminal import sanitize_terminal_text, should_use_color

__all__ = [
    "HumanPresenter",
    "format_json_result",
    "render_json",
    "sanitize_terminal_text",
    "should_use_color",
]
