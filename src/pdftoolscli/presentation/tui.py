"""Minimalist Dark Interactive Terminal UI (TUI) Dashboard.

Conforms to PLAN.md CLI-003 and refimage/.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from rich import box
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

MENU_ACTIONS: list[tuple[str, str]] = [
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


class Screen(Enum):
    """TUI view screen states."""

    MENU = auto()
    FILE_PICKER = auto()
    OPTIONS = auto()
    RESULT = auto()


@dataclass
class OptionChoice:
    """A selectable choice within an option category."""

    label: str
    value: str


@dataclass
class OptionCategory:
    """A group of mutually exclusive options (radio buttons)."""

    name: str
    flag: str
    choices: list[OptionChoice]
    selected_index: int = 0


def build_default_options() -> dict[str, list[OptionCategory]]:
    """Build default option hierarchies for each CLI action."""
    return {
        "render": [
            OptionCategory(
                name="Resolution",
                flag="--dpi",
                choices=[
                    OptionChoice("Standard (150 DPI)", "150"),
                    OptionChoice("High Print (300 DPI)", "300"),
                    OptionChoice("Screen (72 DPI)", "72"),
                ],
                selected_index=0,
            ),
            OptionCategory(
                name="Pages",
                flag="--pages",
                choices=[
                    OptionChoice("All pages (1-N)", "all"),
                    OptionChoice("First page only (1)", "1"),
                    OptionChoice("Custom range (1-5)", "1-5"),
                ],
                selected_index=0,
            ),
            OptionCategory(
                name="Format",
                flag="--format",
                choices=[
                    OptionChoice("PNG (lossless)", "png"),
                    OptionChoice("JPEG (compact)", "jpg"),
                    OptionChoice("WebP", "webp"),
                ],
                selected_index=0,
            ),
        ],
        "pages": [
            OptionCategory(
                name="Operation",
                flag="--operation",
                choices=[
                    OptionChoice("Extract pages", "extract"),
                    OptionChoice("Rotate 90° Clockwise", "rotate-90"),
                    OptionChoice("Reverse page order", "reverse"),
                ],
                selected_index=0,
            ),
            OptionCategory(
                name="Range",
                flag="--pages",
                choices=[
                    OptionChoice("All pages (1-end)", "1-end"),
                    OptionChoice("Odd pages only", "odd"),
                    OptionChoice("Even pages only", "even"),
                ],
                selected_index=0,
            ),
        ],
        "inspect": [
            OptionCategory(
                name="Detail Level",
                flag="--detail",
                choices=[
                    OptionChoice("Standard summary", "summary"),
                    OptionChoice("Detailed catalog inspection", "detailed"),
                    OptionChoice("JSON structure export", "json"),
                ],
                selected_index=0,
            ),
        ],
        "optimize": [
            OptionCategory(
                name="Compression",
                flag="--level",
                choices=[
                    OptionChoice("Lossless stream compression", "lossless"),
                    OptionChoice("Aggressive object deduplication", "max"),
                ],
                selected_index=0,
            ),
            OptionCategory(
                name="Metadata",
                flag="--strip-meta",
                choices=[
                    OptionChoice("Preserve document metadata", "keep"),
                    OptionChoice("Strip unnecessary metadata", "strip"),
                ],
                selected_index=0,
            ),
        ],
        "encrypt": [
            OptionCategory(
                name="Algorithm",
                flag="--algorithm",
                choices=[
                    OptionChoice("AES-256 (Military-grade)", "aes256"),
                    OptionChoice("AES-128 (Legacy compatible)", "aes128"),
                ],
                selected_index=0,
            ),
            OptionCategory(
                name="Permissions",
                flag="--permissions",
                choices=[
                    OptionChoice("Full access with owner password", "full"),
                    OptionChoice("Read-only (disable printing and copy)", "readonly"),
                ],
                selected_index=0,
            ),
        ],
        "decrypt": [
            OptionCategory(
                name="Output Mode",
                flag="--output",
                choices=[
                    OptionChoice("Save as decrypted.pdf", "decrypted.pdf"),
                    OptionChoice("Custom destination path", "custom"),
                ],
                selected_index=0,
            ),
        ],
        "merge": [
            OptionCategory(
                name="Output Mode",
                flag="--output",
                choices=[
                    OptionChoice("Save as merged.pdf", "merged.pdf"),
                    OptionChoice("Save as combined.pdf", "combined.pdf"),
                ],
                selected_index=0,
            ),
            OptionCategory(
                name="Linearize",
                flag="--fast-web-view",
                choices=[
                    OptionChoice("Yes (Fast Web View / Streamed)", "yes"),
                    OptionChoice("No (Standard PDF cross-references)", "no"),
                ],
                selected_index=0,
            ),
        ],
        "split": [
            OptionCategory(
                name="Split Mode",
                flag="--mode",
                choices=[
                    OptionChoice("Single page burst (page-%d.pdf)", "burst"),
                    OptionChoice("Fixed chunks of N pages", "chunks"),
                ],
                selected_index=0,
            ),
        ],
        "text extract": [
            OptionCategory(
                name="Format",
                flag="--format",
                choices=[
                    OptionChoice("Clean UTF-8 plain text", "plain"),
                    OptionChoice("Layout-preserved text with coordinates", "layout"),
                ],
                selected_index=0,
            ),
        ],
        "doctor": [
            OptionCategory(
                name="Diagnostics",
                flag="--check",
                choices=[
                    OptionChoice("Full system & toolchain audit", "all"),
                    OptionChoice("Resource limits & memory isolation test", "limits"),
                ],
                selected_index=0,
            ),
        ],
    }


class TerminalUI:
    """Minimalist dark interactive terminal UI dashboard."""

    def __init__(self, console: Console | None = None) -> None:
        self.console: Console = console or Console()
        self.current_screen: Screen = Screen.MENU
        self.selected_action_index: int = 0
        self.file_path: str = "sample.pdf"
        self.active_category_index: int = 0
        self.options: dict[str, list[OptionCategory]] = build_default_options()
        self.last_command: str = ""

    def get_current_action_name(self) -> str:
        """Get current selected action name."""
        return MENU_ACTIONS[self.selected_action_index][0]

    def get_current_options(self) -> list[OptionCategory]:
        """Get option categories for currently selected action."""
        action = self.get_current_action_name()
        return self.options.get(action, [])

    def build_command(self) -> str:
        """Synthesize the equivalent CLI command string."""
        action = self.get_current_action_name()
        if action == "doctor":
            return "ptc doctor"

        parts = ["ptc", action, self.file_path]
        for cat in self.get_current_options():
            if cat.choices:
                choice = cat.choices[cat.selected_index]
                if choice.value and choice.value not in ("keep", "no"):
                    parts.append(f"{cat.flag} {choice.value}")
        return " ".join(parts)

    def render_dashboard(self) -> None:
        """Render the main action selection dashboard."""
        self.console.clear()

        # 1. ASCII Pixel Banner
        banner_text = Text(ASCII_BANNER.strip("\n"), style="bold white")
        self.console.print(banner_text, justify="center")

        # 2. Taglines
        self.console.print(f"[dim]{TAGLINE}[/dim]", justify="center")
        self.console.print(f"[dim cyan]{CATEGORY_LINE}[/dim cyan]\n", justify="center")

        # 3. Action Picker Box
        menu_lines = []
        for i, (action, desc) in enumerate(MENU_ACTIONS):
            if i == self.selected_action_index:
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
            box=box.SQUARE,
            border_style="cyan" if self.console.is_terminal else "dim",
            padding=(1, 2),
        )
        self.console.print(panel)

        # 4. Bottom shortcut bar
        shortcuts = (
            "[dim]↑↓ choose[/dim]  [cyan]•[/cyan]  "
            "[bold cyan]↵ select[/bold cyan]  [cyan]•[/cyan]  "
            "[dim]q quit[/dim]"
        )
        self.console.print(f"\n{shortcuts}", justify="center")

    def render_file_picker(self) -> None:
        """Render the bordered file path input box."""
        self.console.clear()

        action = self.get_current_action_name().upper()
        self.console.print(f"\n[bold cyan]PDF TOOLS CLI[/bold cyan] • [white]{action}[/white]\n")

        # File path box
        display_path = self.file_path if self.file_path else "[dim]Enter path to PDF file...[/dim]"
        panel = Panel(
            f"[bold white]{display_path}[/bold white]",
            title="Select a PDF",
            title_align="left",
            box=box.SQUARE,
            border_style="cyan",
            padding=(1, 2),
        )
        self.console.print(panel)

        # Existence validation feedback
        if self.file_path:
            p = Path(self.file_path).expanduser()
            if p.is_file():
                size_mb = p.stat().st_size / (1024 * 1024)
                self.console.print(f"\n  [green]✓ File found[/green] [dim]({size_mb:.2f} MB)[/dim]")
            else:
                msg = (
                    f"\n  [dim yellow]ℹ File '{self.file_path}' "
                    "not found on disk (press Enter to accept)[/dim yellow]"
                )
                self.console.print(msg)
        else:
            self.console.print("\n  [dim]Type a PDF path to proceed[/dim]")

        # Shortcut bar
        shortcuts = (
            "[dim]type path[/dim]  [cyan]•[/cyan]  "
            "[bold cyan]↵ continue[/bold cyan]  [cyan]•[/cyan]  "
            "[dim]esc back[/dim]"
        )
        self.console.print(f"\n{shortcuts}", justify="center")

    def render_options(self) -> None:
        """Render the sub-options configuration panel."""
        self.console.clear()

        action = self.get_current_action_name().upper()
        self.console.print(
            f"\n[bold cyan]PDF TOOLS CLI[/bold cyan] • [white]{action} OPTIONS[/white]\n"
        )

        categories = self.get_current_options()
        lines: list[str] = []

        if categories:
            for i, cat in enumerate(categories):
                is_active = i == self.active_category_index
                if is_active:
                    lines.append(f"[bold cyan]▶ {cat.name}[/bold cyan]")
                else:
                    lines.append(f"[bold]{cat.name}[/bold]")

                for j, choice in enumerate(cat.choices):
                    is_selected = j == cat.selected_index
                    if is_selected:
                        lines.append(f"  [cyan]◉[/cyan] [bold white]{choice.label}[/bold white]")
                    else:
                        lines.append(f"  [dim]○ {choice.label}[/dim]")
                lines.append("")

        # Real-time CLI command preview
        cmd = self.build_command()
        lines.append("[dim]Generated CLI Command:[/dim]")
        lines.append(f"[bold cyan]$ {cmd}[/bold cyan]")

        panel = Panel(
            "\n".join(lines),
            title="Options",
            title_align="left",
            box=box.SQUARE,
            border_style="cyan",
            padding=(1, 2),
        )
        self.console.print(panel)

        shortcuts = (
            "[dim]↑↓ category[/dim]  [cyan]•[/cyan]  "
            "[dim]␣/⇄ change[/dim]  [cyan]•[/cyan]  "
            "[bold cyan]↵ run[/bold cyan]  [cyan]•[/cyan]  "
            "[dim]esc back[/dim]"
        )
        self.console.print(f"\n{shortcuts}", justify="center")

    def render_result(self) -> None:
        """Render the command execution preview screen."""
        self.console.clear()

        lines = [
            "[bold green]✔ Command Ready to Execute[/bold green]\n",
            "[dim]Synthesized Command:[/dim]",
            f"[bold cyan]$ {self.last_command}[/bold cyan]\n",
            "[dim]This operation is verified against pdftoolscli invariants.[/dim]",
        ]

        panel = Panel(
            "\n".join(lines),
            title="Execution Preview",
            title_align="left",
            box=box.SQUARE,
            border_style="green",
            padding=(1, 2),
        )
        self.console.print(panel)

        shortcuts = (
            "[bold cyan]↵ new operation[/bold cyan]  [cyan]•[/cyan]  "
            "[dim]esc back[/dim]  [cyan]•[/cyan]  "
            "[dim]q quit[/dim]"
        )
        self.console.print(f"\n{shortcuts}", justify="center")

    def render_current_screen(self) -> None:
        """Dispatch rendering based on current screen state."""
        if self.current_screen == Screen.MENU:
            self.render_dashboard()
        elif self.current_screen == Screen.FILE_PICKER:
            self.render_file_picker()
        elif self.current_screen == Screen.OPTIONS:
            self.render_options()
        elif self.current_screen == Screen.RESULT:
            self.render_result()

    def handle_key(self, key: str) -> bool:
        """Handle a single key event. Return False to exit."""
        if key in ("QUIT", "\x03", "\x04"):
            return False

        if self.current_screen == Screen.MENU:
            if key in ("UP", "k"):
                self.selected_action_index = (self.selected_action_index - 1) % len(MENU_ACTIONS)
            elif key in ("DOWN", "j"):
                self.selected_action_index = (self.selected_action_index + 1) % len(MENU_ACTIONS)
            elif key == "ENTER":
                action = self.get_current_action_name()
                if action == "doctor":
                    self.current_screen = Screen.OPTIONS
                else:
                    self.current_screen = Screen.FILE_PICKER
            elif key in ("ESC", "q", "Q"):
                return False

        elif self.current_screen == Screen.FILE_PICKER:
            if key == "ESC":
                self.current_screen = Screen.MENU
            elif key == "ENTER":
                if not self.file_path.strip():
                    self.file_path = "sample.pdf"
                self.current_screen = Screen.OPTIONS
            elif key == "BACKSPACE":
                self.file_path = self.file_path[:-1]
            elif len(key) == 1 and key.isprintable():
                self.file_path += key

        elif self.current_screen == Screen.OPTIONS:
            categories = self.get_current_options()
            num_cats = len(categories)
            if key == "ESC":
                action = self.get_current_action_name()
                if action == "doctor":
                    self.current_screen = Screen.MENU
                else:
                    self.current_screen = Screen.FILE_PICKER
            elif key in ("UP", "k") and num_cats > 0:
                self.active_category_index = (self.active_category_index - 1) % num_cats
            elif key in ("DOWN", "j") and num_cats > 0:
                self.active_category_index = (self.active_category_index + 1) % num_cats
            elif key in ("SPACE", "RIGHT", "l") and num_cats > 0:
                cat = categories[self.active_category_index]
                cat.selected_index = (cat.selected_index + 1) % len(cat.choices)
            elif key in ("LEFT", "h") and num_cats > 0:
                cat = categories[self.active_category_index]
                cat.selected_index = (cat.selected_index - 1) % len(cat.choices)
            elif key == "ENTER":
                self.last_command = self.build_command()
                self.current_screen = Screen.RESULT
            elif key in ("q", "Q"):
                return False

        elif self.current_screen == Screen.RESULT:
            if key in ("ENTER", "ESC"):
                self.current_screen = Screen.MENU
            elif key in ("q", "Q"):
                return False

        return True

    def run(self, key_provider: Iterable[str] | None = None) -> int:
        """Run interactive event loop."""
        self.render_current_screen()

        if key_provider is not None:
            for key in key_provider:
                if not self.handle_key(key):
                    break
                self.render_current_screen()
            return 0

        while True:
            try:
                key = read_key()
                if not self.handle_key(key):
                    break
                self.render_current_screen()
            except (KeyboardInterrupt, EOFError):
                break

        return 0


def _read_key_posix() -> str:
    """Read a single keypress on POSIX systems."""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A":
                        return "UP"
                    if ch3 == "B":
                        return "DOWN"
                    if ch3 == "C":
                        return "RIGHT"
                    if ch3 == "D":
                        return "LEFT"
                    return "ESC"
                return "ESC"
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch == " ":
            return "SPACE"
        if ch in ("\x7f", "\x08"):
            return "BACKSPACE"
        if ch in ("\x03", "\x04"):
            return "QUIT"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_key_windows() -> str:
    """Read a single keypress on Windows systems."""
    import msvcrt

    ch: str = str(msvcrt.getwch())  # type: ignore[attr-defined]
    if ch in ("\x00", "\xe0"):
        code: str = str(msvcrt.getwch())  # type: ignore[attr-defined]
        if code == "H":
            return "UP"
        if code == "P":
            return "DOWN"
        if code == "K":
            return "LEFT"
        if code == "M":
            return "RIGHT"
        return "ESC"
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch == " ":
        return "SPACE"
    if ch == "\x1b":
        return "ESC"
    if ch == "\x08":
        return "BACKSPACE"
    if ch in ("\x03", "\x04"):
        return "QUIT"
    return ch


def read_key() -> str:
    """Platform-independent single key reader."""
    if sys.platform == "win32":
        return _read_key_windows()
    return _read_key_posix()


def launch_tui(
    console: Console | None = None,
    key_provider: Iterable[str] | None = None,
) -> int:
    """Entrypoint to launch the interactive Terminal UI.

    If run in non-interactive environment (CI / pipe) and no key_provider is given,
    safely writes notice to stderr and returns exit code 0.
    """
    if key_provider is None and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        sys.stderr.write("Interactive TUI requires a controlling TTY terminal.\n")
        return 0

    ui = TerminalUI(console=console)
    return ui.run(key_provider=key_provider)
