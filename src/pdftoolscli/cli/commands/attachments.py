"""CLI commands for PDF document attachments conforming to PLAN.md §12.7 C45-C48 (CMD-015)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.table import Table

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.attachments import AttachmentsService


@click.group(name="attachments")
def attachments_group() -> None:
    """Manage embedded file attachments in PDF documents."""


@attachments_group.command(name="list")
@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--password",
    default=None,
    envvar="PDFTOOLS_PASSWORD",
    help="Document password for encrypted inputs.",
)
@click.pass_context
def list_cmd(ctx: click.Context, input: Path, password: str | None) -> None:
    """List embedded files and file-attachment annotations."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)
        service = AttachmentsService()
        items = service.list_attachments(input_path=input, password=resolved_pw)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments list",
                status="ok",
                data={"attachments": items, "count": len(items)},
                elapsed_ms=elapsed_ms,
            )
        else:
            if not items:
                presenter.render_data(f"No attachments found in '{input}'.")
                return

            table = Table(title=f"Attachments in {input.name} ({len(items)} found)")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Size (bytes)", justify="right")
            table.add_column("MIME Hint", style="yellow")
            table.add_column("Relation")

            for it in items:
                table.add_row(
                    it["id"],
                    it["name"],
                    str(it["size"]),
                    it["mime"],
                    it["relation"],
                )

            presenter.stdout_console.print(table)
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments list",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)


@attachments_group.command(name="extract")
@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
    help="Directory to extract attachments into.",
)
@click.option(
    "--id",
    "ids",
    multiple=True,
    help="Specific attachment ID to extract (e.g. att-0001). Repeatable.",
)
@click.option(
    "--password",
    default=None,
    envvar="PDFTOOLS_PASSWORD",
    help="Document password for encrypted inputs.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing extracted files.",
)
@click.pass_context
def extract_cmd(
    ctx: click.Context,
    input: Path,
    output_dir: Path,
    ids: tuple[str, ...],
    password: str | None,
    overwrite: bool,
) -> None:
    """Extract embedded files to directory with mode 0600 and manifest.json."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)
        service = AttachmentsService()
        result = service.extract_attachments(
            input_path=input,
            output_dir=output_dir,
            ids=list(ids) if ids else None,
            password=resolved_pw,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments extract",
                status="ok",
                data=result,
                elapsed_ms=elapsed_ms,
            )
        else:
            if not opts.quiet:
                msg = (
                    f"Successfully extracted {result['extracted_count']} attachment(s) "
                    f"to '{result['output_dir']}'."
                )
                presenter.render_success(msg)
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments extract",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)


@attachments_group.command(name="add")
@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output PDF path.",
)
@click.option(
    "--description",
    default=None,
    help="Attachment description string.",
)
@click.option(
    "--replace-name",
    default=None,
    help="Replace existing attachment with specified name (requires exactly 1 file).",
)
@click.option(
    "--password",
    default=None,
    envvar="PDFTOOLS_PASSWORD",
    help="Document password for encrypted inputs.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite output file if it exists.",
)
@click.pass_context
def add_cmd(
    ctx: click.Context,
    input: Path,
    files: tuple[Path, ...],
    output_path: Path,
    description: str | None,
    replace_name: str | None,
    password: str | None,
    overwrite: bool,
) -> None:
    """Attach local files to the PDF document catalog."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)
        service = AttachmentsService()
        result = service.add_attachments(
            input_path=input,
            files=list(files),
            output_path=output_path,
            description=description,
            replace_name=replace_name,
            password=resolved_pw,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(command="attachments add", status="ok", data=result, elapsed_ms=elapsed_ms)
        else:
            if not opts.quiet:
                msg = (
                    f"Successfully attached {result['added_count']} file(s) "
                    f"to '{result['output']}'."
                )
                presenter.render_success(msg)
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments add",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)


@attachments_group.command(name="remove")
@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--all",
    "all_attachments",
    is_flag=True,
    default=False,
    help="Remove all attachments from document.",
)
@click.option(
    "--name",
    "names",
    multiple=True,
    help="Specific attachment name to remove. Repeatable.",
)
@click.option(
    "--id",
    "ids",
    multiple=True,
    help="Specific attachment ID to remove (e.g. att-0001). Repeatable.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output PDF path.",
)
@click.option(
    "--password",
    default=None,
    envvar="PDFTOOLS_PASSWORD",
    help="Document password for encrypted inputs.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite output file if it exists.",
)
@click.pass_context
def remove_cmd(
    ctx: click.Context,
    input: Path,
    all_attachments: bool,
    names: tuple[str, ...],
    ids: tuple[str, ...],
    output_path: Path,
    password: str | None,
    overwrite: bool,
) -> None:
    """Remove attachments from document catalog and page annotations."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)
        service = AttachmentsService()
        result = service.remove_attachments(
            input_path=input,
            output_path=output_path,
            all_attachments=all_attachments,
            names=list(names) if names else None,
            ids=list(ids) if ids else None,
            password=resolved_pw,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments remove",
                status="ok",
                data=result,
                elapsed_ms=elapsed_ms,
            )
        else:
            if not opts.quiet:
                msg = (
                    f"Successfully removed {result['removed_count']} attachment(s) "
                    f"from '{result['output']}'."
                )
                presenter.render_success(msg)
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="attachments remove",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)
