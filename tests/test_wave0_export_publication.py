"""#1159: no workbook or HTML output is replaced without operation-specific consent."""

from pathlib import Path
from types import SimpleNamespace
import errno
import time
import zipfile

import pytest

from tests.test_wave0_sqlite_paths import _real_qt_bound_modules  # noqa: F401  (autouse fixture)


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


def test_dashboard_assets_transient_windows_permission_error_is_retried(monkeypatch, tmp_path):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting import output_publication as publication

    target = tmp_path / "dashboard.html"
    rename = publication.os.rename
    attempts = []

    def temporarily_locked(source, destination):
        if Path(source).is_dir():
            attempts.append(Path(destination))
            if len(attempts) == 1:
                raise PermissionError(5, "simulated AV directory handle")
        return rename(source, destination)

    monkeypatch.setattr(publication.os, "rename", temporarily_locked)
    result = publication.write_dashboard_safely(
        write_export_html_dashboard, output_path=target,
        assets_dir=tmp_path / "dashboard_assets", sections=[], source_label="NOK",
    )
    assert target.is_file() and Path(result["html_dashboard_assets_path"]).is_dir()
    assert len(attempts) == 2
    assert "NOK" in target.read_text()


@pytest.mark.parametrize("kernel_noreplace", [True, False])
@pytest.mark.parametrize("error_number", [errno.EPERM, errno.EMLINK, errno.ENOTSUP, errno.EOPNOTSUPP])
def test_publication_without_hardlink_support_is_atomic_and_no_clobber(monkeypatch, tmp_path, error_number, kernel_noreplace):
    from metroliza.exporting import output_publication as publication

    temporary, target = tmp_path / "stage.xlsx", tmp_path / "output.xlsx"
    temporary.write_bytes(b"complete NOK workbook")
    monkeypatch.setattr(publication, "_WINDOWS", False)

    def unsupported(*_):
        raise OSError(error_number, "hard links unsupported")

    monkeypatch.setattr(publication.os, "link", unsupported)
    if not kernel_noreplace:
        monkeypatch.setattr(publication, "_rename_noreplace", lambda *_: False)
    open_file = Path.open

    def never_write_final_name(path, mode="r", *args, **kwargs):
        assert not (Path(path) == target and any(flag in mode for flag in "wxa")), "final name must not receive partial content"
        return open_file(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", never_write_final_name)
    moves = []
    real_rename, real_noreplace = publication.os.rename, publication._rename_noreplace
    monkeypatch.setattr(publication.os, "rename", lambda src, dst: moves.append(("rename", Path(src), Path(dst))) or real_rename(src, dst))
    if kernel_noreplace:
        monkeypatch.setattr(publication, "_rename_noreplace", lambda src, dst: moves.append(("noreplace", Path(src), Path(dst))) or real_noreplace(src, dst))
    publication.publish_output(temporary, target)
    # The final name is only ever produced by one whole-file rename of the complete staged file.
    assert [(src, dst) for _kind, src, dst in moves] == [(temporary, target)]
    assert target.read_bytes() == b"complete NOK workbook"
    assert not temporary.exists()
    temporary.write_bytes(b"other workbook")
    with pytest.raises(FileExistsError, match="Save a copy"):
        publication.publish_output(temporary, target)
    assert target.read_bytes() == b"complete NOK workbook"
    assert temporary.read_bytes() == b"other workbook"


def test_unsupported_hardlinks_do_not_blame_excel_for_folder_permissions(monkeypatch, tmp_path):
    from metroliza.exporting import output_publication as publication

    temporary, target = tmp_path / "stage.xlsx", tmp_path / "output.xlsx"
    temporary.write_bytes(b"complete NOK workbook")

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "folder write denied")

    monkeypatch.setattr(publication, "_WINDOWS", False)
    monkeypatch.setattr(publication.os, "link", lambda *_: (_ for _ in ()).throw(PermissionError(1, "unsupported")))
    monkeypatch.setattr(publication, "_rename_noreplace", lambda *_: False)
    monkeypatch.setattr(publication.os, "rename", denied)
    with pytest.raises(OSError) as error:
        publication.publish_output(temporary, target)
    assert "Excel" not in str(error.value)
    assert temporary.read_bytes() == b"complete NOK workbook"
    assert not target.exists()


