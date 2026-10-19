"""Render only a pinned synthetic dashboard with the standard Playwright host tool.

The verifier loads unchanged file bytes, blocks network access, preserves the
Chromium sandbox, and owns one disposable browser profile. It is build-host
acceptance tooling; it is never imported by ordinary Metroliza startup.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import stat
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PLAYWRIGHT_VERSION = "1.63.0"
MAX_INPUT_BYTES = 1024 * 1024



SCHEMA_VERSION = 1

VIEWPORTS = (
    {"name": "desktop", "width": 1280, "height": 720},
    {"name": "mobile", "width": 390, "height": 844},
)

REQUIRED_SECTIONS = (
    "summary-cards",
    "open-events",
    "severity-timeline",
    "top-signals",
    "sample-aggregates",
    "source-health",
    "signal-charts",
)

MODEL_FACETS = (
    "pinned_input_bytes",
    "browser_dom_execution",
    "responsive_layout",
    "offline_resource_boundary",
    "isolated_profile_cleanup",
)

class DashboardVerificationFailure(ValueError):
    """A fixed, data-free verification failure."""

def _require(condition: bool, code: str) -> None:
    if not condition:
        raise DashboardVerificationFailure(code)

def _layout_expression() -> str:
    required = json.dumps(REQUIRED_SECTIONS)
    return f"""
