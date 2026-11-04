from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

if importlib.util.find_spec("PyQt6") is None:  # pragma: no cover - optional local test runtime.
    QApplication = None
    QDialog = None
    export_dialog = None
    FilterState = None
    NOT_APPLIED_LABEL = "Not applied"
    PYQT_IMPORT_ERROR = ModuleNotFoundError("PyQt6 is not installed")
else:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QApplication, QDialog

    import metroliza.ui.export_dialog as export_dialog
    from metroliza.shared.filter_state import FilterState, NOT_APPLIED_LABEL
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 export dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _build_dialog(monkeypatch, tmp_path, *, db_file=""):
    _app()
    monkeypatch.setattr(
        export_dialog.ExportDialog,
        "_load_dialog_config",
        lambda self: {"selected_preset": "fast_diagnostics"},
    )
    monkeypatch.setattr(export_dialog.ExportDialog, "_save_dialog_config", lambda self: None)
    monkeypatch.setattr(export_dialog, "load_dashboard_visual_settings", lambda: {"preset": "auto"})
    dialog = export_dialog.ExportDialog(parent=None, db_file=db_file)
    dialog.config_path = tmp_path / "export-config.json"
    return dialog


def _combo_labels(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def _set_combo_to_existing_label(combo, needle):
    for label in _combo_labels(combo):
        if needle in label:
            combo.setCurrentText(label)
            return label
    raise AssertionError(f"Missing combo label containing {needle!r}: {_combo_labels(combo)}")


@pytest.mark.parametrize("html_only", [False, True])
@pytest.mark.parametrize("has_database", [False, True])
def test_dated_export_default_and_collision_counter(monkeypatch, tmp_path, html_only, has_database):
    from datetime import date

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 4)

    monkeypatch.setattr(export_dialog, "date", FrozenDate, raising=False)
    monkeypatch.setattr(export_dialog.Path, "home", lambda: tmp_path)
    database = str(tmp_path / "line-a.db") if has_database else ""
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=database)
    monkeypatch.setattr(dialog, "_is_html_dashboard_only", lambda: html_only)
    captured = []
    monkeypatch.setattr(export_dialog.QFileDialog, "getSaveFileName",
                        lambda _p, _t, proposed, _f: (captured.append(proposed) or "", ""))
    stem = "line-a" if has_database else "export"
    suffix = "_dashboard.html" if html_only else ".xlsx"
    expected = tmp_path / f"{stem}_2026-11-04{suffix}"
    try:
        dialog.select_excel_file()
        assert captured[-1] == str(expected)
        assert dialog.excel_file == ""  # Cancelling does not select the proposal.
        expected.touch()
        expected.with_stem(expected.stem + "_1").touch()
        dialog.select_excel_file()
        assert captured[-1] == str(expected.with_stem(expected.stem + "_2"))
    finally:
        dialog.close()


@pytest.mark.parametrize("html_only", [False, True])
def test_export_keeps_user_chosen_name_when_browsing_again(monkeypatch, tmp_path, html_only):
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "line-a.db"))
    monkeypatch.setattr(dialog, "_is_html_dashboard_only", lambda: html_only)
    chosen = tmp_path / ("chosen.html" if html_only else "chosen.xlsx")
    chosen.touch()
    captured = []

    def select(_parent, _title, proposed, _filter):
        captured.append(proposed)
        return str(chosen), ""

    monkeypatch.setattr(export_dialog.QFileDialog, "getSaveFileName", select)
    try:
        dialog.select_excel_file()
        assert dialog.excel_file == chosen
        dialog.select_excel_file()
        assert captured[-1] == str(chosen)
        dialog._coerce_output_path_for_mode()
        assert dialog.excel_file == chosen
    finally:
        dialog.close()