@pytest.mark.parametrize("dashboard", [False, True])
def test_save_copy_retries_publication_race_and_reports_actual_workbook(tmp_path, qapplication_session, dashboard):
    from metroliza.exporting.contracts import validate_export_request
    from metroliza.exporting.export_backends import ExcelExportBackend
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"last complete NOK workbook")
    request = ExportDialog._confirm_output_publication(_dialog_host("copy"), _request("selected.db", target, dashboard=dashboard))
    worker = ExportDataThread(validate_export_request(request))
    first_copy = Path(worker.excel_file)
    worker.run_export_pipeline = _export_thread(first_copy, race=True).run_export_pipeline
    assert ExcelExportBackend().run(worker)
    actual = tmp_path / "out (3).xlsx"
    assert Path(worker.excel_file) == actual
    assert Path(worker._primary_output_file) == actual
    assert worker.completion_metadata["published_output_path"] == str(actual)
    assert worker.completion_metadata["local_xlsx_path"] == str(actual)
    assert actual.is_file()
    assert first_copy.read_bytes() == b"created by another operation"
    assert target.read_bytes() == b"last complete NOK workbook"
    if dashboard:
        assert Path(worker.html_dashboard_file) == tmp_path / "out (3)_dashboard.html"
        assert Path(worker.html_dashboard_assets_dir) == tmp_path / "out (3)_dashboard_assets"


def test_save_copy_html_only_retries_race_after_render(tmp_path, qapplication_session, monkeypatch):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting import export_data_thread
    from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "dashboard.html"
    target.write_text("last complete NOK dashboard")
    request = ExportRequest(AppPaths("selected.db", html_dashboard_file=str(target)), ExportOptions(export_target="html_dashboard"))
    request = ExportDialog._confirm_output_publication(_dialog_host("copy"), request)
    worker = export_data_thread.ExportDataThread(request)
    occupied = tmp_path / "dashboard (2).html"
    calls = []

    def render(**kwargs):
        result = write_export_html_dashboard(**kwargs)
        calls.append(result)
        if len(calls) == 1:
            occupied.write_text("NOK dashboard from another operation")
        return result

    monkeypatch.setattr(export_data_thread, "_write_export_html_dashboard", render)
    worker._write_html_dashboard_if_requested()
    actual = tmp_path / "dashboard (3).html"
    assert Path(worker.completion_metadata["html_dashboard_path"]) == actual
    assert Path(worker._primary_output_file) == actual
    assert actual.is_file()
    assert f"<h1>{actual.name}</h1>" in actual.read_text()
    assert target.read_text() == "last complete NOK dashboard"
    assert occupied.read_text() == "NOK dashboard from another operation"
    assert len(calls) == 2


@pytest.mark.parametrize("error_type,expected_attempts", [(PermissionError, 10), (OSError, 1)])
def test_dashboard_directory_move_retry_is_bounded_and_cleans_staging(monkeypatch, tmp_path, error_type, expected_attempts):
    from metroliza.charts.export_html_dashboard import write_export_html_dashboard
    from metroliza.exporting import output_publication as publication

    target = tmp_path / "dashboard.html"
    target.write_text("last complete NOK dashboard")
    attempts, delays = [], []

    def locked(source, destination):
        attempts.append((source, destination))
        raise error_type("directory cannot move")

    monkeypatch.setattr(publication.os, "rename", locked)
    monkeypatch.setattr(time, "sleep", delays.append)
    with pytest.raises(error_type):
        publication.write_dashboard_safely(
            write_export_html_dashboard, output_path=target,
            assets_dir=tmp_path / "dashboard_assets", sections=[],
            consents=(publication.OutputConsent.for_path(target),),
        )
    assert len(attempts) == expected_attempts
    assert len(delays) == expected_attempts - 1 and sum(delays) < 2
    assert target.read_text() == "last complete NOK dashboard"
    assert set(tmp_path.iterdir()) == {target, tmp_path / f".{target.name}.publish.lock"}


def test_hardlink_fallback_failure_leaves_no_final_file(monkeypatch, tmp_path):
    from metroliza.exporting import output_publication as publication

    temporary, target = tmp_path / "stage.xlsx", tmp_path / "output.xlsx"
    temporary.write_bytes(b"next NOK workbook")
    monkeypatch.setattr(publication, "_WINDOWS", False)
    monkeypatch.setattr(publication.os, "link", lambda *_: (_ for _ in ()).throw(PermissionError(1, "unsupported")))
    monkeypatch.setattr(publication, "_rename_noreplace", lambda *_: (_ for _ in ()).throw(OSError(errno.ENOSPC, "simulated full disk")))
    with pytest.raises(OSError, match="full disk"):
        publication.publish_output(temporary, target)
    assert not target.exists()
    assert temporary.read_bytes() == b"next NOK workbook"


