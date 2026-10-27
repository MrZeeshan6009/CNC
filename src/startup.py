"""Startup diagnostics for deployment logs.

Prints a short, judge-safe status block. Never prints or logs credential values.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_VERSION = "1.0.0"
SAMPLE_BUNDLE = Path("outputs/stretch_dataset/cnc_stretch_dataset.zip")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def diagnostics() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("version", APP_VERSION)]

    rows.append(("deepseek_configured", _yes_no(bool(os.getenv("DEEPSEEK_API_KEY")))))
    rows.append(("deepseek_model", os.getenv("DEEPSEEK_MODEL", "deepseek-flash")))
    rows.append(("sample_dataset", _yes_no(SAMPLE_BUNDLE.is_file())))

    try:
        import OCP  # noqa: F401  (cadquery-ocp provides the OpenCascade kernel)

        cad_state = "pass"
    except Exception as exc:  # pragma: no cover - environment dependent
        cad_state = f"fail ({type(exc).__name__})"
    rows.append(("cad_engine", cad_state))

    try:
        import pymupdf  # noqa: F401

        rows.append(("pdf_engine", "pass"))
    except Exception as exc:  # pragma: no cover
        rows.append(("pdf_engine", f"fail ({type(exc).__name__})"))

    rows.append(("ocr_available", _yes_no(shutil.which("tesseract") is not None)))
    return rows


def report() -> None:
    lines = ["CNC Intelligence Workbench - startup diagnostics"]
    lines.extend(f"  {name}: {value}" for name, value in diagnostics())
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    report()
    # A broken CAD engine must not silently reach judges.
    if not any(name == "cad_engine" and value == "pass" for name, value in diagnostics()):
        print("FATAL: OpenCascade is not importable; CAD analysis would fail.", file=sys.stderr, flush=True)
        raise SystemExit(1)
