"""Package-safe entry point for freezing Metroliza.

This file intentionally is not named ``metroliza.py``. Freezing tools may treat
the entry script basename as an importable module, and using the root launcher
can shadow the canonical ``metroliza`` package during hidden-import analysis.
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    src_text = str(ROOT_DIR / "src")
    if src_text in sys.path:
        sys.path.remove(src_text)
    sys.path.insert(0, src_text)

from metroliza.shared.diagnostic_startup_probe import mark  # noqa: E402

mark("child_entry")

from metroliza.shared.diagnostic_transport import (  # noqa: E402
    attach_child_recorder,
    supervised_mode_requested,
)

recorder = attach_child_recorder()
mark("child_attach_returned")
if supervised_mode_requested():
    try:
        from metroliza.shared.logging_utils import ensure_application_logging

        ensure_application_logging()
    except Exception:
        pass

from metroliza.app.bootstrap import run_application  # noqa: E402

mark("child_bootstrap_imported")

if __name__ == "__main__":
    try:
        code = run_application()
        if code == 0:
            from metroliza.app.diagnostic_qualification import requested_scenario, run_qualification

            scenario = requested_scenario()
            if scenario is not None:
                code = run_qualification(scenario)
        raise SystemExit(code)
    finally:
        if recorder is not None:
            try:
                recorder.close()
            except Exception:
                pass
