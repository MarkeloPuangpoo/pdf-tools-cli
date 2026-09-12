"""Minimalist Dark Interactive Terminal UI (TUI) Dashboard.

Conforms to PLAN.md CLI-003 and refimage/.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# ASCII Pixel Block Banner inspired by refimage/home.png and download-options.png
ASCII_BANNER = """
█▀█ ▀█▀ █▀▀      █▀█ █▀▄ █▀▀   ▀█▀ █▀█ █▀█ █   █▀
█▀▀  █  █▄▄      █▀▀ █▄▀ █▀     █  █▄█ █▄█ █▄▄ ▄█
"""

TAGLINE = "fast. safe. offline. terminal pdf toolkit."
CATEGORY_LINE = (
    "inspect • merge • split • pages • optimize • encrypt • decrypt • text • render • doctor"
)

MENU_ACTIONS = [
    ("inspect", "🔍 Inspect document structure, encryption, and page geometry"),
    ("merge", "🔗 Concatenate multiple PDF documents into one file"),
    ("split", "✂️  Split document into page bursts or custom groups"),
    ("pages", "📄 Extract, remove, reorder, reverse, or rotate pages"),
    ("optimize", "⚡ Lossless object stream and compression optimization"),
    ("encrypt", "🔒 Secure document with military-grade AES-256 encryption"),
    ("decrypt", "🔓 Remove password encryption from protected document"),
    ("text extract", "📝 Extract clean plain UTF-8 text from pages"),
    ("render", "🖼️  Rasterize document pages to PNG, JPEG, WebP, or TIFF"),
    ("doctor", "🩺 Validate runtime environment, toolchains, and limits"),
]


class TerminalUI:
    """Minimalist dark interactive terminal UI dashboard."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.selected_index = 0

    def render_dashboard(self) -> None:
        """Render the complete dashboard screen."""
        self.console.clear()

        # 1. ASCII Banner
        banner_text = Text(ASCII_BANNER.strip("\n"), style="bold white")
        self.console.print(banner_text, justify="center")

        # 2. Taglines
        self.console.print(f"[dim]{TAGLINE}[/dim]", justify="center")
        self.console.print(f"[dim cyan]{CATEGORY_LINE}[/dim cyan]\n", justify="center")

        # 3. Action Picker Box
        menu_lines = []
        for i, (action, desc) in enumerate(MENU_ACTIONS):
            if i == self.selected_index:
                menu_lines.append(
                    f"[bold cyan]› ▶ {action:<14}[/bold cyan] [white]•[/white] [dim]{desc}[/dim]"
                )
            else:
                menu_lines.append(f"    [dim]{action:<14} • {desc}[/dim]")

        menu_content = "\n".join(menu_lines)
        panel = Panel(
            menu_content,
            title="[bold]Select an Operation[/bold]",
            title_align="left",
            border_style="cyan" if self.console.is_terminal else "dim",
            padding=(1, 2),
        )
        self.console.print(panel)

        # 4. Bottom shortcut bar
        shortcuts = (
            "[dim]↑↓ choose[/dim]  [cyan]•[/cyan]  "
            "[bold cyan]↵ run[/bold cyan]  [cyan]•[/cyan]  "
            "[dim]esc back[/dim]  [cyan]•[/cyan]  "
            "[dim]^c quit[/dim]"
        )
        self.console.print(f"\n{shortcuts}", justify="center")


def launch_tui() -> None:
    """Entrypoint to launch the interactive Terminal UI.

    If run in non-interactive environment (CI / pipe), safely exits.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write("Interactive TUI requires a controlling TTY terminal.\n")
        return

    ui = TerminalUI()
    ui.render_dashboard()
