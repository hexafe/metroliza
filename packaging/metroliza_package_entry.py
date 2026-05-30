"""Package-safe entry point for freezing Metroliza.

This file intentionally is not named ``metroliza.py``. Freezing tools may treat
the entry script basename as an importable module, and using the root launcher
can shadow the canonical ``metroliza`` package during hidden-import analysis.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

src_text = str(SRC_DIR)
if src_text in sys.path:
    sys.path.remove(src_text)
sys.path.insert(0, src_text)

from metroliza.app.bootstrap import run_application  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(run_application())
