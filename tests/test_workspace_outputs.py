"""Saved workspace relinking and bundled outputs from private run history."""

from hashlib import sha256
import json
import shutil
from zipfile import ZipFile

import pytest

from metroliza.app.analysis_history import (
    analysis_is_stale, bundle_analysis, capture_source_stamp, recent_analyses,
    record_analysis, result_still_matches,
)
from metroliza.app.workspace_file import read_workspace, write_workspace
from metroliza.ui.workspace_context import WorkspaceSnapshot


def test_saved_workspace_matches_unchanged_copy_and_refuses_same_name_replacement(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "sample.pdf").write_bytes(b"REPORT ORIGINAL")
    database = tmp_path / "source.sqlite"
    database.write_bytes(b"DATABASE")
    location = tmp_path / "report.metroliza-workspace"
    write_workspace(location, WorkspaceSnapshot(1, str(source), str(database)), "reports")
    saved = read_workspace(location)

    moved_directory = shutil.copytree(source, tmp_path / "elsewhere")
    moved_database = tmp_path / "copy.sqlite"
    shutil.copyfile(database, moved_database)
    assert saved.page == "reports"
    assert saved.source.matches(moved_directory)
    assert saved.database.matches(moved_database)

    (moved_directory / "sample.pdf").write_bytes(b"REPORT MODIFIED")
    moved_database.write_bytes(b"DIFFERENT")
    assert not saved.source.matches(moved_directory)
    assert not saved.database.matches(moved_database)


def test_history_keeps_real_settings_and_bundle_resources_and_keeps_source_private(tmp_path):
    source = tmp_path / "private.sqlite"
    source.write_bytes(b"PRIVATE SOURCE DATA")
    dashboard = tmp_path / "Overview.html"
    dashboard.write_text('<script src="Overview-assets/main.js"></script>', encoding="utf-8")
    assets = tmp_path / "Overview-assets"
    assets.mkdir()
    script = assets / "main.js"
    script.write_text("const result = 123;", encoding="utf-8")
    workbook = tmp_path / "Overview.xlsx"
    workbook.write_bytes(b"SYNTHETIC WORKBOOK")
    private = tmp_path / "private-history"
    record_analysis({
        "kind": "reports", "artifacts": [workbook, dashboard, assets], "source": source,
        "settings": {"Reference": "Ref ABC"},
    }, directory=private)

    (private / "bad.json").write_text("[]", encoding="utf-8")
    saved, = recent_analyses(directory=private)
    assert saved["settings"] == {"Reference": "Ref ABC"}
    assert not analysis_is_stale(saved)
    package = tmp_path / "published.zip"
    bundle_analysis(saved, package)
    with ZipFile(package) as archive:
        expected = {"Overview.html", "Overview.xlsx", "Overview-assets/main.js"}
        assert set(archive.namelist()) == expected | {"metroliza-results.json"}
        manifest = json.loads(archive.read("metroliza-results.json"))["sha256"]
        assert manifest == {name: sha256(archive.read(name)).hexdigest() for name in expected}
        assert "Ref ABC" not in manifest
    source.write_bytes(b"UPDATED SOURCE")
    assert analysis_is_stale(saved)

    script.write_text("const result = 4567;", encoding="utf-8")
    changed_package = tmp_path / "changed.zip"
    with pytest.raises(ValueError, match="changed after export"):
        bundle_analysis(saved, changed_package)
    assert not changed_package.exists()
    assert result_still_matches(saved, workbook)
    workbook.write_bytes(b"A DIFFERENT WORKBOOK")
    assert not result_still_matches(saved, workbook)


def test_history_rejects_a_dashboard_missing_its_generated_script(tmp_path):
    dashboard = tmp_path / "report.html"
    dashboard.write_text('<script src="assets/plotly.js"></script>', encoding="utf-8")
    saved = record_analysis({"kind": "csv", "artifacts": [dashboard]}, directory=tmp_path / "history")
    package = tmp_path / "package.zip"
    with pytest.raises(ValueError, match="resource is missing"):
        bundle_analysis(saved, package)
    assert not package.exists()


