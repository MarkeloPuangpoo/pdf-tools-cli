"""Text extraction CLI commands conforming to PLAN.md §12.5 C26 (CMD-006)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.text import TextService


@click.group("text")
def text_group() -> None:
    """Extract and search text content from PDF documents."""


@text_group.command("extract")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--pages",
    "pages_range",
    type=str,
    default=None,
    help="Page range sequence to extract (e.g. 1-5, odd, last).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Target destination text file, or '-' for stdout.",
)
@click.option(
    "--require-text",
    is_flag=True,
    default=False,
    help="Fail with exit code 5 if document contains no extractable text layer.",
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
def extract_text_cmd(
    ctx: click.Context,
    input_path: Path,
    pages_range: str | None,
    output_path: str | None,
    require_text: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Extract plain text streams to stdout or file using PDFium."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    dest_file: Path | None = None
    if output_path and output_path != "-":
        dest_file = Path(output_path)

    try:
        service = TextService()
        result = service.extract(
            input_path=input_path,
            range_expr=pages_range,
            output_path=dest_file,
            require_text=require_text,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        if opts.json:
            if dest_file is not None:
                # With file output, do not duplicate large text payload
                json_data = {
                    "input": result["input"],
                    "output": result["output"],
                    "total_pages": result["total_pages"],
                    "char_count": result["char_count"],
                    "has_text": result["has_text"],
                }
            else:
                json_data = result

            render_json(
                command="text extract",
                status="success",
                data=json_data,
                elapsed_ms=elapsed_ms,
            )
            return

        if dest_file is None:
            # Emit raw plain text cleanly to stdout for piping/redirection
            sys.stdout.write(result["text"])
            if not result["text"].endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            if not opts.quiet:
                presenter.stdout_console.print(
                    f"[bold green]✓[/bold green] Extracted text ({result['char_count']} chars, "
                    f"{result['total_pages']} pages) into [bold]{dest_file}[/bold]"
                )

    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="text extract",
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
                command="text extract",
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))
