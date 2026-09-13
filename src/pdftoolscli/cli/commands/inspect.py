"""Command implementation for `ptc inspect` conforming to PLAN.md §12.2 (CMD-001)."""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ErrorDetail
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.inspect import InspectService


@click.command("inspect", help="Inspect document catalog, page geometry, encryption, and metadata.")
@click.argument("input_path", metavar="INPUT", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--detail",
    type=click.Choice(["basic", "all"], case_sensitive=False),
    default="basic",
    help="Level of inspection detail.",
)
@click.option(
    "--section",
    type=click.Choice(
        ["document", "pages", "security", "metadata", "fonts", "images", "outlines"],
        case_sensitive=False,
    ),
    help="Display only a specific inspection section.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.pass_context
def inspect_cmd(
    ctx: click.Context,
    input_path: Path,
    detail: str,
    section: str | None,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
) -> None:
    """Analyze and inspect document structure, page boxes, and metadata."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)

    # 1. Resolve password
    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    # 2. Run inspection
    service = InspectService()
    result = service.inspect(
        path=input_path,
        password=password,
        detail=detail.lower(),
        section=section.lower() if section else None,
    )

    is_locked = result.get("locked", False)

    # 3. Present result
    if opts.json:
        if is_locked:
            err = ErrorDetail(
                code="E_PASSWORD_REQUIRED",
                category="authentication",
                message="Password required to inspect locked document.",
                hint=(
                    "Provide a password using --password-file, --password-env, or --password-stdin."
                ),
            )
            render_json(command="inspect", status="error", data=result, errors=[err])
            ctx.exit(4)
        render_json(command="inspect", status="ok", data=result)
        return

    # Human terminal presentation
    if is_locked:
        err = ErrorDetail(
            code="E_PASSWORD_REQUIRED",
            category="authentication",
            message=f"Document '{input_path.name}' is encrypted and locked.",
            hint="Provide a password using --password-file, --password-env, or --password-stdin.",
        )
        presenter.render_error(err)
        ctx.exit(4)

    if opts.quiet:
        return

    # Document Table
    table = Table(title=f"Document: {input_path.name}", show_header=True, header_style="bold cyan")
    table.add_column("Property", style="dim", width=22)
    table.add_column("Value")

    table.add_row("File Size", f"{result['file_size_bytes']:,} bytes")
    table.add_row("PDF Version", str(result.get("pdf_version", "Unknown")))
    table.add_row("Page Count", str(result.get("page_count", 0)))
    table.add_row(
        "Encrypted",
        "[green]No[/green]"
        if not result.get("is_encrypted")
        else f"[yellow]Yes ({result.get('encryption_algorithm')})[/yellow]",
    )
    table.add_row("Linearized (Web)", "Yes" if result.get("is_linearized") else "No")
    table.add_row(
        "Digital Signatures", "[yellow]Yes[/yellow]" if result.get("has_signatures") else "No"
    )
    table.add_row("AcroForms", "Yes" if result.get("has_acroforms") else "No")
    table.add_row("Tagged PDF", "Yes" if result.get("is_tagged") else "No")

    presenter.stdout_console.print(table)

    # Metadata Table (if present)
    meta = result.get("metadata", {})
    if meta:
        m_table = Table(title="Metadata", show_header=True, header_style="bold cyan")
        m_table.add_column("Key", style="dim", width=22)
        m_table.add_column("Value")
        for k, v in meta.items():
            m_table.add_row(k, str(v))
        presenter.stdout_console.print(m_table)

    # Pages detail if requested
    pages = result.get("pages", [])
    if pages and (detail == "all" or len(pages) <= 10):
        p_table = Table(title="Pages Geometry", show_header=True, header_style="bold cyan")
        p_table.add_column("Page", justify="right", width=6)
        p_table.add_column("MediaBox", width=24)
        p_table.add_column("CropBox", width=24)
        p_table.add_column("Rotation", justify="right", width=8)

        for p in pages:
            mb_vals = p["mediabox"]
            cb_vals = p["cropbox"]
            mb = f"[{mb_vals[0]:.1f}, {mb_vals[1]:.1f}, {mb_vals[2]:.1f}, {mb_vals[3]:.1f}]"
            cb = f"[{cb_vals[0]:.1f}, {cb_vals[1]:.1f}, {cb_vals[2]:.1f}, {cb_vals[3]:.1f}]"
            p_table.add_row(str(p["page"]), mb, cb, f"{p['rotation']}°")

        presenter.stdout_console.print(p_table)

    # Extended details
    if detail == "all":
        fonts = result.get("fonts", [])
        if fonts:
            presenter.stdout_console.print(
                f"\n[bold cyan]Fonts ({len(fonts)}):[/bold cyan] {', '.join(fonts)}"
            )
        image_count = result.get("image_count", 0)
        presenter.stdout_console.print(f"[bold cyan]Embedded Images:[/bold cyan] {image_count}")