new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {{
  const required = {required};
  const sections = Array.from(document.querySelectorAll('section[data-section]'));
  const sectionNames = sections.map(node => node.getAttribute('data-section'));
  const tracked = [
    document.querySelector('.dashboard-header'),
    document.querySelector('main'),
    ...sections,
    ...document.querySelectorAll('.summary-card, .signal-panel, .signal-chart, .table-scroll')
  ].filter(Boolean);
  const clipped = tracked.filter(node => {{
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return style.display === 'none' || style.visibility === 'hidden' ||
      rect.width <= 0 || rect.height <= 0 || rect.left < -1 || rect.right > innerWidth + 1;
  }});
  const tableScrolls = Array.from(document.querySelectorAll('.table-scroll'));
  const tableViolations = tableScrolls.filter(node => {{
    const rect = node.getBoundingClientRect();
    const overflow = getComputedStyle(node).overflowX;
    return rect.left < -1 || rect.right > innerWidth + 1 ||
      !['auto', 'scroll'].includes(overflow);
  }});
  const linked = Array.from(document.querySelectorAll('[src], [href]'));
  const external = linked.filter(node => {{
    const raw = node.getAttribute('src') || node.getAttribute('href') || '';
    if (!raw || raw.startsWith('#')) return false;
    try {{
      return !['file:', 'data:'].includes(new URL(raw, document.baseURI).protocol);
    }} catch (_) {{
      return true;
    }}
  }});
  const rootWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  resolve({{
    ready_state: document.readyState,
    js_evaluated: true,
    viewport_width: innerWidth,
    viewport_height: innerHeight,
    required_sections_match: JSON.stringify(sectionNames) === JSON.stringify(required),
    section_count: sections.length,
    summary_card_count: document.querySelectorAll('.summary-card').length,
    signal_panel_count: document.querySelectorAll('.signal-panel').length,
    signal_chart_count: document.querySelectorAll('svg.signal-chart').length,
    sample_point_count: document.querySelectorAll('.sample-point').length,
    table_scroll_count: tableScrolls.length,
    table_scroll_violation_count: tableViolations.length,
    global_overflow_px: Math.max(0, rootWidth - innerWidth),
    clipped_element_count: clipped.length,
    external_reference_count: external.length,
    resource_entry_count: performance.getEntriesByType('resource').length,
    inline_script_count: document.scripts.length,
    main_present: document.querySelector('main#dashboard-content') !== null,
    heading_present: document.querySelector('h1') !== null
  }});
}})))
""".strip()

def _viewport_observation(page, dashboard: Path, viewport: dict[str, Any]) -> dict[str, Any]:
    page.set_viewport_size({key: viewport[key] for key in ("width", "height")})
    page.goto(dashboard.as_uri(), wait_until="load", timeout=15000)
    value = page.evaluate(_layout_expression())
    _require(type(value) is dict, "browser_dom_mismatch")
    return _validate_viewport(value, viewport)


def _validate_viewport(value: dict, viewport: dict) -> dict:
    expected_keys = {
        "ready_state", "js_evaluated", "viewport_width", "viewport_height",
        "required_sections_match", "section_count", "summary_card_count",
        "signal_panel_count", "signal_chart_count", "sample_point_count",
        "table_scroll_count", "table_scroll_violation_count", "global_overflow_px",
        "clipped_element_count", "external_reference_count", "resource_entry_count",
        "inline_script_count", "main_present", "heading_present",
    }
    _require(set(value) == expected_keys, "browser_dom_mismatch")
    boolean_fields = {"js_evaluated", "required_sections_match", "main_present", "heading_present"}
    _require(all(type(value[key]) is bool for key in boolean_fields)
             and all(type(value[key]) is int for key in expected_keys - boolean_fields - {"ready_state"}),
             "browser_dom_mismatch")
    dom_expected = {
        "ready_state": "complete",
        "js_evaluated": True,
        "viewport_width": viewport["width"],
        "viewport_height": viewport["height"],
        "required_sections_match": True,
        "section_count": len(REQUIRED_SECTIONS),
        "signal_panel_count": 1,
        "signal_chart_count": 1,
        "sample_point_count": 2,
        "external_reference_count": 0,
        "resource_entry_count": 0,
        "inline_script_count": 0,
        "main_present": True,
        "heading_present": True,
    }
    _require(
        all(value.get(name) == expected for name, expected in dom_expected.items())
        and isinstance(value.get("summary_card_count"), int)
        and value["summary_card_count"] >= 5,
        "browser_dom_mismatch",
    )
    _require(
        value.get("table_scroll_count", 0) >= 1
        and value.get("table_scroll_violation_count") == 0
        and value.get("global_overflow_px") == 0
        and value.get("clipped_element_count") == 0,
        "browser_layout_mismatch",
    )
    return {"name": viewport["name"], **value}


def _input_bytes(path: Path) -> bytes:
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
             and not getattr(info, "st_file_attributes", 0) & 0x400, "input_invalid")
    _require(0 < info.st_size <= MAX_INPUT_BYTES, "input_size_invalid")
    with path.open("rb") as stream:
        content = stream.read(MAX_INPUT_BYTES + 1)
    _require(len(content) == info.st_size, "input_changed")
    return content


def _plain_directory(path: Path) -> None:
    _require(path.is_absolute(), "scratch_invalid")
    for component in (path, *path.parents):
        info = component.lstat()
        _require(stat.S_ISDIR(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & 0x400, "scratch_invalid")


def _validate_inputs(dashboard: Path, expected_sha256: str, browser: Path, scratch: Path) -> bytes:
    _plain_directory(scratch)
    _require(browser.is_absolute() and browser.is_file() and not browser.is_symlink(),
             "browser_executable_invalid")
    _require(dashboard.is_absolute(), "input_invalid")
    _plain_directory(dashboard.parent)
    _require(type(expected_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
             "input_hash_invalid")
    content = _input_bytes(dashboard)
    _require(hashlib.sha256(content).hexdigest() == expected_sha256, "input_hash_mismatch")
    return content


def _render(dashboard: Path, browser_path: Path, profile: Path, receipt: dict) -> None:
    check_host_runtime(browser_path)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile, executable_path=browser_path, headless=True, chromium_sandbox=True,
            offline=True, service_workers="block", accept_downloads=False, timeout=15000,
        )
        browser = context.browser
        _require(browser is not None, "browser_identity_invalid")
        try:
            _observe_pages(context, browser, dashboard, receipt)
        finally:
            context.close()
            _require(not browser.is_connected(), "browser_close_failed")
            receipt["evidence"]["browser_disconnected"] = True


def check_host_runtime(browser: Path) -> None:
    _require(browser.is_absolute() and browser.is_file() and not browser.is_symlink(),
             "browser_executable_invalid")
    try:
        version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        raise DashboardVerificationFailure("browser_driver_missing") from None
    _require(version == PLAYWRIGHT_VERSION, "browser_driver_version_mismatch")


def _observe_pages(context, browser, dashboard: Path, receipt: dict) -> None:
    evidence = receipt["evidence"]
    evidence["browser_version"] = browser.version
    evidence["automation_driver"] = "playwright-" + PLAYWRIGHT_VERSION
    requests = {"count": 0, "schemes": set(), "unexpected": False}
    errors = []
    expected_url = dashboard.as_uri()

    def requested(request):
        requests["count"] += 1
        requests["schemes"].add(urlsplit(request.url).scheme)
        if request.url != expected_url or requests["count"] > len(VIEWPORTS):
            requests["unexpected"] = True

    def routed(route):
        # Offline mode is also set before navigation. Deny every resource other
        # than the one byte-pinned document, including other local files.
        if route.request.url != expected_url:
            requests["unexpected"] = True
            route.abort()
        else:
            route.continue_()

    context.route("**/*", routed)
    context.on("request", requested)
    page = context.new_page()
    page.on("pageerror", lambda _error: errors.append(True) if not errors else None)
    page.on("crash", lambda: errors.append(True) if not errors else None)
    page.set_default_timeout(15000)
    evidence["viewports"] = [_viewport_observation(page, dashboard, viewport) for viewport in VIEWPORTS]
    _require(not errors, "browser_dom_exception")
    _require(browser.is_connected(), "browser_close_failed")
    _require(requests["count"] == len(VIEWPORTS) and requests["schemes"] == {"file"}
             and not requests["unexpected"], "offline_boundary_failed")
    evidence["network_request_count"] = requests["count"]
    evidence["network_request_schemes"] = sorted(requests["schemes"])
    receipt["facets"].update(dict.fromkeys(
        ("browser_dom_execution", "responsive_layout", "offline_resource_boundary"), "passed"
    ))


def verify_dashboard(dashboard_path: str | Path, expected_sha256: str,
                     browser_executable: str | Path, scratch_directory: str | Path) -> dict[str, Any]:
    receipt = {
        "schema_version": SCHEMA_VERSION, "status": "failed",
        "facets": dict.fromkeys(MODEL_FACETS, "not_run"), "error_codes": [],
        "evidence": {
            "input_sha256": None, "input_size": None, "browser_version": None,
            "automation_driver": None, "host_platform": sys.platform, "viewports": [],
            "network_request_count": None, "network_request_schemes": [],
            "browser_disconnected": False, "profile_removed": False, "source_unchanged": False,
        },
    }
    dashboard, browser, scratch = Path(dashboard_path), Path(browser_executable), Path(scratch_directory)
    try:
        content = _validate_inputs(dashboard, expected_sha256, browser, scratch)
        receipt["evidence"].update(input_sha256=expected_sha256, input_size=len(content))
        receipt["facets"]["pinned_input_bytes"] = "passed"
        profile = None
        try:
            with tempfile.TemporaryDirectory(prefix="dashboard-browser-", dir=scratch) as temporary:
                profile = Path(temporary)
                _render(dashboard, browser, profile, receipt)
        finally:
            if profile is not None:
                receipt["evidence"]["profile_removed"] = not profile.exists()
        _require(receipt["evidence"]["profile_removed"], "profile_cleanup_failed")
        _require(_input_bytes(dashboard) == content, "input_changed")
        receipt["evidence"]["source_unchanged"] = True
        receipt["facets"]["isolated_profile_cleanup"] = "passed"
        receipt["status"] = "passed"
    except DashboardVerificationFailure as error:
        receipt["error_codes"].append(str(error))
    except Exception:
        receipt["error_codes"].append("browser_tool_failed")
    return receipt


def validate_receipt(value: object, expected_sha256: str, *, require_windows: bool = True) -> dict:
    _require(type(value) is dict and set(value) == {
        "schema_version", "status", "facets", "error_codes", "evidence"
    }, "browser_receipt_invalid")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
             and value["status"] == "passed" and value["error_codes"] == []
             and value["facets"] == dict.fromkeys(MODEL_FACETS, "passed"), "browser_receipt_incomplete")
    evidence = value["evidence"]
    _require(type(evidence) is dict and set(evidence) == {
        "input_sha256", "input_size", "browser_version", "automation_driver", "host_platform",
        "viewports", "network_request_count", "network_request_schemes", "browser_disconnected",
        "profile_removed", "source_unchanged",
    }, "browser_receipt_invalid")
    _require(evidence["input_sha256"] == expected_sha256
             and type(evidence["input_size"]) is int and 0 < evidence["input_size"] <= MAX_INPUT_BYTES
             and evidence["automation_driver"] == "playwright-" + PLAYWRIGHT_VERSION
             and type(evidence["browser_version"]) is str
             and re.fullmatch(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,6}\.[0-9]{1,6}", evidence["browser_version"]) is not None,
             "browser_receipt_identity_mismatch")
    _require(not require_windows or evidence["host_platform"] == "win32", "browser_windows_proof_missing")
    _require(evidence["browser_disconnected"] is True and evidence["profile_removed"] is True
             and evidence["source_unchanged"] is True
             and type(evidence["network_request_count"]) is int
             and evidence["network_request_count"] == len(VIEWPORTS)
             and evidence["network_request_schemes"] == ["file"], "browser_receipt_incomplete")
    observations = evidence["viewports"]
    _require(type(observations) is list and len(observations) == len(VIEWPORTS), "browser_dom_mismatch")
    for observed, viewport in zip(observations, VIEWPORTS, strict=True):
        _require(type(observed) is dict and observed.get("name") == viewport["name"], "browser_dom_mismatch")
        _validate_viewport({key: item for key, item in observed.items() if key != "name"}, viewport)
    return value


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    _require(path.is_absolute() and not path.exists(), "receipt_path_invalid")
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    try:
        with staged.open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dashboard", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--browser", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = verify_dashboard(
        args.dashboard,
        args.expected_sha256,
        args.browser,
        args.scratch,
    )
    try:
        _write_receipt(args.receipt, receipt)
    except (DashboardVerificationFailure, OSError):
        return 2
    return 0 if receipt["status"] == "passed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
