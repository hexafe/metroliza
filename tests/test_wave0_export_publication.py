"""#1159: no workbook or HTML output is replaced without operation-specific consent."""

from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest


def _export_thread(target, *, cancel=False, race=False):
    def pipeline(writer):
        sheet = writer.book.add_worksheet("Measurements")
        sheet.write(0, 0, "NOK")
        sheet.write(1, 0, 12.5)
        if race:
            target.write_bytes(b"created by another operation")
        return not cancel

    return SimpleNamespace(
        excel_file=str(target), run_export_pipeline=pipeline,
        begin_workbook_close=lambda: None, complete_workbook_close=lambda _: None,
    )


def test_export_existing_target_without_consent_keeps_old_bytes(tmp_path):
    from metroliza.exporting.export_backends import ExcelExportBackend

    target = tmp_path / "export.xlsx"
    target.write_bytes(b"last complete workbook")
    with pytest.raises(FileExistsError, match="Save a copy"):
        ExcelExportBackend().run(_export_thread(target))
    assert target.read_bytes() == b"last complete workbook"
    assert set(tmp_path.iterdir()) == {target}


def test_export_race_created_after_check_does_not_replace_target(tmp_path):
    from metroliza.exporting.export_backends import ExcelExportBackend

    target = tmp_path / "export.xlsx"
    with pytest.raises(FileExistsError, match="Save a copy"):
        ExcelExportBackend().run(_export_thread(target, race=True))
    assert target.read_bytes() == b"created by another operation"
    assert set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize("locked", [False, True])
def test_export_replace_requires_consent_and_locked_file_keeps_old_result(tmp_path, monkeypatch, locked):
    from metroliza.exporting.export_backends import ExcelExportBackend
    from metroliza.exporting.output_publication import OutputConsent
    import os

    target = tmp_path / "export.xlsx"
    target.write_bytes(b"old workbook")
    thread = _export_thread(target)
    thread.replace_outputs = (OutputConsent.for_path(target),)
    if locked:
        def locked_replace(*_args):
            raise PermissionError("Excel lock")

        monkeypatch.setattr(os, "replace", locked_replace)
        with pytest.raises(PermissionError, match="Close it in Excel"):
            ExcelExportBackend().run(thread)
        assert target.read_bytes() == b"old workbook"
    else:
        assert ExcelExportBackend().run(thread)
        with zipfile.ZipFile(target) as package:
            assert b"12.5" in package.read("xl/worksheets/sheet1.xml")
            assert b"NOK" in package.read("xl/sharedStrings.xml")
    assert set(tmp_path.iterdir()) == {target}


def test_export_cancel_keeps_old_target(tmp_path):
    from metroliza.exporting.export_backends import ExcelExportBackend

    target = tmp_path / "export.xlsx"
    target.write_bytes(b"old workbook")
    assert not ExcelExportBackend().run(_export_thread(target, cancel=True))
    assert target.read_bytes() == b"old workbook"
    assert set(tmp_path.iterdir()) == {target}


def _request(database, target, *, dashboard=False):
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest

    return ExportRequest(AppPaths(database, str(target)), ExportOptions(generate_html_dashboard=dashboard))


def _dialog_host(choice):
    return SimpleNamespace(
        _choose_output_collision=lambda *_: choice,
        _set_path_field_value=lambda *_: None, excel_file_text_label=None,
    )


@pytest.mark.parametrize("choice", ["copy", "replace", "cancel"])
def test_export_operation_decision_copy_replace_cancel_and_db_switch(tmp_path, choice):
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "output.xlsx"
    target.write_bytes(b"old")
    host = _dialog_host(choice)
    request = _request("first.sqlite", target)
    result = ExportDialog._confirm_output_publication(host, request)
    if choice == "cancel":
        assert result is None
    elif choice == "copy":
        assert result.paths.excel_file == str(tmp_path / "output (2).xlsx")
        assert not result.replace_outputs
    else:
        assert len(result.replace_outputs) == 1
        prompts = []
        host._choose_output_collision = lambda db, *args: prompts.append(db) or "cancel"
        assert ExportDialog._confirm_output_publication(host, _request("other.DB", target)) is None
        assert prompts == ["other.DB"]
    assert target.read_bytes() == b"old"


def test_collision_prompt_defaults_to_copy_and_shows_database_and_paths(monkeypatch, qapplication_session, tmp_path):
    from PyQt6.QtWidgets import QMessageBox
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "existing.xlsx"
    copy = tmp_path / "existing (2).xlsx"
    seen = []

    def click_default(prompt):
        seen.append((prompt.defaultButton().text(), prompt.text()))
        prompt.defaultButton().click()

    monkeypatch.setattr(QMessageBox, "exec", click_default)
    assert ExportDialog._choose_output_collision(None, "selected.sqlite3", (target,), (target,), copy) == "copy"
    assert seen[0][0] == "Save a copy"
    assert all(value in seen[0][1] for value in ("selected.sqlite3", str(target), str(copy)))


