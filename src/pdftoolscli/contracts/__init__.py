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
from pdftoolscli.contracts.rendering import (
    MAX_PIXELS_PER_PAGE,
    Renderer,
    RenderResult,
    RenderSpec,
)
from pdftoolscli.contracts.secrets import SecretProvider, SecretValue
from pdftoolscli.contracts.text import (
    TextBox,
    TextExtractor,
    TextExtractSpec,
    TextPageResult,
)

__all__ = [
    "DocumentInfo",
    "EditingBackend",
    "EncryptionSpec",
    "MAX_PIXELS_PER_PAGE",
    "OutlineNode",
    "PageBox",
    "PageInfo",
    "RenderResult",
    "RenderSpec",
    "Renderer",
    "SafeDocumentHandle",
    "SecretProvider",
    "SecretValue",
    "TextBox",
    "TextExtractSpec",
    "TextExtractor",
    "TextPageResult",
]
