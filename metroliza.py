"""Compatibility launcher for the packaged Metroliza application."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
_PACKAGE = _SRC / "metroliza"

_src_text = str(_SRC)
if _src_text in sys.path:
    sys.path.remove(_src_text)
sys.path.insert(0, _src_text)

# When this file is imported as ``metroliza`` from the repository root, expose
# the package search path so ``metroliza.*`` submodules still resolve.
__path__ = [str(_PACKAGE)]

from metroliza.app.bootstrap import (  # noqa: E402
    LICENSE_MODE_ENV,
    PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV,
    PDF_PARSER_SMOKE_FIXTURE_ENV,
    STARTUP_SMOKE_ENV,
    VERSION_DATE,
    StartupConfig,
    bootstrap_application,
    get_or_create_qapplication,
    initialize_logging,
    launch_ui,
    load_startup_config,
    log_and_exit,
    parse_env_flag,
    run_application,
    run_pdf_parser_smoke_mode,
    run_startup_smoke_mode,
    validate_license_bootstrap,
)

__all__ = [
    "LICENSE_MODE_ENV",
    "PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV",
    "PDF_PARSER_SMOKE_FIXTURE_ENV",
    "STARTUP_SMOKE_ENV",
    "VERSION_DATE",
    "StartupConfig",
    "bootstrap_application",
    "get_or_create_qapplication",
    "initialize_logging",
    "launch_ui",
    "load_startup_config",
    "log_and_exit",
    "parse_env_flag",
    "run_application",
    "run_pdf_parser_smoke_mode",
    "run_startup_smoke_mode",
    "validate_license_bootstrap",
]


if __name__ == "__main__":
    raise SystemExit(run_application())
