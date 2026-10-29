"""Minimal launcher entry: no application/Qt/OCR imports or raw output sinks."""

import atexit
from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT_DIR / "src"))

from metroliza.shared.diagnostic_startup_probe import enabled, mark, mark_error  # noqa: E402
from metroliza.app.startup_profile import record_event  # noqa: E402

if enabled():
    atexit.register(mark, "launcher_atexit_reached")

mark("launcher_entry")
record_event("supervisor_entry")
try:
    from metroliza.app.diagnostic_launcher import main
except Exception as error:
    mark("launcher_import_failed")
    mark_error(error)
    raise
mark("launcher_imported")
record_event("supervisor_imported")


if __name__ == "__main__":
    try:
        code = main()
    except Exception as error:
        mark("launcher_main_failed")
        mark_error(error)
        raise
    raise SystemExit(code)