def test_result_dialog_sanitizes_details_before_display_or_copy(monkeypatch):
    captured = {}

    class _Dialog:
        def exec(self):
            captured["executed"] = True

    monkeypatch.setattr(export_dialog, "QMessageBox", lambda _parent: _Dialog())
    monkeypatch.setattr(
        export_dialog,
        "_configure_export_result_dialog",
        lambda _dialog, **kwargs: captured.setdefault("display", kwargs["diagnostics"]),
    )
    monkeypatch.setattr(
        export_dialog,
        "_add_export_result_actions",
        lambda _dialog, **_kwargs: (None, None),
    )
    monkeypatch.setattr(export_dialog, "_connect_export_result_links", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        export_dialog,
        "_handle_export_result_action",
        lambda _dialog, **kwargs: captured.setdefault("copy", kwargs["diagnostics"]),
    )
    secret = "postgresql://operator:secret-password@host/reports"

    export_dialog.show_export_result_message(
        None,
        "error",
        "Export failed",
        "The export failed.",
        diagnostics=f"terminal_failure: RuntimeError: could not connect to {secret}",
    )

    assert captured["executed"]
    assert captured["display"] == captured["copy"]
    assert secret not in captured["display"]
    assert "could not connect" not in captured["display"]
    assert "terminal_failure" in captured["display"]
    assert "failure_type=ExportError" in captured["display"]


def test_path_filter_group_controls_and_button_state(monkeypatch, tmp_path):
    dialog = _build_dialog(monkeypatch, tmp_path)
    try:
        assert dialog.database_text_label.accessibleName() == "Export source database"
        assert dialog.excel_file_text_label.accessibleName() == "Export output path"
        assert not dialog.export_button.isEnabled()
        assert "Select both" in dialog.path_readiness_label.text()

        dialog.excel_file = tmp_path / "export.xlsx"
        dialog._set_path_field_value(dialog.excel_file_text_label, dialog.excel_file)
        dialog._update_export_button_enabled_state()

        assert not dialog.export_button.isEnabled()
        assert "Select a database file" in dialog.path_readiness_label.text()

        dialog.set_filter_state(FilterState(ax_values=("AX1",), has_nok_only=True))
        dialog.set_grouping_applied(True)

        class _ChildDialog:
            def __init__(self):
                self.closed = False
                self.deleted = False

            def close(self):
                self.closed = True

            def deleteLater(self):
                self.deleted = True

        filter_window = _ChildDialog()
        grouping_window = _ChildDialog()
        dialog.filter_window = filter_window
        dialog.grouping_window = grouping_window
        dialog.df_for_grouping = object()

        dialog._update_database_context(str(tmp_path / "source.db"))

        assert dialog.export_button.isEnabled()
        assert "Ready for export" in dialog.path_readiness_label.text()
        assert dialog.filter_query == export_dialog.DEFAULT_FILTER_QUERY
        assert dialog.filter_state is None
        assert dialog.select_filter_label.text() == NOT_APPLIED_LABEL
        assert dialog.df_for_grouping is None
        assert dialog.select_group_label.text() == "Not applied"
        assert dialog._selected_group_analysis_level() == "off"
        assert not hasattr(dialog, "group_analysis_level_combobox")
        assert not hasattr(dialog, "group_analysis_scope_combobox")
        assert dialog.filter_window is None
        assert dialog.grouping_window is None
        assert filter_window.closed and filter_window.deleted
        assert grouping_window.closed and grouping_window.deleted

        dialog.clear_filters()
        dialog.clear_grouping()

        assert dialog.filter_query == export_dialog.DEFAULT_FILTER_QUERY
        assert dialog.select_filter_label.text() == NOT_APPLIED_LABEL
        assert dialog.select_group_label.text() == "Not applied"
    finally:
        dialog.close()


def test_export_parent_honors_dirty_child_close_refusal(monkeypatch, tmp_path):
    original_db = str(tmp_path / "original.db")
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=original_db)

    class _RefusingChild:
        def __init__(self):
            self.allow_close = False
            self.close_calls = 0
            self.deleted = False

        def close(self):
            self.close_calls += 1
            return self.allow_close

        def deleteLater(self):
            self.deleted = True

    child = _RefusingChild()
    dialog.filter_window = child
    dialog.show()
    try:
        assert dialog._update_database_context(str(tmp_path / "replacement.db")) is False
        assert dialog.db_file == original_db
        assert dialog.filter_window is child
        assert child.deleted is False

        assert dialog.close() is False
        assert dialog.isVisible()
        assert dialog.filter_window is child

        child.allow_close = True
        assert dialog.close() is True
        assert child.deleted is True
        assert dialog.filter_window is None
    finally:
        child.allow_close = True
        dialog.close()