def test_save_copy_publication_stops_after_twenty_races_without_replacing(monkeypatch, tmp_path, qapplication_session):
    from metroliza.exporting import export_backends
    from metroliza.exporting.export_data_thread import ExportDataThread
    from metroliza.ui.export_dialog import ExportDialog

    target = tmp_path / "out.xlsx"
    target.write_bytes(b"last complete NOK workbook")
    request = ExportDialog._confirm_output_publication(_dialog_host("copy"), _request("selected.db", target))
    worker = ExportDataThread(request)
    worker.run_export_pipeline = _export_thread(target).run_export_pipeline
    calls = []

    def race(temporary, candidate, **kwargs):
        calls.append(candidate)
        candidate.write_bytes(b"NOK concurrent writer")
        raise FileExistsError("simulated publication collision")

    monkeypatch.setattr(export_backends, "publish_output", race)
    with pytest.raises(FileExistsError):
        export_backends.ExcelExportBackend().run(worker)
    assert len(calls) == len(set(calls)) == 20
    assert target.read_bytes() == b"last complete NOK workbook"
    assert all(path.read_bytes() == b"NOK concurrent writer" for path in calls)
    assert set(tmp_path.iterdir()) == {target, *calls}


@pytest.mark.parametrize("terminal", ["finished", "canceled"])
def test_copy_completion_dialog_links_to_actual_published_workbook(monkeypatch, tmp_path, qapplication_session, terminal):
    from metroliza.ui import export_dialog
    from tests.test_export_dialog_behavior import _build_dialog

    dialog = _build_dialog(monkeypatch, tmp_path, db_file="selected.db")
    dialog.excel_file = tmp_path / "out (2).xlsx"
    actual = tmp_path / "out (3).xlsx"
    actual.write_bytes(b"complete NOK workbook")
    dialog.export_thread = SimpleNamespace(
        export_target="excel_xlsx", completion_metadata={"published_output_path": str(actual)},
    )
    seen = []
    monkeypatch.setattr(export_dialog, "show_export_result_message", lambda *args, **kwargs: seen.append(kwargs))
    try:
        getattr(dialog, f"on_export_{terminal}")()
        assert seen and Path(seen[0]["excel_file"]) == actual
    finally:
        dialog.export_thread = None
        dialog.close()


@pytest.mark.parametrize(("error_number", "supported"), [
    (errno.EINVAL, False), (errno.ENOSYS, False), (errno.ENOTSUP, False), (errno.EOPNOTSUPP, False),
    (errno.EEXIST, None), (errno.EACCES, None),
])
def test_rename_noreplace_errno_mapping(monkeypatch, tmp_path, error_number, supported):
    import ctypes
    from metroliza.exporting import output_publication as publication

    def renameat2(*_args):
        return -1

    fake_libc = type("FakeLibc", (), {})()
    fake_libc.renameat2 = renameat2
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: fake_libc)
    monkeypatch.setattr(ctypes, "get_errno", lambda: error_number)
    if supported is False:
        assert publication._rename_noreplace(tmp_path / "a", tmp_path / "b") is False
    else:
        expected = FileExistsError if error_number == errno.EEXIST else PermissionError
        with pytest.raises(expected):
            publication._rename_noreplace(tmp_path / "a", tmp_path / "b")


def test_rename_noreplace_missing_symbol_falls_back(monkeypatch, tmp_path):
    import ctypes
    from metroliza.exporting import output_publication as publication

    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: object())
    assert publication._rename_noreplace(tmp_path / "a", tmp_path / "b") is False


def test_hardlink_exdev_fallback_never_copies_into_final_name(monkeypatch, tmp_path):
    from metroliza.exporting import output_publication as publication

    temporary, target = tmp_path / "stage.xlsx", tmp_path / "output.xlsx"
    temporary.write_bytes(b"complete NOK workbook")
    monkeypatch.setattr(publication, "_WINDOWS", False)
    monkeypatch.setattr(publication.os, "link", lambda *_: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    publication.publish_output(temporary, target)
    assert target.read_bytes() == b"complete NOK workbook" and not temporary.exists()
