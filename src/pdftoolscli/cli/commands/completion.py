"""Shell completion script generator conforming to PLAN.md §10, CLI-002."""

from __future__ import annotations

import sys

import click
from click.shell_completion import get_completion_class

from pdftoolscli.domain.errors import ConfigError

SUPPORTED_SHELLS = ("bash", "zsh", "fish", "powershell")


@click.command("completion")
@click.argument("shell", type=click.Choice(list(SUPPORTED_SHELLS), case_sensitive=False))
@click.pass_context
def completion_cmd(ctx: click.Context, shell: str) -> None:
    """Generate tab-completion script for the specified shell (bash, zsh, fish, powershell)."""
    # Reject --json flag on completion command per PLAN.md CLI-002
    raw_args = sys.argv[1:]
    if "--json" in raw_args:
        raise ConfigError(
            "The '--json' flag is not supported for shell completion generation.",
            hint="Run 'ptc completion <shell>' without '--json'.",
        )

    shell_name = shell.lower()
    comp_cls = get_completion_class(shell_name)
    if comp_cls is None:
        raise ConfigError(
            f"Unsupported shell: '{shell}'. Supported shells: {', '.join(SUPPORTED_SHELLS)}."
        )

    # Click completion class uses root command
    root_cmd = ctx.find_root().command
    comp_obj = comp_cls(root_cmd, ctx_args={}, prog_name="ptc", complete_var="_PTC_COMPLETE")

    # Generate source script
    script = comp_obj.source()
    click.echo(script)
