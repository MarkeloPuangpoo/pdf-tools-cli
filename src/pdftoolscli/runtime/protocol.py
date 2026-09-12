"""Length-prefixed JSON IPC message protocol conforming to PLAN.md §30."""

from __future__ import annotations

import json
import struct
from dataclasses import asdict, dataclass
from typing import Any, BinaryIO

MAX_IPC_MESSAGE_BYTES = 10 * 1024 * 1024  # 10 MiB frame limit


@dataclass(frozen=True)
class Message:
    type: str
    task_id: str
    payload: dict[str, Any]

    def to_bytes(self) -> bytes:
        data = json.dumps(asdict(self)).encode("utf-8")
        if len(data) > MAX_IPC_MESSAGE_BYTES:
            raise ValueError(
                f"IPC message size {len(data)} exceeds maximum {MAX_IPC_MESSAGE_BYTES}"
            )
        header = struct.pack(">I", len(data))
        return header + data

    @classmethod
    def from_bytes(cls, data: bytes) -> Message:
        obj = json.loads(data.decode("utf-8"))
        return cls(
            type=str(obj["type"]),
            task_id=str(obj["task_id"]),
            payload=dict(obj.get("payload", {})),
        )


def send_ipc_message(stream: BinaryIO, msg: Message) -> None:
    """Send a length-prefixed JSON IPC message over a binary stream."""
    stream.write(msg.to_bytes())
    stream.flush()


def read_ipc_message(stream: BinaryIO) -> Message | None:
    """Read a length-prefixed JSON IPC message from a binary stream.

    Returns None if stream reaches EOF before header.
    """
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        raise EOFError("Incomplete IPC message header read")

    (msg_len,) = struct.unpack(">I", header)
    if msg_len > MAX_IPC_MESSAGE_BYTES:
        raise ValueError(f"IPC message length {msg_len} exceeds maximum allowed")

    data = stream.read(msg_len)
    if len(data) < msg_len:
        raise EOFError(f"Expected {msg_len} bytes for IPC message, got {len(data)}")

    return Message.from_bytes(data)
