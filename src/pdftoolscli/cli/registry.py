"""Lazy command loading registry conforming to PLAN.md §10."""

from __future__ import annotations

import importlib
from typing import Any

import click


class LazyGroup(click.Group):
    """Click command group that loads subcommands on demand for rapid startup."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_commands: dict[str, str] = {}

    def add_lazy_command(self, name: str, import_path: str) -> None:
        """Register a subcommand by import path (e.g. 'pkg.module:command_func')."""
        self._lazy_commands[name] = import_path

    def list_commands(self, ctx: click.Context) -> list[str]:
        base_cmds = set(super().list_commands(ctx))
        base_cmds.update(self._lazy_commands.keys())
        return sorted(base_cmds)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name in self._lazy_commands:
            import_path = self._lazy_commands[cmd_name]
            mod_name, func_name = import_path.split(":", 1)
            mod = importlib.import_module(mod_name)
            cmd = getattr(mod, func_name)
            if isinstance(cmd, click.Command):
                return cmd

        return super().get_command(ctx, cmd_name)


def get_command_catalog(group: click.Group) -> dict[str, Any]:
    """Return structured JSON catalog describing all registered commands."""
    catalog: dict[str, Any] = {
        "name": group.name or "pdftoolscli",
        "commands": {},
    }

    ctx = click.Context(group)
    for cmd_name in group.list_commands(ctx):
        cmd = group.get_command(ctx, cmd_name)
        if cmd is not None:
            catalog["commands"][cmd_name] = {
                "name": cmd.name,
                "help": cmd.help or "",
                "options": [
                    {
                        "opts": param.opts,
                        "help": getattr(param, "help", ""),
                        "required": getattr(param, "required", False),
                    }
                    for param in cmd.params
                    if isinstance(param, click.Option)
                ],
            }

    return catalog
