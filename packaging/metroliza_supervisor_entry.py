"""Minimal launcher entry: no application/Qt/OCR imports or raw output sinks."""

from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT_DIR / "src"))

from metroliza.app.diagnostic_launcher import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
