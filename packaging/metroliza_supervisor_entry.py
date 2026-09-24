"""Minimal launcher entry: no application/Qt/OCR imports or raw output sinks."""

from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT_DIR / "src"))

from metroliza.shared.diagnostic_startup_probe import mark, mark_error  # noqa: E402

mark("launcher_entry")
try:
    from metroliza.app.diagnostic_launcher import main
except Exception as error:
    mark("launcher_import_failed")
    mark_error(error)
    raise
mark("launcher_imported")


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        mark("launcher_main_failed")
        mark_error(error)
        raise
    raise SystemExit(code)
