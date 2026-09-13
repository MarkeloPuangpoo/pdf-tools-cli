"""Human-friendly terminal presenter using Rich conforming to PLAN.md §16, §17."""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from pdftoolscli.domain.errors import ErrorDetail, PDFToolsError
from pdftoolscli.presentation.terminal import sanitize_terminal_text, should_use_color


class HumanPresenter:
    """Renders human-readable CLI outputs, tables, error boxes, and progress."""

    def __init__(
        self,
        color: str = "auto",
        quiet: bool = False,
        verbose: bool = False,
    ) -> None:
        self.quiet = quiet
        self.verbose = verbose

        use_color_stdout = should_use_color(color, stream=sys.stdout)
        use_color_stderr = should_use_color(color, stream=sys.stderr)

        self.stdout_console = Console(
            file=sys.stdout,
            no_color=not use_color_stdout,
            highlight=False,
        )
        self.stderr_console = Console(
            file=sys.stderr,
            no_color=not use_color_stderr,
            highlight=False,
        )

    def render_error(self, error: PDFToolsError | ErrorDetail | Exception) -> None:
        """Render a formatted error message to stderr with code, location, and hint."""
        if isinstance(error, PDFToolsError):
            detail = error.as_detail()
        elif isinstance(error, ErrorDetail):
            detail = error
        else:
            detail = ErrorDetail(
                code="E_INTERNAL",
                category="internal",
                message=str(error),
            )

        title = f"[bold red]error[/bold red] [red]({detail.code})[/red]"
        body = sanitize_terminal_text(detail.message)

        text_content = Text(body)

        if detail.input_id:
            text_content.append(f"\n  input: {sanitize_terminal_text(detail.input_id)}")
        if detail.page is not None:
            text_content.append(f"\n  page: {detail.page}")

        if detail.hint:
            clean_hint = sanitize_terminal_text(detail.hint)
            text_content.append(f"\n[dim green]hint: {clean_hint}[/dim green]")

        panel = Panel(
            text_content,
            title=title,
            title_align="left",
            border_style="red",
            expand=False,
        )
        self.stderr_console.print(panel)

    def render_warning(self, warning: ErrorDetail) -> None:
        """Render a warning to stderr (suppressed in quiet mode)."""
        if self.quiet:
            return

        msg = sanitize_terminal_text(warning.message)
        self.stderr_console.print(f"[yellow]warning ({warning.code}):[/yellow] {msg}")

    def render_success(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Render a success/diagnostic message to stderr (suppressed in quiet mode)."""
        if self.quiet:
            return

        clean_msg = sanitize_terminal_text(message)
        self.stderr_console.print(f"[bold green]✓[/bold green] {clean_msg}")
        if details and self.verbose:
            for k, v in details.items():
                self.stderr_console.print(f"  [dim]{k}: {v}[/dim]")

    def render_data(self, text: str) -> None:
        """Render primary requested text output directly to stdout."""
        clean = sanitize_terminal_text(text)
        self.stdout_console.print(clean, soft_wrap=True)
