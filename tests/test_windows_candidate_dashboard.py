from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

from metroliza.industrial.realtime.realtime_dashboard_html import (
    write_realtime_dashboard_html,
)
from scripts.verify_windows_candidate_dashboard import (
    MODEL_FACETS,
    REQUIRED_SECTIONS,
    VIEWPORTS,
    verify_dashboard,
    validate_receipt,
)


def _write_synthetic_dashboard(path: Path) -> Path:
    return write_realtime_dashboard_html(
        {
            "title": "Synthetic offline dashboard",
            "generated_at": "2026-06-13T10:02:00Z",
            "signals": [
                {
                    "id": 1,
                    "signal_key": "cycle_time",
                    "metric_name": "cycle_time_s",
                    "unit": "s",
                    "source_name": "Synthetic Assembly",
                    "samples": [
                        {
                            "id": 1,
                            "event_time": "2026-06-13T10:00:00Z",
                            "value": 10.25,
                        },
                        {
                            "id": 2,
                            "event_time": "2026-06-13T10:01:00Z",
                            "value": 11.0,
                        },
                    ],
                }
            ],
        },
        path,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_hash_mismatch_is_rejected_without_claiming_browser_rendering(tmp_path):
    dashboard = _write_synthetic_dashboard(tmp_path / "dashboard.html")
    browser = Path(shutil.which("chromium") or shutil.which("google-chrome") or __file__)

    receipt = verify_dashboard(
        dashboard.resolve(),
        "0" * 64,
        browser.resolve(),
        tmp_path.resolve(),
    )

    assert receipt["status"] == "failed"
    assert receipt["error_codes"] == ["input_hash_mismatch"]
    assert receipt["facets"] == dict.fromkeys(MODEL_FACETS, "not_run")
    assert receipt["evidence"]["viewports"] == []
    assert receipt["evidence"]["browser_disconnected"] is False
    assert receipt["evidence"]["profile_removed"] is False


def test_browser_path_must_be_an_existing_absolute_regular_file(tmp_path):
    dashboard = _write_synthetic_dashboard(tmp_path / "dashboard.html")

    receipt = verify_dashboard(
        dashboard.resolve(),
        _sha256(dashboard),
        tmp_path / "missing-browser",
        tmp_path.resolve(),
    )

    assert receipt["status"] == "failed"
    assert receipt["error_codes"] == ["browser_executable_invalid"]
    assert receipt["facets"] == dict.fromkeys(MODEL_FACETS, "not_run")


def _source_receipt():
    path = Path(__file__).parent / "fixtures/windows_candidate_protocol/browser-source-engineering-receipt.json"
    return json.loads(path.read_text())


def test_candidate_cli_requires_explicit_browser_before_launch(tmp_path, monkeypatch, capsys):
    from scripts import qualify_windows_candidate_core as driver

    observed = []
    monkeypatch.setattr(driver, "qualify", observed.append)
    argv = ["qualify_windows_candidate_core.py", "--expected-source-sha", "a" * 40]
    for name in ("source-checkout", "artifact-dir", "fixture-dir", "output-dir", "oracle"):
        argv.extend(("--" + name, str(tmp_path / name)))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as caught:
        driver.main()
    assert caught.value.code == 2
    assert "--browser" in capsys.readouterr().err
    assert observed == []

    browser = tmp_path / "approved browser.exe"
    monkeypatch.setattr(sys, "argv", [*argv, "--browser", str(browser)])
    assert driver.main() == 0
    assert len(observed) == 1 and observed[0].browser == browser


def test_actual_source_browser_receipt_is_not_windows_evidence():
    value = _source_receipt()
    digest = value["evidence"]["input_sha256"]
    assert validate_receipt(value, digest, require_windows=False) is value
    with pytest.raises(ValueError, match="browser_windows_proof_missing"):
        validate_receipt(value, digest)


@pytest.mark.parametrize("field,bad_value", [
    ("input_sha256", "0" * 64), ("input_size", True),
    ("browser_version", "unexpected-private-path"), ("automation_driver", "unknown"),
    ("browser_disconnected", False), ("profile_removed", False), ("source_unchanged", False),
    ("network_request_count", True), ("network_request_schemes", ["https"]), ("viewports", []),
])
def test_candidate_browser_gate_rejects_wrong_binding_or_incomplete_evidence(field, bad_value):
    value = _source_receipt()
    digest = value["evidence"]["input_sha256"]
    value["evidence"]["host_platform"] = "win32"  # Protocol test only; never a native receipt.
    value["evidence"][field] = bad_value
    with pytest.raises(ValueError):
        validate_receipt(value, digest)


def test_browser_viewport_counters_cannot_be_boolean_success_markers():
    value = _source_receipt()
    value["evidence"]["viewports"][0]["global_overflow_px"] = False
    with pytest.raises(ValueError, match="browser_dom_mismatch"):
        validate_receipt(value, value["evidence"]["input_sha256"], require_windows=False)


def test_browser_host_requires_the_current_dashboard_hash_and_retains_only_closed_proof(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts import qualify_windows_candidate_core as driver
    from scripts import verify_windows_candidate_dashboard as verifier

    value = _source_receipt()
    value["evidence"]["host_platform"] = "win32"  # Synthetic protocol control, no browser launched.
    digest = value["evidence"]["input_sha256"]
    called = []

    def render(path, expected, browser, private):
        called.append((path, expected, browser, private))
        return value

    monkeypatch.setattr(driver, "_adjacent_module", lambda *_args: SimpleNamespace(
        verify_dashboard=render, validate_receipt=verifier.validate_receipt
    ))
    diag = SimpleNamespace(_run_in_private_directory=lambda action: action(tmp_path / "owned"))
    artifacts = {"private_dashboard": {"path": "dashboard.html", "sha256": "0" * 64}}
    with pytest.raises(driver.CandidateFailure, match="offline_browser_verification_failed"):
        driver._verify_dashboard_rendering(diag, tmp_path, artifacts, tmp_path / "browser.exe")
    assert not (tmp_path / "browser-observation.json").exists()
    artifacts["private_dashboard"]["sha256"] = digest
    driver._verify_dashboard_rendering(diag, tmp_path, artifacts, tmp_path / "browser.exe")
    assert called[-1] == (tmp_path / "dashboard.html", digest, tmp_path / "browser.exe", tmp_path / "owned")
    retained = tmp_path / artifacts["browser_evidence"]["path"]
    assert _sha256(retained) == artifacts["browser_evidence"]["sha256"]
    assert json.loads(retained.read_text()) == value


browser_available = pytest.mark.skipif(
    shutil.which("chromium") is None or importlib.util.find_spec("playwright") is None,
    reason="explicit host browser and Playwright are required",
)


@browser_available
def test_real_chromium_executes_dom_and_layout_in_an_isolated_profile(tmp_path):
    dashboard = _write_synthetic_dashboard(tmp_path / "dashboard.html")
    digest = _sha256(dashboard)
    before = dashboard.read_bytes()

    receipt = verify_dashboard(
        dashboard.resolve(),
        digest,
        Path(shutil.which("chromium")).resolve(),
        tmp_path.resolve(),
    )

    assert receipt["status"] == "passed", receipt
    assert receipt["error_codes"] == []
    assert receipt["facets"] == dict.fromkeys(MODEL_FACETS, "passed")
    evidence = receipt["evidence"]
    assert evidence["input_sha256"] == digest
    assert evidence["input_size"] == len(before)
    assert evidence["browser_version"]
    assert evidence["automation_driver"] == "playwright-1.63.0"
    assert evidence["browser_disconnected"] is True
    assert evidence["host_platform"] == "linux"
    assert evidence["network_request_count"] == len(VIEWPORTS)
    assert evidence["network_request_schemes"] == ["file"]
    assert evidence["profile_removed"] is True
    assert evidence["source_unchanged"] is True
    assert dashboard.read_bytes() == before
    assert [item["name"] for item in evidence["viewports"]] == [
        item["name"] for item in VIEWPORTS
    ]
    for viewport, expected in zip(evidence["viewports"], VIEWPORTS, strict=True):
        assert viewport["ready_state"] == "complete"
        assert viewport["js_evaluated"] is True
        assert viewport["viewport_width"] == expected["width"]
        assert viewport["viewport_height"] == expected["height"]
        assert viewport["required_sections_match"] is True
        assert viewport["section_count"] == len(REQUIRED_SECTIONS)
        assert viewport["signal_panel_count"] == 1
        assert viewport["signal_chart_count"] == 1
        assert viewport["sample_point_count"] == 2
        assert viewport["global_overflow_px"] == 0
        assert viewport["clipped_element_count"] == 0
        assert viewport["table_scroll_violation_count"] == 0
        assert viewport["external_reference_count"] == 0
        assert viewport["resource_entry_count"] == 0
        assert viewport["inline_script_count"] == 0


@browser_available
@pytest.mark.parametrize("defect", ["overflow", "external_resource"])
def test_real_browser_rejects_layout_or_external_resource_and_closes_its_profile(tmp_path, defect):
    dashboard = _write_synthetic_dashboard(tmp_path / "dashboard.html")
    content = dashboard.read_text()
    if defect == "overflow":
        content = content.replace("</style>", "body { min-width: 2000px; }</style>")
    else:
        content = content.replace("</body>", '<img src="https://example.invalid/synthetic.png"></body>')
    dashboard.write_text(content)
    receipt = verify_dashboard(dashboard, _sha256(dashboard), Path(shutil.which("chromium")).resolve(), tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["error_codes"] in (["browser_layout_mismatch"], ["browser_dom_mismatch"])
    assert receipt["evidence"]["browser_disconnected"] is True
    assert receipt["evidence"]["profile_removed"] is True
    assert not list(tmp_path.glob("dashboard-browser-*"))


@browser_available
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_interrupted_browser_measurement_still_closes_owned_browser_and_profile(tmp_path, monkeypatch, interruption):
    from scripts import verify_windows_candidate_dashboard as verifier

    browsers = []
    primary = interruption("synthetic")

    def interrupted(_context, browser, _dashboard, _receipt):
        browsers.append(browser)
        raise primary

    monkeypatch.setattr(verifier, "_observe_pages", interrupted)
    dashboard = _write_synthetic_dashboard(tmp_path / "dashboard.html")
    with pytest.raises(interruption) as caught:
        verify_dashboard(dashboard, _sha256(dashboard), Path(shutil.which("chromium")).resolve(), tmp_path)
    assert caught.value is primary
    assert len(browsers) == 1 and not browsers[0].is_connected()
    assert not list(tmp_path.glob("dashboard-browser-*"))
