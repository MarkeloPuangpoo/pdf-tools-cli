# ADR 0001: Initial Technology Stack, PDF Backends, and Process Isolation

## Status
Accepted

## Context
PDF processing involves parsing complex, potentially malformed or hostile binary streams, modifying object trees, rendering raster representations, and extracting text. To ensure high reliability, cross-platform performance, and maintainability for `pdftoolscli`, we evaluated multiple ecosystems and engines.

Critical requirements:
1. Rock-solid, standard-compliant PDF structural manipulation (cross-reference tables, object streams, encryption, page trees).
2. High-fidelity raster rendering matching modern browsers.
3. Fast plain-text extraction.
4. Protection against C++ segmentation faults, out-of-memory panics, and hostile decompression bombs.
5. Permissive licensing (MIT/Apache) without strong copyleft (GPL/AGPL) constraints.

## Decisions

### 1. Implementation Language & Packaging (ADR-001)
- **Decision**: Python 3.12+ managed via `uv`, built with `Hatchling`, and distributed via PyPI wheels and PyInstaller standalone bundles.
- **Rationale**: Python provides first-class bindings to battle-tested C++ engines (`qpdf`, `PDFium`) and modern packaging via `uv` enables sub-millisecond dependency resolution and deterministic cross-platform lockfiles.

### 2. PDF Structural Engine (ADR-002)
- **Decision**: Use `pikepdf` backed by `libqpdf`.
- **Rationale**: `qpdf` is an industry-standard PDF transformation engine with extensive real-world compliance. It handles damaged cross-reference tables, modern encryption (AES-256 R6), and stream optimization. `PyMuPDF` was rejected due to AGPL licensing.

### 3. Rendering & Text Extraction Engine (ADR-003)
- **Decision**: Use `pypdfium2` (Google PDFium).
- **Rationale**: PDFium powers Google Chrome and Android, providing world-class font rendering and layout fidelity. Unlike Poppler, PDFium is distributed as self-contained precompiled wheels without requiring external system package installations.

### 4. Process Isolation Architecture (ADR-004)
- **Decision**: PDFium C API operations and native parsing runs inside isolated, ephemeral worker processes supervised by `runtime/supervisor.py`.
- **Rationale**: PDFium is not thread-safe. Running in dedicated worker processes prevents thread race conditions and guarantees that unexpected C++ segmentation faults or memory spikes terminate only the worker, allowing the parent CLI process to clean up temporary resources and report exit code 10 cleanly.

## Consequences
- **Positive**: Strict memory and security boundaries; zero risk of CLI crashes due to native segfaults; permissive MIT licensing.
- **Negative**: Minor IPC process spawn overhead (~20ms per command invocation); requires careful serialization of requests and responses across the worker boundary.
