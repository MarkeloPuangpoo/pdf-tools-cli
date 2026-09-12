"""Worker process entrypoint and handler execution conforming to PLAN.md §30."""

from __future__ import annotations

import contextlib
import importlib
import sys
import time
import traceback
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from pdftoolscli.runtime.protocol import Message
from pdftoolscli.runtime.resource_limits import ResourceBudget, apply_child_resource_limits

TaskHandler = Callable[[dict[str, Any]], dict[str, Any]]

# Global registry of worker task handlers
_TASK_REGISTRY: dict[str, TaskHandler] = {}


def register_task_handler(task_type: str, handler: TaskHandler) -> None:
    """Register a handler function for a worker task type."""
    _TASK_REGISTRY[task_type] = handler


# Built-in diagnostics and testing handlers
def _builtin_echo(args: dict[str, Any]) -> dict[str, Any]:
    return {"echo": args.get("value")}


def _builtin_sleep(args: dict[str, Any]) -> dict[str, Any]:
    duration = float(args.get("duration", 1.0))
    time.sleep(duration)
    return {"done": True}


def _builtin_error(args: dict[str, Any]) -> dict[str, Any]:
    msg = str(args.get("message", "Intentional worker error"))
    raise ValueError(msg)


def _builtin_crash(args: dict[str, Any]) -> dict[str, Any]:
    code = int(args.get("code", 42))
    sys.exit(code)


def _builtin_alloc(args: dict[str, Any]) -> dict[str, Any]:
    mib = int(args.get("mib", 50))
    data = bytearray(mib * 1024 * 1024)
    time.sleep(float(args.get("hold_seconds", 0.5)))
    return {"allocated_bytes": len(data)}


register_task_handler("echo", _builtin_echo)
register_task_handler("sleep", _builtin_sleep)
register_task_handler("error", _builtin_error)
register_task_handler("crash", _builtin_crash)
register_task_handler("alloc", _builtin_alloc)


def _resolve_task_handler(task_type: str) -> TaskHandler | None:
    """Resolve task handler from registry or dynamic module import."""
    if task_type in _TASK_REGISTRY:
        return _TASK_REGISTRY[task_type]

    if ":" in task_type:
        mod_name, func_name = task_type.split(":", 1)
        try:
            mod = importlib.import_module(mod_name)
            handler = getattr(mod, func_name)
            if callable(handler):
                return handler  # type: ignore[no-any-return]
        except (ImportError, AttributeError):
            return None

    return None


def worker_process_entrypoint(
    conn: Connection,
    budget: ResourceBudget,
) -> None:
    """Isolated worker entrypoint invoked within a spawned subprocess."""
    apply_child_resource_limits(budget)

    msg: Message | None = None
    try:
        if not conn.poll(budget.timeout_seconds):
            return

        raw_data = conn.recv_bytes()
        if len(raw_data) >= 4:
            msg = Message.from_bytes(raw_data[4:])
        else:
            return

        task_type = str(msg.payload.get("task_type", ""))
        task_args = dict(msg.payload.get("args", {}))

        handler = _resolve_task_handler(task_type)
        if handler is None:
            err_msg = Message(
                type="error",
                task_id=msg.task_id,
                payload={
                    "error": f"Unknown task type '{task_type}'",
                    "code": "E_INTERNAL",
                },
            )
            conn.send_bytes(err_msg.to_bytes())
            return

        # Execute handler
        result = handler(task_args)

        res_msg = Message(
            type="result",
            task_id=msg.task_id,
            payload=result,
        )
        conn.send_bytes(res_msg.to_bytes())
    except Exception as e:
        tb = traceback.format_exc()
        with contextlib.suppress(Exception):
            err_msg = Message(
                type="error",
                task_id=msg.task_id if msg else "unknown",
                payload={
                    "error": str(e),
                    "code": getattr(e, "code", "E_INTERNAL"),
                    "traceback": tb,
                },
            )
            conn.send_bytes(err_msg.to_bytes())
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    sys.exit(0)
