"""Command implementation for `ptc validate` conforming to PLAN.md §12.2 (CMD-001)."""

from __future__ import annotations

from pathlib import Path

import click
import pikepdf
from rich.panel import Panel

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import (
    ErrorDetail,
    PDFInvalidError,
)
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.validation import CatalogValidator


@click.command("validate", help="Validate PDF syntax, cross-references, and catalog integrity.")
@click.argument("input_path", metavar="INPUT", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--strict", is_flag=True, default=False, help="Strict mode: treat syntax warnings as errors."
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.pass_context
def validate_cmd(
    ctx: click.Context,
    input_path: Path,
    strict: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
) -> None:
    """Validate PDF document structure and catalog invariants."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)

    # 1. Resolve password
    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    warnings: list[ErrorDetail] = []
    errors: list[ErrorDetail] = []
    is_valid = True

    try:
        # Open with recovery disabled to detect syntax defects
        pdf = pikepdf.open(input_path, password=password or "", attempt_recovery=False)
        try:
            page_count = len(pdf.pages)
            if page_count == 0:
                is_valid = False
                errors.append(
                    ErrorDetail(
                        code="E_PDF_INVALID",
                        category="document",
                        message="Document has 0 pages (empty catalog).",
                    )
                )

            # Check digital signatures
            if CatalogValidator.has_digital_signatures(pdf):
                warnings.append(
                    ErrorDetail(
                        code="W_SIGNATURE_PRESENT",
                        category="safety",
                        message="Document contains digital signatures.",
                    )
                )

        finally:
            pdf.close()

    except pikepdf.PasswordError as p_err:
        err = ErrorDetail(
            code="E_PASSWORD_REQUIRED" if not password else "E_PASSWORD_INVALID",
            category="authentication",
            message=str(p_err) or "Password required or invalid.",
            hint=(
                "Provide a valid password using --password-file, "
                "--password-env, or --password-stdin."
            ),
        )
        if opts.json:
            render_json(command="validate", status="error", errors=[err])
        else:
            presenter.render_error(err)
        ctx.exit(4)

    except (pikepdf.PdfError, PDFInvalidError) as v_err:
        is_valid = False
        errors.append(
            ErrorDetail(
                code="E_PDF_INVALID",
                category="document",
                message=f"Validation error: {v_err}",
                details=str(v_err),
            )
        )

    # If strict mode is enabled and there are warnings, treat as failure
    if strict and warnings:
        is_valid = False
        for w in warnings:
            errors.append(
                ErrorDetail(
                    code="E_STRICT_FAILURE",
                    category="validation",
                    message=f"Strict validation failed on warning: {w.message}",
                )
            )

    data = {
        "filename": input_path.name,
        "valid": is_valid,
        "strict": strict,
        "warning_count": len(warnings),
        "error_count": len(errors),
    }

    if opts.json:
        status = "ok" if is_valid else "error"
        render_json(command="validate", status=status, data=data, warnings=warnings, errors=errors)
        if not is_valid:
            ctx.exit(5)
        return

    if not is_valid:
        for err in errors:
            presenter.render_error(err)
        ctx.exit(5)

    if not opts.quiet:
        panel = Panel(
            f"[bold green]✓[/bold green] Document '{input_path.name}' is syntactically valid.",
            border_style="green",
            expand=False,
        )
        presenter.stdout_console.print(panel)
        for w in warnings:
            presenter.render_warning(w)
