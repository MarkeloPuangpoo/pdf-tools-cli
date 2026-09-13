"""Environment diagnostics and dependency probing service conforming to PLAN.md §12.2 (CMD-001)."""

from __future__ import annotations

import platform
import shutil
import sys
from typing import Any

import pikepdf
import PIL
import psutil
import pypdfium2 as pdfium

OPTIONAL_EXTERNAL_TOOLS = ["ocrmypdf", "tesseract", "unpaper", "gs", "qpdf"]


class DoctorService:
    """Probes system environment, native library versions, optional CLI tools, and limits."""

    def probe(self, show_paths: bool = False) -> dict[str, Any]:
        """Probe the active execution environment."""
        # 1. Python runtime
        runtime_info = {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable if show_paths else "[sanitized]",
            "platform": sys.platform,
            "architecture": platform.machine(),
            "os": platform.system(),
        }

        pdfium_build = str(getattr(pdfium, "PDFIUM_INFO", "Unknown"))
        libraries_info = {
            "pikepdf": {
                "version": pikepdf.__version__,
                "qpdf_version": getattr(pikepdf, "__libqpdf_version__", "Unknown"),
                "status": "ready",
            },
            "pypdfium2": {
                "version": str(getattr(pdfium, "PYPDFIUM_INFO", "Unknown")),
                "pdfium_build": pdfium_build,
                "status": "ready",
            },
            "pillow": {
                "version": PIL.__version__,
                "status": "ready",
            },
            "psutil": {
                "version": psutil.__version__,
                "status": "ready",
            },
        }

        # 3. Optional external toolchains
        tools_info: dict[str, dict[str, Any]] = {}
        for tool in OPTIONAL_EXTERNAL_TOOLS:
            path = shutil.which(tool)
            if path:
                tools_info[tool] = {
                    "installed": True,
                    "status": "available",
                    "path": path if show_paths else "[in PATH]",
                }
            else:
                tools_info[tool] = {
                    "installed": False,
                    "status": "not installed (optional)",
                    "path": None,
                }

        # 4. Supported raster codecs
        supported_codecs = ["PNG", "JPEG", "WEBP", "TIFF", "BMP", "GIF"]

        # 5. Resource limit capabilities
        has_rlimit = False
        try:
            import resource

            has_rlimit = hasattr(resource, "RLIMIT_AS") or hasattr(resource, "RLIMIT_DATA")
        except ImportError:
            pass

        limit_enforcement = "hard" if has_rlimit else "monitored"
        limits_info = {
            "enforcement": limit_enforcement,
            "psutil_monitoring": True,
            "has_rlimit": has_rlimit,
        }

        return {
            "runtime": runtime_info,
            "libraries": libraries_info,
            "tools": tools_info,
            "codecs": supported_codecs,
            "limits": limits_info,
        }
