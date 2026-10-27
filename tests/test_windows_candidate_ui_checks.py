"""Synthetic UI/dashboard source checks; native display evidence runs on Windows."""

from __future__ import annotations

import hashlib

import pytest
from PyQt6.QtWidgets import QApplication

from metroliza.app.windows_candidate_ui_checks import run_ui_checks


@pytest.fixture(scope="session")
def application():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("name", ("plain", "owned # próba"))
def test_real_private_dashboard_from_synthetic_sqlite(application, tmp_path, name):
    scratch = tmp_path / name
    scratch.mkdir()

    result = run_ui_checks(scratch)

    assert result["status"] == "partial", result
    assert result["error_codes"] == []
    assert result["facets"] == {
        "private_dashboard_generation": "passed",
        "offline_html_source": "passed",
        "industrial_geometry": "not_assessed",
        "browser_rendering": "not_assessed",
    }
    evidence = result["evidence"]
    assert evidence["sample_count"] == 2
    assert evidence["private_directory_removed_after_close"] is True
    assert evidence["browser_rendered"] is False
    assert evidence["screen"]["qpa"] == application.platformName()
    html_file = scratch / evidence["relative_artifact_dir"] / evidence["retained_html"]
    assert html_file.is_file()
    assert hashlib.sha256(html_file.read_bytes()).hexdigest() == evidence["dashboard_sha256"]
    assert 'data-section="signal-charts"' in html_file.read_text(encoding="utf-8")


def test_invalid_scratch_is_closed_failure(application, tmp_path):
    result = run_ui_checks(tmp_path / "missing")

    assert result["status"] == "failed"
    assert result["error_codes"] == ["scratch_invalid"]
    assert result["facets"]["private_dashboard_generation"] == "not_run"
    assert result["evidence"]["browser_rendered"] is False


class _ClosingWindow:
    def __init__(self, closed, visible):
        self.closed, self.visible, self.deleted = closed, visible, False

    def close(self):
        return self.closed

    def isVisible(self):
        return self.visible

    def deleteLater(self):
        self.deleted = True


@pytest.mark.parametrize("closed,visible", [(False, False), (True, True)])
def test_close_refusal_or_visible_owner_is_retained(application, closed, visible, monkeypatch):
    from metroliza.app import windows_candidate_ui_checks as ui
    retained = []
    monkeypatch.setattr(ui, "_RETAINED_WINDOWS", retained)
    window = _ClosingWindow(closed, visible)
    assert ui._close_window_safely(application, window) == "window_close_refused"
    assert retained == [window]
    assert not window.deleted


def test_dialog_cleanup_preserves_refusing_owner_and_still_closes_siblings(application, monkeypatch):
    from metroliza.app import windows_candidate_ui_checks as ui
    retained = []
    monkeypatch.setattr(ui, "_RETAINED_WINDOWS", retained)
    refused, sibling = _ClosingWindow(False, False), _ClosingWindow(True, False)
    assert not ui._close_dialogs_safely(application, [refused, sibling])
    assert retained == [refused]
    assert not refused.deleted
    assert sibling.deleted
