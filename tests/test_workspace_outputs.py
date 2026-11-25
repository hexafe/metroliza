"""Saved workspace relinking and bundled outputs from private run history."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import shutil
from zipfile import ZipFile

import pytest

from metroliza.app.analysis_history import (
    AnalysisListing, AnalysisReceiptReference, analysis_is_stale, bundle_analysis, capture_source_stamp,
    load_recent_analyses, recent_analyses,
    record_analysis, remove_analysis, result_still_matches,
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
    dashboard.write_text('<script src="Overview-assets/plotly-2.27.0.min.js"></script>', encoding="utf-8")
    assets = tmp_path / "Overview-assets"
    assets.mkdir()
    script = assets / "plotly-2.27.0.min.js"
    script.write_text("const result = 123;", encoding="utf-8")
    notice = assets / "plotly.min.js.LICENSE.txt"
    notice.write_text("SYNTHETIC COMPANION NOTICE", encoding="utf-8")
    (assets / "private.txt").write_text("UNRELATED TEXT", encoding="utf-8")
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
        expected = {"Overview.html", "Overview.xlsx",
                    f"Overview-assets/{script.name}", f"Overview-assets/{notice.name}"}
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
    monkeypatch.setattr(ui, "load_recent_analyses", lambda **_kwargs: AnalysisListing((folder_run, csv_run)))
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
        _finish_history_task(dialog._listing_task)
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



def _finish_history_task(task):
    from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

    assert task is not None
    loop, watchdog = QEventLoop(), QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    task.finished.connect(loop.quit)
    if not task.isFinished():
        watchdog.start(3000)
        loop.exec()
        watchdog.stop()
    QCoreApplication.processEvents()


def test_recent_history_limits_large_malformed_ledger_without_pruning(tmp_path, monkeypatch):
    from metroliza.app import analysis_history

    root = tmp_path / "large-history"
    root.mkdir()
    folder = tmp_path / "retained.xlsx"
    folder.touch()
    valid = record_analysis({"kind": "recipe", "artifacts": [folder]}, directory=root)
    for index in range(180):
        receipt = {**valid, "settings": {"order": index}}
        (root / f"20280101T000000{index:06}Z-synthetic.json").write_text(json.dumps(receipt))
    corrupt = root / "20290101T000000000000Z-corrupt.json"
    corrupt.write_text("[" * 2000)
    names = sorted(path.name for path in root.iterdir())

    full = load_recent_analyses(directory=root)
    assert full.partial is False
    assert [row["settings"]["order"] for row in full.receipts] == list(range(179, 80, -1))

    monkeypatch.setattr(analysis_history, "_MAX_LIST_ENTRIES", 10)
    limited = load_recent_analyses(directory=root)
    assert limited.partial is True
    assert len(limited.receipts) <= 10

    monkeypatch.setattr(analysis_history, "_MAX_LIST_ENTRIES", 1000)
    monkeypatch.setattr(analysis_history, "_MAX_LIST_BYTES", 10)
    assert load_recent_analyses(directory=root) == AnalysisListing((), partial=True)
    assert load_recent_analyses(directory=root, cancelled=lambda: True) == AnalysisListing((), partial=True)
    assert sorted(path.name for path in root.iterdir()) == names
    assert corrupt.read_text() == "[" * 2000
    assert folder.exists()


def test_history_date_search_finds_receipts_outside_recent_limit(tmp_path, monkeypatch):
    from metroliza.app import analysis_history

    root = tmp_path / "history"
    output = tmp_path / "analysis.xlsx"
    output.touch()
    newest = record_analysis({"kind": "csv", "artifacts": [output]}, directory=root)
    day = date(2024, 1, 2)
    before = datetime.combine(day, time.min).astimezone(timezone.utc) - timedelta(microseconds=1)
    first = before + timedelta(microseconds=1)
    after = datetime.combine(day + timedelta(days=1), time.min).astimezone(timezone.utc)
    for order, timestamp in enumerate((before, first, after)):
        receipt = {**newest, "at": timestamp.isoformat(), "settings": {"order": order}}
        name = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{order:032x}.json"
        (root / name).write_text(json.dumps(receipt), encoding="utf-8")

    monkeypatch.setattr(analysis_history, "_RECENT_LIMIT", 1)
    assert [row["at"] for row in load_recent_analyses(directory=root).receipts] == [newest["at"]]
    listing = load_recent_analyses(directory=root, day=day)
    assert [row["settings"]["order"] for row in listing.receipts] == [1]
    assert len(listing.references) == 1
    assert listing.partial is False

    last = after - timedelta(microseconds=1)
    name = f"{last.strftime('%Y%m%dT%H%M%S%fZ')}-{'4' * 32}.json"
    (root / name).write_text(json.dumps({**newest, "at": last.isoformat()}), encoding="utf-8")
    assert load_recent_analyses(directory=root, day=day).partial is True
    assert load_recent_analyses(directory=root, day=day, cancelled=lambda: True).partial is True


def test_history_removal_is_bound_to_one_confirmed_receipt(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "analysis.xlsx"
    source.write_bytes(b"source")
    output.write_bytes(b"result")
    root = tmp_path / "history"
    record_analysis({"kind": "csv", "source": source, "artifacts": [output]}, directory=root)
    record_analysis({"kind": "recipe", "source": source, "artifacts": [output]}, directory=root)
    listing = load_recent_analyses(directory=root)
    recipe, csv = (
        next(ref for run, ref in zip(listing.receipts, listing.references) if run["kind"] == kind)
        for kind in ("recipe", "csv")
    )
    recipe_file = root / recipe.name
    content = recipe_file.read_bytes()
    recipe_file.write_bytes(content + b" ")
    with pytest.raises(ValueError, match="entry changed"):
        remove_analysis(recipe, directory=root)
    assert recipe_file.read_bytes() == content + b" "
    with pytest.raises(ValueError, match="cannot be removed"):
        remove_analysis(AnalysisReceiptReference("../" + recipe.name, recipe.sha256), directory=root)

    assert remove_analysis(csv, directory=root) is True
    assert remove_analysis(csv, directory=root) is False
    assert sorted(path.name for path in root.iterdir()) == [recipe.name]
    assert source.read_bytes() == b"source"
    assert output.read_bytes() == b"result"


def test_history_dialog_filters_and_confirms_single_receipt_removal(
    tmp_path, monkeypatch, qapplication_session,
):
    from PyQt6.QtCore import QDate, QSignalBlocker, QThread
    from PyQt6.QtWidgets import QMessageBox

    from metroliza.app import analysis_history
    from metroliza.ui import analysis_history_dialog as ui

    root = tmp_path / "history"
    old, new = tmp_path / "earlier.xlsx", tmp_path / "newest.xlsx"
    old.touch()
    new.touch()
    earlier = record_analysis({"kind": "csv", "artifacts": [old]}, directory=root)
    timestamp = datetime(2024, 3, 1, 12).astimezone(timezone.utc)
    earlier_name = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{'1' * 32}.json"
    previous, = root.glob("*.json")
    earlier_receipt = root / earlier_name
    previous.rename(earlier_receipt)
    earlier_receipt.write_text(json.dumps({**earlier, "at": timestamp.isoformat()}), encoding="utf-8")
    record_analysis({"kind": "csv", "artifacts": [new]}, directory=root)
    monkeypatch.setattr(analysis_history, "_history_directory", lambda: root)
    answers = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: next(answers))
    on_gui = []

    def observe_remove(reference):
        on_gui.append(QThread.currentThread() is qapplication_session.thread())
        return remove_analysis(reference)

    monkeypatch.setattr(ui, "remove_analysis", observe_remove)
    dialog = ui.AnalysisHistoryDialog(None)
    try:
        _finish_history_task(dialog._listing_task)
        assert dialog.runs.count() == 2
        with QSignalBlocker(dialog.history_date):
            dialog.history_date.setDate(QDate(2024, 3, 1))
        dialog.date_filter.setChecked(True)
        _finish_history_task(dialog._listing_task)
        assert dialog.runs.count() == 1
        assert "earlier.xlsx" in dialog.runs.currentItem().text()

        dialog.remove_button.click()
        assert dialog._task is None and earlier_receipt.exists()
        dialog.remove_button.click()
        _finish_history_task(dialog._task)
        if dialog._listing_task is not None:
            _finish_history_task(dialog._listing_task)
        assert on_gui == [False]
        assert dialog.runs.count() == 0
        assert "No saved analyses for this date" in dialog.listing_notice.text()
        assert "History entry removed." in dialog.status.toPlainText()
        assert not earlier_receipt.exists()
        assert len(tuple(root.glob("*.json"))) == 1
        assert old.exists() and new.exists()
    finally:
        dialog.close()


def test_history_refresh_rejects_previous_listing_and_displays_partial_state(
    tmp_path, monkeypatch, qapplication_session,
):
    from threading import Event

    from PyQt6.QtCore import QThread

    from metroliza.ui import analysis_history_dialog as ui

    prior = tmp_path / "previous.xlsx"
    current = tmp_path / "current.xlsx"
    prior.touch()
    current.touch()
    history = tmp_path / "history"
    first = record_analysis({"kind": "recipe", "artifacts": [prior]}, directory=history)
    second = record_analysis({"kind": "csv", "artifacts": [current]}, directory=history)
    entered, release = Event(), Event()
    called = []
    def load(*, cancelled, day):
        called.append(QThread.currentThread() is qapplication_session.thread())
        assert day is None
        if len(called) == 1:
            entered.set()
            release.wait(3)
            assert cancelled()
            return AnalysisListing((first,))
        return AnalysisListing((second,), partial=True)

    monkeypatch.setattr(ui, "load_recent_analyses", load)
    dialog = ui.AnalysisHistoryDialog(None)
    observed = []
    original_set_result = dialog.result.set_result

    def observe(_outcome, paths, **kwargs):
        observed.extend(paths)
        return original_set_result(_outcome, paths, **kwargs)

    monkeypatch.setattr(dialog.result, "set_result", observe)
    try:
        assert entered.wait(2)
        assert called == [False]
        initial = dialog._listing_task
        dialog.reload()
        assert initial.isInterruptionRequested()
        assert "Reading" in dialog.listing_notice.text()
        release.set()
        _finish_history_task(initial)
        if dialog._listing_task is not None:
            _finish_history_task(dialog._listing_task)
        assert called == [False, False]
        assert observed == [str(current)]
        assert dialog.runs.count() == 1
        assert "Partial history list" in dialog.listing_notice.text()
    finally:
        release.set()
        dialog.close()
