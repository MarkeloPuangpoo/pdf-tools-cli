# PDF Tools CLI (`pdftoolscli`)

Fast, safe, offline PDF toolkit designed for automation, developers, and terminal workflows.

## Features

- **Strict Safety Invariants**: Input files are never overwritten in-place. All file modifications are published atomically using private temporary staging directories.
- **Process Isolation**: Native parsing and rendering (`pikepdf`/`qpdf`, `pypdfium2`/`PDFium`) run in supervised worker processes to isolate potential crashes and memory limits.
- **No Secret Leakage**: Passwords are never accepted via raw command-line flags; supported methods include environment variables, secure secret files, stdin, or interactive masked TTY prompts.
- **Machine & Human Friendly**: Clean separation of `stdout` (payloads and structured JSON v1) and `stderr` (logs, diagnostics, progress).

## Installation

```bash
uv tool install pdftoolscli
# or via pipx
pipx install pdftoolscli
```

## Quick Start

```bash
# Inspect a document
pdftoolscli inspect document.pdf

# Merge multiple PDFs
pdftoolscli merge cover.pdf chapter1.pdf -o book.pdf

# Extract page range
pdftoolscli pages extract book.pdf '1-5,last' -o excerpt.pdf
```

## License

MIT License. See [LICENSE](LICENSE) for details.
