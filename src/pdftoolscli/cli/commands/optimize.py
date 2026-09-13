"""Optimize CLI command conforming to PLAN.md §12.4 C20 (CMD-005)."""

from __future__ import annotations

import time
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.optimization import OptimizationService


@click.command("optimize")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination optimized PDF file.",
)
@click.option(
    "--object-streams",
    type=click.Choice(["preserve", "generate", "disable"], case_sensitive=False),
    default="preserve",
    help="Object stream generation mode (default: preserve).",
)
@click.option(
    "--linearize",
    is_flag=True,
    default=False,
    help="Optimize document for Fast Web View (linearization).",
)
@click.option(
    "--keep-larger",
    is_flag=True,
    default=False,
    help="Publish candidate file even if output is larger than original.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Allow overwriting existing destination files.",
)
@click.pass_context
def optimize_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path,
    object_streams: str,
    linearize: bool,
    keep_larger: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Safely optimize PDF structure and recompress eligible streams."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = OptimizationService()
        result = service.optimize(
            input_path=input_path,
            output_path=output_path,
            object_streams=object_streams,
            linearize=linearize,
            keep_larger=keep_larger,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="optimize",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            orig_sz = result["original_size_bytes"]
            out_sz = result["output_size_bytes"]
            pct = result["savings_percent"]
            status_text = f"saved {pct}%" if pct > 0 else "no size reduction"
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Optimized [bold]{input_path.name}[/bold]: "
                f"{orig_sz} B → {out_sz} B ({status_text}) into [bold]{output_path}[/bold]"
            )

    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="optimize",
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
                command="optimize",
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))
