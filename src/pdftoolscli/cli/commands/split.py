"""Split CLI command conforming to PLAN.md §12.3 C09."""

from __future__ import annotations

import time
from pathlib import Path

import click
from rich.table import Table

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.pages import PageService


@click.command("split")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Target directory to place split PDF pieces.",
)
@click.option(
    "--every",
    type=int,
    default=None,
    help="Split into chunks of N pages (defaults to 1 if neither --every nor --ranges provided).",
)
@click.option(
    "--ranges",
    type=str,
    default=None,
    help="Semicolon-separated range expressions (e.g. '1-5;6-last').",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing output files."
)
@click.pass_context
def split_cmd(
    ctx: click.Context,
    input_path: Path,
    output_dir: Path,
    every: int | None,
    ranges: str | None,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Split document into multiple parts by page interval or ranges."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)

    # Resolve password
    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    start_time = ctx.obj.get("start_time", time.monotonic())
    service = PageService()

    try:
        result = service.split(
            input_path=input_path,
            output_dir=output_dir,
            every=every,
            ranges=ranges,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        if opts.json:
            render_json(
                command="split",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Successfully split [bold]{input_path.name}[/bold] "
                f"into [bold]{result['total_parts']}[/bold] parts in [bold]{output_dir}[/bold]"
            )
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Part", justify="right", width=6)
            table.add_column("Filename", width=30)
            table.add_column("Pages", justify="right", width=8)

            for part in result["parts"]:
                table.add_row(str(part["part"]), part["filename"], str(part["page_count"]))

            presenter.stdout_console.print(table)

    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="split",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        ctx.exit(int(err.exit_code))
    except Exception as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        u_err = PDFToolsError(
            str(err),
            code="E_INTERNAL",
            exit_code=ExitCode.INTERNAL_ERROR,
        )
        if opts.json:
            render_json(
                command="split",
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))
