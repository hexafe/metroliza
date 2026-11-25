"""Opt-in declarative profile journey for the private candidate process."""
from __future__ import annotations

import stat
from pathlib import Path

from metroliza.app.windows_candidate_import_sync import run_ui_import
from metroliza.app.windows_candidate_native_check import close_report_owner
from metroliza.app.windows_candidate_qualification import ScenarioFailure, _sha256, _wait
from metroliza.parsing.preflight import ParsePreflightStatus

PLUGIN = "synthetic_package_profile"
PROFILE = rb"""schema_version: 1
plugin:
  plugin_id: synthetic_package_profile
  display_name: Synthetic packaged profile
  version: 0.1.0
  source_format: pdf
  supported_locales: ["*"]
  template_ids: [synthetic_package_template]
  priority: 910
probe:
  required_markers: ["SYNTHETIC PACKAGE PROFILE"]
  reject_markers: []
  confidence: 91
extraction:
  report_fields:
    reference: '^Reference:\s*(?P<value>\S+)$'
    report_date: '^Date:\s*(?P<value>\d{4}-\d{2}-\d{2})$'
    sample_number: '^Sample:\s*(?P<value>\S+)$'
  blocks:
    - header: "TEST FEATURE"
      pattern: '^DIM\s+(?P<axis_code>\w+)\s+(?P<nominal>[-0-9.]+)\s+(?P<tol_plus>[-0-9.]+)\s+(?P<tol_minus>[-0-9.]+)\s+(?P<bonus>[-0-9.]+)\s+(?P<measured>[-0-9.]+)\s+(?P<deviation>[-0-9.]+)\s+(?P<out_of_tolerance>[-0-9.]+)$'
normalization:
  decimal_separator: "."
  date_formats: ["%Y-%m-%d"]
"""
EXPECTED = (
    b"sample_file,reference,report_date,sample_number,block_index,header_normalized,"
    b"axis_code,nominal,tol_plus,tol_minus,bonus,measured,deviation,out_of_tolerance\n"
    b"profile-sample.pdf,REF-A,2026-01-05,0007,0,TEST FEATURE,X,10,0.2,-0.2,,10.09,0.09,0\n"
    b"profile-sample.pdf,REF-A,2026-01-05,0007,0,TEST FEATURE,Y,20,0.2,-0.2,0.01,20.35,0.35,0.14\n"
)


def verify_profile_probe_home(profile_home: Path) -> Path:
    """Check the isolated default store before a probe can trigger discovery."""
    from metroliza.parsing.declarative_parser_profiles import approved_profiles_dir
    from metroliza.parsing.parser_plugin_paths import configured_external_plugin_path_entries, disabled_plugin_ids

    store = profile_home / ".metroliza" / "parser_plugins"
    approved = store / "profiles" / "approved" / PLUGIN
    if (Path.home() != profile_home or configured_external_plugin_path_entries() != (str(store),) or disabled_plugin_ids()
            or approved_profiles_dir() / PLUGIN != approved):
        raise ScenarioFailure("profile_probe_home_mismatch")
    for directory in (profile_home, store.parent, store, store / "profiles", approved.parent):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            if directory == profile_home:
                raise ScenarioFailure("profile_probe_home_mismatch") from None
        else:
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ScenarioFailure("profile_probe_home_mismatch")
    if approved.exists() or approved.is_symlink():
        raise ScenarioFailure("profile_probe_home_mismatch")
    return approved


def _prepare_inputs(scratch: Path) -> tuple[Path, Path, Path]:
    from metroliza.parsing.pdf_backend import require_pdf_backend

    scratch.mkdir()
    samples = scratch / "samples"
    samples.mkdir()
    profile, expected, sample = scratch / "profile.yaml", scratch / "expected.csv", samples / "profile-sample.pdf"
    profile.write_bytes(PROFILE)
    expected.write_bytes(EXPECTED)
    with require_pdf_backend().open() as document:
        page = document.new_page()
        page.insert_text((72, 72), (
            "SYNTHETIC PACKAGE PROFILE\nReference: REF-A\nDate: 2026-01-05\nSample: 0007\n"
            "DIM X 10 0.2 -0.2 - 10.09 0.09 0\nDIM Y 20 0.2 -0.2 0.01 20.35 0.35 0.14"
        ))
        document.save(sample)
    return profile, expected, sample