def test_default_copy_publishes_new_workbook_and_keeps_old_bytes(tmp_path):
    from metroliza.ui.export_dialog import ExportDialog
    from metroliza.exporting.export_backends import ExcelExportBackend

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"last complete NOK workbook")
    request = ExportDialog._confirm_output_publication(_dialog_host("copy"), _request("chosen.DB", target))
    copied = Path(request.paths.excel_file)
    assert ExcelExportBackend().run(_export_thread(copied))
    assert copied.exists() and target.read_bytes() == b"last complete NOK workbook"


def test_changed_file_invalidates_replacement_consent(tmp_path):
    from metroliza.exporting.export_backends import ExcelExportBackend
    from metroliza.exporting.output_publication import OutputConsent

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"old")
    thread = _export_thread(target)
    thread.replace_outputs = (OutputConsent.for_path(target),)
    target.write_bytes(b"different file after confirmation")
    with pytest.raises(FileExistsError, match="changed after confirmation"):
        ExcelExportBackend().run(thread)
    assert target.read_bytes() == b"different file after confirmation"


@pytest.mark.parametrize("replace_existing", [False, True])
def test_dashboard_publication_protects_old_html_and_assets(tmp_path, replace_existing):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting.output_publication import OutputConsent, write_dashboard_safely

    target = tmp_path / "out_dashboard.html"
    assets = tmp_path / "out_dashboard_assets"
    target.write_text("old NOK dashboard")
    assets.mkdir()
    old_asset = assets / "old.png"
    old_asset.write_bytes(b"old NOK asset")
    kwargs = dict(output_path=target, assets_dir=assets, sections=[], source_label="NOK")
    if replace_existing:
        result = write_dashboard_safely(write_export_html_dashboard, consents=(OutputConsent.for_path(target),), **kwargs)
        assert Path(result["html_dashboard_assets_path"]).is_dir()
        assert target.read_text() != "old NOK dashboard"
    else:
        with pytest.raises(FileExistsError):
            write_dashboard_safely(write_export_html_dashboard, **kwargs)
        assert target.read_text() == "old NOK dashboard"
        assert set(tmp_path.iterdir()) == {target, assets, tmp_path / f".{target.name}.publish.lock"}
    if replace_existing:
        assert not assets.exists()
    else:
        assert old_asset.read_bytes() == b"old NOK asset"


def test_copy_avoids_sidecar_collision_as_well_as_workbook(tmp_path):
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "out.xlsx"
    (tmp_path / "out_dashboard.html").write_text("existing dashboard")
    (tmp_path / "out (2)_dashboard_assets").mkdir()
    request = ExportDialog._confirm_output_publication(_dialog_host("copy"), _request("chosen.db", target, dashboard=True))
    assert request.paths.excel_file == str(tmp_path / "out (3).xlsx")
    assert request.paths.html_dashboard_file == str(tmp_path / "out (3)_dashboard.html")


def test_cancel_during_workbook_close_keeps_old_file(tmp_path, monkeypatch):
    from metroliza.exporting.export_backends import ExcelExportBackend
    from metroliza.exporting.output_publication import OutputConsent

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"old result")
    thread = _export_thread(target)
    thread.replace_outputs = (OutputConsent.for_path(target),)
    thread.complete_workbook_close = lambda _: setattr(thread, "export_canceled", True)
    assert not ExcelExportBackend().run(thread)
    assert target.read_bytes() == b"old result"
    assert set(tmp_path.iterdir()) == {target}


def test_dashboard_cancel_after_render_keeps_old_html_and_cleans_staging(tmp_path):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting.output_publication import OutputPublicationCanceled, OutputConsent, write_dashboard_safely

    target = tmp_path / "dashboard.html"
    target.write_text("last complete NOK dashboard")
    with pytest.raises(OutputPublicationCanceled):
        write_dashboard_safely(
            write_export_html_dashboard, output_path=target,
            assets_dir=tmp_path / "dashboard_assets", sections=[],
            consents=(OutputConsent.for_path(target),), should_cancel=lambda: True,
        )
    assert target.read_text() == "last complete NOK dashboard"
    assert set(tmp_path.iterdir()) == {target}


def test_collision_consent_does_not_cover_a_file_changed_while_prompt_open(tmp_path):
    from metroliza.ui.export_dialog import ExportDialog
    from metroliza.exporting.export_backends import ExcelExportBackend

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"original")
    host = _dialog_host("replace")

    def choose(*_):
        target.write_bytes(b"another writer during confirmation")
        return "replace"

    host._choose_output_collision = choose
    request = ExportDialog._confirm_output_publication(host, _request("selected.db", target))
    thread = _export_thread(target)
    thread.replace_outputs = request.replace_outputs
    with pytest.raises(FileExistsError, match="changed after confirmation"):
        ExcelExportBackend().run(thread)
    assert target.read_bytes() == b"another writer during confirmation"