def test_history_marks_a_source_that_changed_during_the_run(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text("code\n001\n", encoding="utf-8")
    source_stamp = capture_source_stamp(source)
    source.write_text("code\n002,updated\n", encoding="utf-8")
    output = tmp_path / "analysis.xlsx"
    output.touch()
    saved = record_analysis({"kind": "csv", "artifacts": [output], "source": source,
                             "source_stamp": source_stamp}, directory=tmp_path / "history")
    assert saved["source_changed_during_run"] is True
    assert analysis_is_stale(saved)


def test_report_folder_history_detects_an_in_place_same_stat_change(tmp_path, monkeypatch):
    import os

    from metroliza.parsing import report_folder_revision as revision
    from metroliza.parsing.preflight import ParseFilePreflight, ParsePreflightStatus

    monkeypatch.setattr(revision, "supported_report_file_extensions", lambda: {".pdf", ".xlsx"})
    source = tmp_path / "input"
    nested = source / "nested"
    nested.mkdir(parents=True)
    report = nested / "private-name.pdf"
    report.write_bytes(b"original")
    scan = ParseFilePreflight(
        "nested/private-name.pdf", str(report), ParsePreflightStatus.READY, "pdf",
        "sha256:" + sha256(b"original").hexdigest(),
    )
    output = source / "published.xlsx"
    expected = revision.revision_from_preflight((scan,), (output,))
    output.write_bytes(b"OUR OWN OUTPUT")
    history = tmp_path / "history"
    record_analysis({"kind": "recipe", "artifacts": [output], "source": source,
                     "report_folder_revision": expected}, directory=history)

    saved, = recent_analyses(directory=history)
    assert len(saved["report_folder_revision"]) == 64
    assert "private-name.pdf" not in next(history.glob("*.json")).read_text()
    assert analysis_is_stale(saved) is False
    (nested / "ignored.txt").touch()
    assert analysis_is_stale(saved) is False
    (nested / "new.pdf").write_bytes(b"new")
    assert analysis_is_stale(saved) is True
    (nested / "new.pdf").unlink()
    assert analysis_is_stale(saved) is False

    old_stat = report.stat()
    report.write_bytes(b"modified")
    os.utime(report, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert report.stat().st_size == old_stat.st_size
    assert report.stat().st_mtime_ns == old_stat.st_mtime_ns
    assert analysis_is_stale(saved) is True
    report.unlink()
    assert analysis_is_stale(saved) is True


def test_report_folder_history_does_not_guess_when_evidence_is_unavailable(tmp_path, monkeypatch):
    from metroliza.parsing import report_folder_revision as revision
    from metroliza.parsing.preflight import ParseFilePreflight, ParsePreflightStatus

    source = tmp_path / "input"
    source.mkdir()
    overlap = source / "report.xlsx"
    overlap.write_bytes(b"report")
    report = ParseFilePreflight(
        overlap.name, str(overlap), ParsePreflightStatus.DUPLICATE, "xlsx",
        "sha256:" + sha256(b"report").hexdigest(),
    )
    assert revision.revision_from_preflight((report,), (overlap,)) is None
    assert analysis_is_stale({"kind": "recipe", "source": str(source),
                              "source_stamp": capture_source_stamp(source)}) is None
    assert analysis_is_stale({"kind": "recipe", "source": str(source),
                              "report_folder_revision": None}) is None
    saved = {"kind": "recipe", "source": str(source), "files": [],
             "report_folder_revision": revision.revision_from_preflight((report,))}
    assert analysis_is_stale(saved, cancelled=lambda: True) is None
    monkeypatch.setattr(revision, "_MAX_ENTRIES", 1)
    (source / "ignored.txt").touch()
    assert analysis_is_stale(saved) is None


def test_history_discards_late_folder_check_after_selection_changes(
    tmp_path, monkeypatch, qapplication_session,
):
    from threading import Event
    from time import monotonic

    from PyQt6.QtCore import QThread
    from PyQt6.QtTest import QTest

    from metroliza.ui import analysis_history_dialog as ui

    source = tmp_path / "source"
    source.mkdir()
    one = tmp_path / "first.xlsx"
    two = tmp_path / "second.xlsx"
    one.touch()
    two.touch()
    history = tmp_path / "history"
    folder_run = record_analysis({"kind": "recipe", "artifacts": [one], "source": source,
                                  "report_folder_revision": "a" * 64}, directory=history)
    csv_run = record_analysis({"kind": "csv", "artifacts": [two]}, directory=history)
    monkeypatch.setattr(ui, "recent_analyses", lambda: iter((folder_run, csv_run)))
    entered, release = Event(), Event()
    on_gui = []

    def check_folder(_run, _generation):
        on_gui.append(QThread.currentThread() is qapplication_session.thread())
        entered.set()
        release.wait(3)
        return True

    monkeypatch.setattr(ui, "_check_report_source", check_folder)
    dialog = ui.AnalysisHistoryDialog(None)
    try:
        assert entered.wait(2)
        assert on_gui == [False]
        dialog.runs.setCurrentRow(1)
        release.set()
        deadline = monotonic() + 3
        while dialog._source_task is not None and monotonic() < deadline:
            QTest.qWait(10)
        assert dialog._source_task is None
        assert "second.xlsx" in dialog.result.summary.text()
        assert "Source changed" not in dialog.result.summary.text()
    finally:
        release.set()
        dialog.close()
