"""Package-safe entry point for freezing Metroliza.

This file intentionally is not named ``metroliza.py``. Freezing tools may treat
the entry script basename as an importable module, and using the root launcher
can shadow the canonical ``metroliza`` package during hidden-import analysis.
"""

from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT_DIR = Path(__file__).resolve().parents[1]
    src_text = str(ROOT_DIR / "src")
    if src_text in sys.path:
        sys.path.remove(src_text)
    sys.path.insert(0, src_text)

from metroliza.shared.diagnostic_fatal_probe import (  # noqa: E402
    enable_private_fatal_probe, register_private_exit_inventory,
)

# First entry callback, hence last under atexit's LIFO ordering. In particular
# the child_atexit_reached marker below runs before the inventory.
register_private_exit_inventory()
enable_private_fatal_probe()

from metroliza.shared.compute_worker import use_native_windows_version  # noqa: E402

# Install the same native fallback for ordinary and qualified packaged parents
# before bootstrap or lazy NumPy/platform users can invoke cmd /c ver.
use_native_windows_version()

from metroliza.shared.diagnostic_startup_probe import enabled, mark, mark_error  # noqa: E402

if enabled():
    atexit.register(mark, "child_atexit_reached")

QUALIFICATION_GATE_ENV = "METROLIZA_STARTUP_SMOKE"

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
        mark("child_application_returned")
        # Every qualification scenario is gated on METROLIZA_STARTUP_SMOKE=1. Check that
        # gate before importing the harness, so an ordinary user's clean exit never
        # imports test-only code (an import failure there would turn exit 0 into a crash).
        if code == 0 and os.environ.get(QUALIFICATION_GATE_ENV) == "1":
            from metroliza.app.diagnostic_qualification import requested_scenario, run_qualification

            scenario = requested_scenario()
            if scenario is not None:
                code = run_qualification(scenario)
            else:
                from metroliza.app.windows_candidate_qualification import (
                    requested_scenario as requested_candidate_scenario,
                    run_qualification as run_candidate_qualification,
                )

                if os.environ.get("METROLIZA_COMPUTE_QUALIFICATION_ROOT"):
                    from metroliza.app.compute_worker_qualification import run_qualification as run_compute_qualification

                    code = run_compute_qualification()
                elif requested_candidate_scenario() is not None:
                    code = run_candidate_qualification()
            mark("child_qualification_returned")
        mark("child_exit_zero" if code == 0 else "child_exit_nonzero")
        raise SystemExit(code)
    except Exception as error:
        mark("child_main_failed")
        mark_error(error)
        raise
    finally:
        if recorder is not None:
            mark("child_recorder_close_entered")
            try:
                recorder.close()
                mark("child_recorder_close_returned")
            except Exception as error:
                mark("child_recorder_close_failed")
                mark_error(error)
                pass