def test_output_mode_and_option_synchronization(monkeypatch, tmp_path):
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "source.db"))
    try:
        dialog.excel_file = tmp_path / "source.xlsx"
        dialog.include_google_sheets_checkbox.setChecked(True)

        assert dialog._selected_export_target() == "google_sheets_drive_convert"
        assert dialog._selected_group_analysis_level() == "off"
        assert dialog._selected_group_analysis_scope() == "auto"
        assert not hasattr(dialog, "group_analysis_level_combobox")
        assert not hasattr(dialog, "group_analysis_scope_combobox")

        dialog.set_grouping_applied(True)
        assert dialog._selected_group_analysis_level() == "standard"
        assert dialog._selected_group_analysis_scope() == "auto"
        assert dialog.generate_html_dashboard_checkbox.isChecked()
        assert not dialog.generate_html_dashboard_checkbox.isEnabled()
        assert dialog.dashboard_visuals_button.isEnabled()

        selected_label = _set_combo_to_existing_label(dialog.preset_combobox, "HTML dashboard only")
        dialog.preset_combobox.setCurrentText(selected_label)
        dialog._sync_html_dashboard_only_state()

        assert dialog._selected_export_target() == "html_dashboard"
        assert dialog.generate_html_dashboard_checkbox.isChecked()
        assert not dialog.generate_html_dashboard_checkbox.isEnabled()
        assert not dialog.include_google_sheets_checkbox.isChecked()
        assert not dialog.include_google_sheets_checkbox.isEnabled()
        assert dialog.select_excel_label.text() == "Dashboard file:"
        assert str(dialog.excel_file).endswith("_dashboard.html")
        assert "HTML dashboard selected" in dialog.path_readiness_label.text()
        assert not dialog.dashboard_visuals_button.isHidden()
        assert dialog.dashboard_visuals_button.isEnabled()
        assert "Adjust HTML dashboard" in dialog.dashboard_visuals_button.toolTip()

        _set_combo_to_existing_label(dialog.preset_combobox, "Main plots")
        dialog._sync_html_dashboard_only_state()

        assert dialog.select_excel_label.text() == "Excel file:"
        assert str(dialog.excel_file).endswith("source.xlsx")
        assert dialog.include_google_sheets_checkbox.isEnabled()
    finally:
        dialog.close()


def test_deliverables_summary_tracks_export_context(monkeypatch, tmp_path):
    dialog = _build_dialog(monkeypatch, tmp_path)
    try:
        summary = dialog.deliverables_summary_label.text()
        assert "Database: not selected" in summary
        assert "Workbook: not selected" in summary
        assert "Preset: Main plots" in summary
        assert "HTML dashboard: off" in summary
        assert "Google Sheets: off" in summary
        assert "Grouping: off" in summary
        assert "Industrial context: off" in summary

        dialog._update_database_context(str(tmp_path / "source.db"))
        dialog.excel_file = tmp_path / "export.xlsx"
        dialog._set_path_field_value(dialog.excel_file_text_label, dialog.excel_file)
        dialog._update_export_button_enabled_state()
        dialog.include_google_sheets_checkbox.setChecked(True)
        dialog.generate_html_dashboard_checkbox.setChecked(True)
        dialog.include_industrial_context_checkbox.setChecked(True)
        dialog.set_grouping_applied(True)

        summary = dialog.deliverables_summary_label.text()
        assert "Database: source.db" in summary
        assert "Workbook: export.xlsx" in summary
        assert "HTML dashboard: on (grouping)" in summary
        assert "Google Sheets: on" in summary
        assert "Grouping: on" in summary
        assert "Industrial context: on" in summary
        assert dialog.deliverables_summary_label.property("statusVariant") == "success"

        dialog.set_grouping_applied(False)
        _set_combo_to_existing_label(dialog.preset_combobox, "HTML dashboard only")
        dialog._sync_html_dashboard_only_state()

        summary = dialog.deliverables_summary_label.text()
        assert "Dashboard: export_dashboard.html" in summary
        assert "HTML dashboard: standalone" in summary
        assert "Google Sheets: off (dashboard only)" in summary
    finally:
        dialog.close()


