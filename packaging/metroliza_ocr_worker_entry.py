"""Minimal onedir OCR worker entry; no Qt or diagnostic output."""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    src_text = str(ROOT_DIR / "src")
    if src_text in sys.path:
        sys.path.remove(src_text)
    sys.path.insert(0, src_text)

from metroliza.parsing.frozen_ocr_worker import worker_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(worker_main())
