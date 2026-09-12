"""Unit tests for process supervision, worker execution, and IPC protocol.

Conforms to PLAN.md §30, §31.
"""

from __future__ import annotations

import io
import time

import pytest

from pdftoolscli.domain.errors import PDFToolsError, ResourceLimitError
from pdftoolscli.runtime.protocol import (
    Message,
    read_ipc_message,
    send_ipc_message,
)
from pdftoolscli.runtime.resource_limits import ResourceBudget
from pdftoolscli.runtime.supervisor import ProcessSupervisor


def test_ipc_protocol_roundtrip() -> None:
    msg = Message(type="task", task_id="t1", payload={"key": "value", "count": 42})
    data = msg.to_bytes()
    assert len(data) > 4

    parsed = Message.from_bytes(data[4:])
    assert parsed.type == "task"
    assert parsed.task_id == "t1"
    assert parsed.payload == {"key": "value", "count": 42}


def test_ipc_stream_read_write() -> None:
    buf = io.BytesIO()
    msg = Message(type="result", task_id="t2", payload={"status": "ok"})
    send_ipc_message(buf, msg)

    buf.seek(0)
    received = read_ipc_message(buf)
    assert received is not None
    assert received.type == "result"
    assert received.payload == {"status": "ok"}


def test_ipc_stream_empty() -> None:
    buf = io.BytesIO()
    assert read_ipc_message(buf) is None


def test_supervisor_run_task_success() -> None:
    supervisor = ProcessSupervisor()
    result = supervisor.run_task("echo", {"value": "antigravity"})
    assert result == {"echo": "antigravity"}


def test_supervisor_run_task_error() -> None:
    supervisor = ProcessSupervisor()
    with pytest.raises(PDFToolsError) as exc_info:
        supervisor.run_task("error", {"message": "Intentional worker error"})
    assert "Intentional worker error" in str(exc_info.value)


def test_supervisor_timeout() -> None:
    supervisor = ProcessSupervisor()
    budget = ResourceBudget(timeout_seconds=0.3)
    start = time.monotonic()
    with pytest.raises(ResourceLimitError) as exc_info:
        supervisor.run_task("sleep", {"duration": 2.0}, budget=budget)
    elapsed = time.monotonic() - start
    assert "exceeded timeout" in str(exc_info.value)
    # Ensure worker was killed promptly
    assert elapsed < 2.0


def test_supervisor_worker_crash() -> None:
    supervisor = ProcessSupervisor()
    with pytest.raises(PDFToolsError) as exc_info:
        supervisor.run_task("crash", {"code": 42})
    assert "terminated unexpectedly with exit code 42" in str(exc_info.value)
    assert exc_info.value.code == "E_INTERNAL"
    assert exc_info.value.exit_code == 10


def test_supervisor_memory_limit() -> None:
    supervisor = ProcessSupervisor()
    # 25 MiB budget, allocation of 60 MiB
    budget = ResourceBudget(memory_mib=25, timeout_seconds=5.0)
    with pytest.raises(ResourceLimitError) as exc_info:
        supervisor.run_task("alloc", {"mib": 60, "hold_seconds": 1.0}, budget=budget)
    assert "exceeded memory ceiling" in str(exc_info.value)
