"""Storage subsystem: filesystem identity, workspaces, and atomic publications."""

from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import (
    FileIdentity,
    assert_distinct_files,
    get_file_identity,
    is_same_file,
    sniff_file_format,
    sniff_magic_bytes,
)
from pdftoolscli.storage.workspace import InvocationWorkspace

__all__ = [
    "AtomicPublisher",
    "FileIdentity",
    "InvocationWorkspace",
    "assert_distinct_files",
    "get_file_identity",
    "is_same_file",
    "sniff_file_format",
    "sniff_magic_bytes",
]