def _review_mismatch(
    workspace, previous, source: Path, occurrence: str, sample_sha256: str, status: ParsePreflightStatus,
) -> str | None:
    result = workspace._preflight_result
    if result is None or result is previous:
        return "no_fresh_review"
    if not workspace._preflight_is_current():
        return "request_not_current"
    if len(result.files) != 1:
        return "file_count"
    item, = result.files
    if item.status is not status:
        return f"status_{item.status.value}" if isinstance(item.status, ParsePreflightStatus) else "status_invalid"
    try:
        observed_source = Path(item.source_path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError, TypeError):
        return "source_unavailable"
    if observed_source != source:
        return "source_path"
    if item.stable_occurrence_id != occurrence:
        return "occurrence"
    if item.fingerprint != f"sha256:{sample_sha256}":
        return "fingerprint"
    return None


def _require_review(
    workspace, app, source: Path, occurrence: str, sample_sha256: str, database: Path, *, approved: bool,
) -> None:
    phase = "approved" if approved else "unapproved"
    status = ParsePreflightStatus.READY if approved else ParsePreflightStatus.UNSUPPORTED
    previous = workspace._preflight_result
    workspace.scan_button.click()
    _wait(app, lambda: workspace.preflight_thread is None and workspace.metadata_thread is None,
          deadline_s=30, stage=f"profile_probe_{phase}_review")
    mismatch = _review_mismatch(workspace, previous, source, occurrence, sample_sha256, status)
    if mismatch is not None:
        raise ScenarioFailure(f"profile_probe_{phase}_{mismatch}")
    selected = workspace.report_planner.model.selected_ids
    if (approved and selected != (occurrence,)) or (not approved and selected):
        raise ScenarioFailure(f"profile_probe_{phase}_selection")
    if not approved and workspace.parse_button.isEnabled():
        raise ScenarioFailure("profile_probe_unapproved_parse_enabled")
    if database.exists():
        raise ScenarioFailure(f"profile_probe_{phase}_database_exists")


def run_profile_probe(scratch: Path, profile_home: Path, app) -> dict:
    """Use the actual default store and Reports workflow inside an already isolated process."""
    from importlib import import_module

    from PyQt6.QtCore import QSettings

    from metroliza.app.ui_entrypoint import load_main_window_factory
    from metroliza.parsing.declarative_parser_profiles import install_profile
    from metroliza.parsing.parser_plugin_paths import invalidate_parser_plugin_runtime

    UiPreferences = import_module("metroliza.ui.ui_preferences").UiPreferences

    approved = verify_profile_probe_home(profile_home)
    profile, expected, sample = _prepare_inputs(scratch)
    try:
        source = sample.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise ScenarioFailure("profile_probe_sample_path_unavailable") from None
    input_paths = {"profile": profile, "expected": expected, "sample": sample}
    inputs = {name: _sha256(path) for name, path in input_paths.items()}
    database = scratch / "profile-import.sqlite"
    settings = QSettings(str(scratch / "settings.ini"), QSettings.Format.IniFormat)
    window = load_main_window_factory()("candidate-profile-probe", None, ui_preferences=UiPreferences(settings))
    try:
        window.show()
        app.processEvents()
        window.navigation_list.setCurrentRow(window.navigation_combo.findData("reports"))
        if not window.set_directory(str(sample.parent)) or not window.set_db_file(str(database)):
            raise ScenarioFailure("profile_probe_reports_context")
        workspace = window.reports_workspace
        invalidate_parser_plugin_runtime()
        _require_review(workspace, app, source, sample.name, inputs["sample"], database, approved=False)
        installed = install_profile(
            profile, sample_paths=(sample,), expected_results_ref=expected, approved_by="synthetic-candidate"
        )
        if installed.approved_dir != approved or installed.sha256 != inputs["profile"] or installed.backup_dir:
            raise ScenarioFailure("profile_probe_approval")
        approval = _sha256(installed.approval_path)
        _require_review(workspace, app, source, sample.name, inputs["sample"], database, approved=True)
        result = run_ui_import(workspace, app)
        if result is None or result.imported_files != 1 or result.failed_files != 0:
            raise ScenarioFailure("profile_probe_import_count")
    finally:
        close_report_owner(window, app)
    if (any(_sha256(path) != inputs[name] for name, path in input_paths.items())
            or _sha256(installed.profile_path) != inputs["profile"] or _sha256(installed.approval_path) != approval):
        raise ScenarioFailure("profile_probe_input_changed")
    return {"inputs": inputs, "approval_sha256": approval, "database_sha256": _sha256(database)}