def test_select_excel_file_and_validation_warning_branches(monkeypatch, tmp_path):
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "source.db"))
    try:
        selected_path = tmp_path / "manual.xlsx"
        monkeypatch.setattr(
            export_dialog.QFileDialog,
            "getSaveFileName",
            lambda *args: (str(selected_path), "Excel workbook (*.xlsx)"),
        )

        dialog.select_excel_file()

        assert dialog.excel_file == selected_path
        assert dialog.export_button.isEnabled()

        dialog.violin_plot_min_samplesize.setText("1")
        dialog.summary_plot_scale.setText("bad")
        dialog.validate_violin_plot_min_samplesize_input()
        dialog.validate_plot_scale_input()

        assert dialog.violin_plot_min_samplesize.text() == "2"
        assert dialog.summary_plot_scale.text() == "0"

        warnings = []
        monkeypatch.setattr(
            export_dialog.QMessageBox,
            "warning",
            lambda *args: warnings.append(args),
        )
        monkeypatch.setattr(
            export_dialog,
            "build_validated_export_request",
            lambda **kwargs: (_ for _ in ()).throw(ValueError("missing source rows")),
        )

        dialog.show_loading_screen()

        assert warnings
        assert warnings[0][1] == "Export validation failed"
        assert "missing source rows" in warnings[0][2]
        assert dialog.export_thread is None
    finally:
        dialog.close()


def test_filter_group_window_guards_and_metadata_notice(monkeypatch, tmp_path):
    class _Parent(QDialog):
        def __init__(self):
            super().__init__()
            self.db_file = None

        def is_metadata_enrichment_active(self):
            return True

        def set_db_file(self, db_file):
            self.db_file = db_file

    _app()
    parent = _Parent()
    dialog = _build_dialog(monkeypatch, tmp_path, db_file="")
    dialog.setParent(parent)
    try:
        notices = []
        monkeypatch.setattr(
            export_dialog.QMessageBox,
            "information",
            lambda *args: notices.append(args),
        )

        assert dialog._refresh_metadata_enrichment_notice() is True
        assert not dialog.metadata_enrichment_notice_label.isHidden()

        dialog.open_filter_window()
        dialog.open_grouping_window()

        assert [notice[1] for notice in notices] == ["Database required", "Database required"]

        class _FakeChild:
            def __init__(self, *args, **kwargs):
                self.show_count = 0
                self.raise_count = 0
                self.activate_count = 0
                self.refresh_count = 0

            def isVisible(self):
                return self.show_count > 0

            def show(self):
                self.show_count += 1

            def raise_(self):
                self.raise_count += 1

            def activateWindow(self):
                self.activate_count += 1

            def refresh_data(self):
                self.refresh_count += 1

        monkeypatch.setattr(export_dialog, "FilterDialog", _FakeChild)
        monkeypatch.setattr(export_dialog, "DataGrouping", _FakeChild)
        dialog.db_file = str(tmp_path / "source.db")

        dialog.open_filter_window()
        dialog.open_filter_window()
        dialog.open_grouping_window()
        dialog.open_grouping_window()

        assert dialog.filter_window.show_count == 1
        assert dialog.filter_window.raise_count == 2
        assert dialog.grouping_window.show_count == 1
        assert dialog.grouping_window.refresh_count == 1
    finally:
        dialog.close()
        parent.close()


def test_export_dialog_helper_methods(monkeypatch, tmp_path):
    linked = export_dialog.format_message_with_clickable_links(
        "See https://example.invalid/a?b=1&c=2\nDone"
    )

    assert '<a href="https://example.invalid/a?b=1&amp;c=2">' in linked
    assert "<br>" in linked

    class _TerminalDialog:
        def __init__(self):
            self.calls = []

        def reject_as_terminal(self):
            self.calls.append("reject_as_terminal")

    terminal_dialog = _TerminalDialog()
    export_dialog._reject_progress_dialog_as_terminal(terminal_dialog)

    assert terminal_dialog.calls == ["reject_as_terminal"]

    class _LegacyDialog:
        def __init__(self):
            self.calls = []

        def request_terminal_close(self):
            self.calls.append("request_terminal_close")

        def reject(self):
            self.calls.append("reject")

    legacy_dialog = _LegacyDialog()
    export_dialog._reject_progress_dialog_as_terminal(legacy_dialog)

    assert legacy_dialog.calls == ["request_terminal_close", "reject"]

    exported_file = tmp_path / "export.xlsx"
    exported_file.write_text("placeholder", encoding="utf-8")
    reveals = []
    opened = []
    monkeypatch.setattr(export_dialog, "reveal_file_in_explorer", lambda path: reveals.append(path))
    monkeypatch.setattr(export_dialog.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)

    export_dialog.handle_export_result_link(
        None,
        QUrl.fromLocalFile(str(exported_file)).toString(),
        excel_file=exported_file,
    )
    export_dialog.handle_export_result_link(None, "https://example.invalid/result", excel_file=exported_file)

    assert reveals == []
    assert len(opened) == 2
    assert opened[0].toLocalFile() == str(exported_file)
    assert opened[1].scheme() == "https"


