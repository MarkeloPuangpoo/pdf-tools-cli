"""Domain contracts and interfaces."""

from pdftoolscli.contracts.editing import (
    DocumentInfo,
    EditingBackend,
    EncryptionSpec,
    OutlineNode,
    PageBox,
    PageInfo,
    SafeDocumentHandle,
)
from pdftoolscli.contracts.secrets import SecretProvider, SecretValue

__all__ = [
    "DocumentInfo",
    "EditingBackend",
    "EncryptionSpec",
    "OutlineNode",
    "PageBox",
    "PageInfo",
    "SafeDocumentHandle",
    "SecretProvider",
    "SecretValue",
]