def test_export_start_rechecks_collision_after_database_change(monkeypatch, tmp_path):
    from metroliza.ui import export_dialog
    from tests.test_export_dialog_behavior import _build_dialog

    dialog = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "first.sqlite"))
    target = tmp_path / "existing.xlsx"
    target.write_bytes(b"last complete NOK workbook")
    prompts, starts = [], []

    def cancel(prompt):
        prompts.append(prompt.text())
        prompt.button(export_dialog.QMessageBox.StandardButton.Cancel).click()

    monkeypatch.setattr(export_dialog.QMessageBox, "exec", cancel)
    monkeypatch.setattr(export_dialog, "create_export_data_thread", lambda request: starts.append(request))
    dialog.excel_file = target
    try:
        dialog.show_loading_screen()
        dialog._update_database_context(str(tmp_path / "second.DB"))
        dialog.show_loading_screen()
        assert len(prompts) == 2
        assert "first.sqlite" in prompts[0] and "second.DB" in prompts[1]
        assert starts == []
        assert target.read_bytes() == b"last complete NOK workbook"
    finally:
        dialog.close()


def test_dashboard_target_created_after_render_is_preserved(tmp_path):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting.output_publication import write_dashboard_safely

    target = tmp_path / "dashboard.html"

    def render(**kwargs):
        result = write_export_html_dashboard(**kwargs)
        target.write_text("NOK dashboard from another operation")
        return result

    with pytest.raises(FileExistsError, match="Save a copy"):
        write_dashboard_safely(render, output_path=target, assets_dir=tmp_path / "dashboard_assets", sections=[])
    assert target.read_text() == "NOK dashboard from another operation"
    assert set(tmp_path.iterdir()) == {target, tmp_path / f".{target.name}.publish.lock"}


def test_html_only_collision_copy_keeps_existing_dashboard(tmp_path):
    from metroliza.ui.export_dialog import ExportDialog
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest

    target = tmp_path / "dashboard.html"
    target.write_text("old NOK dashboard")
    request = ExportRequest(
        AppPaths("selected.sqlite", html_dashboard_file=str(target)),
        ExportOptions(export_target="html_dashboard"),
    )
    result = ExportDialog._confirm_output_publication(_dialog_host("copy"), request)
    assert result.paths.excel_file is None
    assert result.paths.html_dashboard_file == str(tmp_path / "dashboard (2).html")
    assert not result.replace_outputs
    assert target.read_text() == "old NOK dashboard"


@pytest.mark.parametrize("exists", [False, True])
def test_windows_publication_uses_no_replace_rename_policy(monkeypatch, tmp_path, exists):
    from metroliza.exporting import output_publication as publication

    temporary, target = tmp_path / "staged.xlsx", tmp_path / "out.xlsx"
    temporary.write_bytes(b"complete NOK workbook")
    if exists:
        target.write_bytes(b"old result")
    calls = []
    original_rename = publication.os.rename

    def windows_rename(source, destination):
        calls.append((source, destination))
        if destination.exists():
            raise FileExistsError(str(destination))
        original_rename(source, destination)

    monkeypatch.setattr(publication, "_WINDOWS", True)
    monkeypatch.setattr(publication.os, "rename", windows_rename)
    if exists:
        with pytest.raises(FileExistsError, match="Save a copy"):
            publication.publish_output(temporary, target)
        assert target.read_bytes() == b"old result" and temporary.exists()
    else:
        publication.publish_output(temporary, target)
        assert target.read_bytes() == b"complete NOK workbook" and not temporary.exists()
    assert calls == [(temporary, target)]


def test_replacement_consent_survives_validation_and_worker_creation(tmp_path, qapplication_session):
    from metroliza.exporting.contracts import validate_export_request
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"last complete NOK workbook")
    request = ExportDialog._confirm_output_publication(_dialog_host("replace"), _request("selected.sqlite3", target))
    validated = validate_export_request(request)
    worker = ExportDataThread(validated)
    assert worker.replace_outputs == request.replace_outputs
    assert len(worker.replace_outputs) == 1
    assert worker.db_file == "selected.sqlite3"
    assert target.read_bytes() == b"last complete NOK workbook"


def test_locked_dashboard_replace_keeps_old_html_assets_and_cleans_new_generation(monkeypatch, tmp_path):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting import output_publication as publication

    target = tmp_path / "dashboard.html"
    assets = tmp_path / "dashboard_assets"
    target.write_text("old NOK dashboard")
    assets.mkdir()
    (assets / "old.png").write_bytes(b"old NOK asset")
    consents = (publication.OutputConsent.for_path(target),)
    original_replace = publication.os.replace

    def locked(source, destination):
        if Path(destination) == target:
            raise PermissionError("locked dashboard")
        original_replace(source, destination)

    monkeypatch.setattr(publication.os, "replace", locked)
    with pytest.raises(PermissionError, match="existing file was kept"):
        publication.write_dashboard_safely(
            write_export_html_dashboard, consents=consents,
            output_path=target, assets_dir=assets, sections=[],
        )
    assert target.read_text() == "old NOK dashboard"
    assert (assets / "old.png").read_bytes() == b"old NOK asset"
    assert set(tmp_path.iterdir()) == {target, assets, tmp_path / f".{target.name}.publish.lock"}
