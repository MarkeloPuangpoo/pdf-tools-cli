"""Process supervisor and resource monitor conforming to PLAN.md §30, §31."""

from __future__ import annotations

import contextlib
import multiprocessing
import signal
import time
import uuid
from typing import Any

import psutil

from pdftoolscli.domain.errors import ExitCode, PDFToolsError, ResourceLimitError
from pdftoolscli.runtime.protocol import Message
from pdftoolscli.runtime.resource_limits import ResourceBudget
from pdftoolscli.runtime.worker import worker_process_entrypoint


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children cleanly."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            with contextlib.suppress(psutil.NoSuchProcess):
                child.terminate()
        with contextlib.suppress(psutil.NoSuchProcess):
            parent.terminate()

        # Wait up to 2 seconds for graceful exit
        _, alive = psutil.wait_procs([parent, *children], timeout=2.0)
        for p in alive:
            with contextlib.suppress(psutil.NoSuchProcess):
                p.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


class ProcessSupervisor:
    """Supervises isolated spawned worker processes, enforcing resource budgets and deadlines."""

    def __init__(self, default_budget: ResourceBudget | None = None) -> None:
        self.default_budget = default_budget or ResourceBudget()

    def run_task(
        self,
        task_type: str,
        task_args: dict[str, Any],
        budget: ResourceBudget | None = None,
    ) -> dict[str, Any]:
        """Execute a task in an isolated worker process under resource supervision."""
        effective_budget = budget or self.default_budget
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        ctx = multiprocessing.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=True)

        proc = ctx.Process(
            target=worker_process_entrypoint,
            args=(child_conn, effective_budget),
        )

        try:
            proc.start()
        finally:
            child_conn.close()

        # Send initial task message
        task_msg = Message(
            type="task",
            task_id=task_id,
            payload={"task_type": task_type, "args": task_args},
        )
        parent_conn.send_bytes(task_msg.to_bytes())

        start_time = time.monotonic()
        msg: Message | None = None

        try:
            while proc.is_alive():
                # Check if response is ready on pipe
                if parent_conn.poll(0.02):
                    break

                elapsed = time.monotonic() - start_time
                if elapsed > effective_budget.timeout_seconds:
                    if proc.pid:
                        _kill_process_tree(proc.pid)
                    raise ResourceLimitError(
                        f"Worker task '{task_type}' exceeded timeout deadline of "
                        f"{effective_budget.timeout_seconds}s."
                    )

                # Sample memory RSS
                if proc.pid:
                    try:
                        p = psutil.Process(proc.pid)
                        total_rss = p.memory_info().rss
                        for child in p.children(recursive=True):
                            total_rss += child.memory_info().rss

                        if total_rss > effective_budget.memory_mib * 1024 * 1024:
                            _kill_process_tree(proc.pid)
                            used_mib = total_rss // (1024 * 1024)
                            raise ResourceLimitError(
                                f"Worker task '{task_type}' exceeded memory ceiling of "
                                f"{effective_budget.memory_mib} MiB (used {used_mib} MiB)."
                            )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

            try:
                if parent_conn.poll(0.1):
                    raw_resp = parent_conn.recv_bytes()
                    if len(raw_resp) >= 4:
                        msg = Message.from_bytes(raw_resp[4:])
            except (EOFError, OSError):
                msg = None

            proc.join(timeout=1.0)

            if msg is None:
                # Worker exited without returning a message
                exit_code = proc.exitcode
                if exit_code in (-signal.SIGKILL, -9, 137):
                    raise ResourceLimitError(
                        f"Worker process for task '{task_type}' was killed by OS (OOM / SIGKILL).",
                    )
                raise PDFToolsError(
                    f"Worker process for task '{task_type}' terminated unexpectedly "
                    f"with exit code {exit_code}.",
                    code="E_INTERNAL",
                    exit_code=ExitCode.INTERNAL_ERROR,
                )

            if msg.type == "error":
                err_msg = msg.payload.get("error", "Unknown worker error")
                err_code = msg.payload.get("code", "E_INTERNAL")
                raise PDFToolsError(err_msg, code=err_code, exit_code=ExitCode.INTERNAL_ERROR)

            return msg.payload
        finally:
            with contextlib.suppress(Exception):
                parent_conn.close()
            if proc.is_alive() and proc.pid:
                _kill_process_tree(proc.pid)
