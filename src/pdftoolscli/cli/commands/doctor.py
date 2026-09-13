"""Command implementation for `ptc doctor` conforming to PLAN.md §12.2 (CMD-001)."""

from __future__ import annotations

import click
from rich.table import Table

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.doctor import DoctorService


@click.command("doctor", help="Inspect runtime environment, native libraries, and limits.")
@click.option("--paths", is_flag=True, default=False, help="Display absolute filesystem paths.")
@click.pass_context
def doctor_cmd(
    ctx: click.Context,
    paths: bool,
) -> None:
    """Validate runtime environment, toolchains, native libraries, and resource budgets."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)

    service = DoctorService()
    probe_data = service.probe(show_paths=paths)

    if opts.json:
        render_json(command="doctor", status="ok", data=probe_data)
        return

    if opts.quiet:
        return

    # 1. Runtime
    rt = probe_data["runtime"]
    rt_table = Table(title="System & Runtime", show_header=True, header_style="bold cyan")
    rt_table.add_column("Component", style="dim", width=22)
    rt_table.add_column("Details")
    rt_table.add_row("Python", f"{rt['version']} ({rt['implementation']})")
    rt_table.add_row("Executable", str(rt["executable"]))
    rt_table.add_row("Platform / OS", f"{rt['os']} ({rt['architecture']})")
    presenter.stdout_console.print(rt_table)

    # 2. Native PDF Libraries
    libs = probe_data["libraries"]
    lib_table = Table(title="Core Native Libraries", show_header=True, header_style="bold cyan")
    lib_table.add_column("Library", style="dim", width=22)
    lib_table.add_column("Version", width=18)
    lib_table.add_column("Backend Details", width=24)
    lib_table.add_column("Status")

    lib_table.add_row(
        "pikepdf",
        libs["pikepdf"]["version"],
        f"libqpdf {libs['pikepdf']['qpdf_version']}",
        "[green]Ready[/green]",
    )
    lib_table.add_row(
        "pypdfium2",
        libs["pypdfium2"]["version"],
        f"PDFium {libs['pypdfium2']['pdfium_build']}",
        "[green]Ready[/green]",
    )
    lib_table.add_row(
        "Pillow", libs["pillow"]["version"], "Image raster codecs", "[green]Ready[/green]"
    )
    lib_table.add_row(
        "psutil", libs["psutil"]["version"], "Process monitoring", "[green]Ready[/green]"
    )
    presenter.stdout_console.print(lib_table)

    # 3. Optional Tools
    tools = probe_data["tools"]
    t_table = Table(
        title="Optional External Toolchains", show_header=True, header_style="bold cyan"
    )
    t_table.add_column("Tool", style="dim", width=22)
    t_table.add_column("Status", width=24)
    t_table.add_column("Location")

    for tool_name, t_info in tools.items():
        status_str = (
            "[green]Available[/green]"
            if t_info["installed"]
            else "[dim]Not installed (optional)[/dim]"
        )
        loc = t_info["path"] or "-"
        t_table.add_row(tool_name, status_str, loc)
    presenter.stdout_console.print(t_table)

    # 4. Limits & Enforcements
    lim = probe_data["limits"]
    lim_table = Table(title="Platform Resource Limits", show_header=True, header_style="bold cyan")
    lim_table.add_column("Property", style="dim", width=22)
    lim_table.add_column("Value")
    lim_table.add_row("Limit Enforcement", f"[bold green]{lim['enforcement']}[/bold green]")
    lim_table.add_row("psutil Monitoring", "Active" if lim["psutil_monitoring"] else "Inactive")
    lim_table.add_row("POSIX RLIMIT", "Supported" if lim["has_rlimit"] else "Unavailable")
    presenter.stdout_console.print(lim_table)