def test_reveal_file_in_explorer_failure_branch(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_dialog.reveal_file_in_explorer(Path(tmp_path / "missing.xlsx"))


def test_export_lifecycle_success_cancel_and_terminal_paths(monkeypatch, tmp_path):
    dialog = _build_dialog(monkeypatch, tmp_path, db_file=str(tmp_path / "source.db"))
    try:
        dialog.excel_file = tmp_path / "source.xlsx"
        dialog.violin_plot_min_samplesize.setText("7")
        dialog.summary_plot_scale.setText("3")

        export_request = types.SimpleNamespace(
            paths=types.SimpleNamespace(excel_file=str(tmp_path / "validated.xlsx"), html_dashboard_file=None),
            options=types.SimpleNamespace(
                violin_plot_min_samplesize=7, summary_plot_scale=3,
                export_target="excel_xlsx", generate_html_dashboard=False,
            ),
        )
        validation_calls = {}
        monkeypatch.setattr(
            export_dialog,
            "build_validated_export_request",
            lambda **kwargs: validation_calls.update(kwargs) or export_request,
        )
        monkeypatch.setattr(export_dialog, "save_export_dialog_config", lambda *args: None)

        class _Signal:
            def __init__(self):
                self.callbacks = []

            def connect(self, callback):
                self.callbacks.append(callback)

        class _FakeThread:
            def __init__(self):
                self.update_label = _Signal()
                self.update_progress = _Signal()
                self.error_occurred = _Signal()
                self.completed = _Signal()
                self.finished = _Signal()
                self.canceled = _Signal()
                self.running = True
                self.started = False
                self.stopped = False
                self.deleted = False
                self.export_target = "excel_xlsx"
                self.completion_metadata = {"excel_file": str(tmp_path / "validated.xlsx")}

            def start(self):
                self.started = True

            def isRunning(self):
                return self.running

            def stop_exporting(self):
                self.stopped = True

            def deleteLater(self):
                self.deleted = True

        events = []

        class _FakeProgressDialog:
            def __init__(self):
                self.shown = False
                self.accepted = False
                self.rejected_as_terminal = False
                self.cancel_button = export_dialog.QPushButton("Cancel")

            def show(self):
                self.shown = True

            def accept(self):
                self.accepted = True
                events.append("progress_accepted")

            def reject_as_terminal(self):
                self.rejected_as_terminal = True
                events.append("progress_rejected")

            def findChildren(self, *_args):
                return [self.cancel_button]

        progress_dialog = _FakeProgressDialog()
        loading_label = export_dialog.QLabel("")
        loading_bar = types.SimpleNamespace(setValue=lambda value: None)
        fake_thread = _FakeThread()
        monkeypatch.setattr(
            export_dialog,
            "create_worker_progress_dialog",
            lambda *args, **kwargs: (progress_dialog, loading_label, loading_bar, None),
        )
        monkeypatch.setattr(export_dialog, "create_export_data_thread", lambda request: fake_thread)

        dialog.last_result_row.set_result("completed")
        dialog._update_export_button_enabled_state()
        assert not dialog.last_result_row.isHidden()
        dialog.show_loading_screen()
        assert dialog.last_result_row.isHidden()

        assert validation_calls["db_file"] == str(tmp_path / "source.db")
        assert dialog.excel_file == tmp_path / "validated.xlsx"
        assert dialog.violin_plot_min_samplesize.text() == "7"
        assert dialog.summary_plot_scale.text() == "3"
        assert fake_thread.started
        assert progress_dialog.shown
        assert not dialog.export_button.isEnabled()
        assert fake_thread.update_label.callbacks == [loading_label.setText]
        assert fake_thread.update_progress.callbacks == [loading_bar.setValue]

        dialog.stop_exporting()

        assert fake_thread.stopped
        assert dialog._cancel_requested is True
        assert not progress_dialog.cancel_button.isEnabled()
        assert "Cancel requested" in loading_label.text()

        notices = []

        def _record_information(*args):
            notices.append(args)
            events.append("message")

        monkeypatch.setattr(export_dialog.QMessageBox, "information", _record_information)
        cancel_results = []
        monkeypatch.setattr(
            export_dialog,
            "show_export_result_message",
            lambda *args, **kwargs: (
                cancel_results.append((args, kwargs)),
                events.append("rich_message"),
            ),
        )
        dialog.on_export_canceled()

        assert cancel_results[-1][0][2] == "Export cancelled"
        assert "cancelled" in dialog.last_result_row.summary.text()
        assert not dialog.last_result_row.findChildren(export_dialog.QPushButton)
        assert progress_dialog.rejected_as_terminal
        assert events[-2:] == ["progress_rejected", "rich_message"]
        assert dialog.export_button.isEnabled()
        assert dialog._cancel_requested is False
        assert progress_dialog.cancel_button.isEnabled()

        result_messages = []
        monkeypatch.setattr(
            export_dialog,
            "build_export_completion_message",
            lambda **kwargs: (
                ("error", "Export failed", "The export did not complete its required output.")
                if kwargs.get("terminal_failure")
                else ("info", "Export complete", "Done")
            ),
        )
        monkeypatch.setattr(
            export_dialog,
            "show_export_result_message",
            lambda *args, **kwargs: (
                result_messages.append((args, kwargs)),
                events.append("rich_message"),
            ),
        )

        dialog.export_thread = fake_thread
        dialog.loading_dialog = progress_dialog
        events.clear()
        dialog.on_export_finished()

        assert progress_dialog.accepted
        assert result_messages
        assert events[:2] == ["progress_accepted", "rich_message"]
        assert dialog.export_error_message is None

        dialog.export_error_message = "disk full"
        events.clear()
        dialog.on_export_finished()

        assert result_messages[-1][0][2:4] == (
            "Export failed",
            "The export did not complete its required output.",
        )
        assert events[:2] == ["progress_accepted", "rich_message"]

        progress_dialog.accepted = False
        fake_thread.running = False
        dialog._export_terminal_handled = False
        dialog.export_error_message = None
        dialog._cancel_requested = False
        dialog.on_export_thread_stopped()

        assert progress_dialog.accepted
        assert dialog.export_button.isEnabled()
        assert fake_thread.deleted
        assert dialog.export_thread is None

        dialog.stop_exporting()

        assert notices[-1][1] == "Export canceled"
    finally:
        dialog.close()


@pytest.mark.parametrize("produced", [("book.xlsx",), ("dash.html",), ("book.xlsx", "dash.html"), ()])
def test_w1_completion_actions_only_for_produced_files(monkeypatch, tmp_path, produced):
    _app()
    paths = tuple(tmp_path / name for name in produced)
    for path in paths:
        path.touch()
    (tmp_path / "stale.xlsx").touch()
    opened, revealed = [], []
    monkeypatch.setattr(export_dialog.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    monkeypatch.setattr(export_dialog, "reveal_file_in_explorer", lambda path: revealed.append(Path(path)))

    def acknowledge(box):
        buttons = {button.text(): button for button in box.buttons()}
        expected = {"OK"}
        if produced:
            expected.add("Show in folder")
        if "book.xlsx" in produced:
            expected.add("Open workbook")
        if "dash.html" in produced:
            expected.add("Open dashboard")
        assert set(buttons) == expected
        for text, button in buttons.items():
            if text != "OK":
                button.click()
        return 0

    monkeypatch.setattr(export_dialog.QMessageBox, "exec", acknowledge)
    export_dialog.show_export_result_message(None, "info", "Done", "Done", artifacts=(*paths, tmp_path / "missing.html"))
    assert {url.toLocalFile() for url in opened} == {str(path) for path in paths}
    assert revealed == list(paths[:1])


@pytest.mark.parametrize("reveal", [False, True])
def test_w1_actions_check_missing_files_and_open_failure(monkeypatch, tmp_path, reveal):
    _app()
    path = tmp_path / "gone.xlsx"
    warnings, opened = [], []
    monkeypatch.setattr(export_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(export_dialog.QDesktopServices, "openUrl", lambda url: opened.append(url) or False)
    monkeypatch.setattr(export_dialog, "reveal_file_in_explorer", lambda p: opened.append(p))
    if reveal:
        from metroliza.ui.result_actions import activate_result_file
        activate_result_file(None, path, reveal=lambda p: opened.append(p))
    else:
        export_dialog.handle_export_result_link(None, path.resolve().as_uri(), excel_file=path)
    assert not opened
    assert str(path) in warnings[-1] and "was moved or deleted" in warnings[-1]
    path.touch()
    export_dialog.handle_export_result_link(None, path.resolve().as_uri(), excel_file=path)
    assert len(opened) == 1
    assert path.name in warnings[-1]


def test_w1_failed_shell_reveal_warns_instead_of_raising(monkeypatch, tmp_path):
    # Raised inside a Qt slot this would abort the app (no sys.excepthook).
    import subprocess
    from metroliza.ui.result_actions import activate_result_file

    _app()
    path = tmp_path / "out.xlsx"
    path.touch()
    warnings = []
    monkeypatch.setattr(export_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))

    def failing_reveal(_path):
        raise subprocess.CalledProcessError(3, ["xdg-open", str(tmp_path)])

    activate_result_file(None, path, reveal=failing_reveal)
    assert str(path) in warnings[-1] and "CalledProcessError" in warnings[-1]


def test_w1_local_folder_link_opens_folder(monkeypatch, tmp_path):
    _app()
    opened, warnings = [], []
    monkeypatch.setattr(export_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(export_dialog.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    export_dialog.handle_export_result_link(None, tmp_path.resolve().as_uri())
    assert [url.toLocalFile() for url in opened] == [str(tmp_path.resolve())]
    assert warnings == []


@pytest.mark.parametrize("status", ["complete", "complete_with_omissions", "cancelled", "failed"])
def test_w1_export_retains_typed_outcome_after_acknowledge(monkeypatch, tmp_path, status):
    from metroliza.exporting.export_outcomes import (
        ExportArtifactResult, ExportArtifactStatus, ExportRunResult, ExportRunStatus,
    )
    dialog = _build_dialog(monkeypatch, tmp_path)
    path = tmp_path / "result.xlsx"
    path.touch()
    completed = status in {"complete", "complete_with_omissions"}
    result = ExportRunResult(ExportRunStatus(status), (ExportArtifactResult(
        "workbook", "Workbook", ExportArtifactStatus.COMPLETE if completed else ExportArtifactStatus.FAILED,
        True, str(path),
    ),), ())
    opened, revealed = [], []
    monkeypatch.setattr(export_dialog.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    monkeypatch.setattr(export_dialog, "reveal_file_in_explorer", lambda path: revealed.append(Path(path)))
    dialog.export_thread = types.SimpleNamespace(export_run_result=result, completion_metadata={})
    monkeypatch.setattr(export_dialog, "show_export_result_message", lambda *args, **kw: None)
    try:
        dialog.on_export_finished()
        row = dialog.last_result_row
        assert not row.isHidden()
        assert "Last export" in row.summary.text()
        assert {"complete": "completed", "complete_with_omissions": "completed with warnings"}.get(status, status) in row.summary.text()
        import re
        assert re.search(r"\b\d{2}:\d{2}\b", row.summary.text())
        assert bool(row.findChildren(export_dialog.QPushButton)) == completed
        assert (path.name in row.summary.text()) == completed
        for button in row.findChildren(export_dialog.QPushButton):
            button.click()
        assert [url.toLocalFile() for url in opened] == ([str(path)] if completed else [])
        assert revealed == ([path] if completed else [])
        if completed:
            warnings = []
            monkeypatch.setattr(export_dialog.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
            path.unlink()
            for button in row.findChildren(export_dialog.QPushButton):
                button.click()
            assert len(opened) == len(revealed) == 1
            assert all("was moved or deleted" in warning and str(path) in warning for warning in warnings)
            assert len(warnings) == 2
    finally:
        dialog.export_thread = None
        dialog.close()


def test_w1_local_link_opens_named_file_and_uses_basename(monkeypatch, tmp_path):
    _app()
    path = tmp_path / "work book.xlsx"
    path.touch()
    opened = []
    monkeypatch.setattr(export_dialog.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    monkeypatch.setattr(export_dialog, "reveal_file_in_explorer", lambda path: pytest.fail("link must open"))
    uri = path.resolve().as_uri()
    export_dialog.handle_export_result_link(None, uri, excel_file=path)
    assert opened[0].toLocalFile() == str(path)
    linked = export_dialog.format_message_with_clickable_links(uri)
    assert f'>{path.name}</a>' in linked
    assert f'href="{uri}"' in linked
