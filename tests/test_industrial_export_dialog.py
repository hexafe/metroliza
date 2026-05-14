from __future__ import annotations

import sys
import types

import pytest

try:
    from PyQt6.QtWidgets import QApplication

    import modules.industrial_export_dialog as industrial_export_dialog
    from modules.industrial_credentials import IndustrialStoredCredentials
    from modules.industrial_export_dialog import IndustrialExportDialog
    from modules.industrial_source_config import build_source_profile, upsert_source_profile_in_config
    from modules.industrial_workflow_state import IndustrialFilterState, IndustrialGroupingState
    from modules.industrial_workers import IndustrialLiveExportThread
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    IndustrialExportDialog = None
    IndustrialFilterState = None
    IndustrialGroupingState = None
    IndustrialLiveExportThread = None
    IndustrialStoredCredentials = None
    industrial_export_dialog = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial export dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_export_dialog_uses_csv_summary_style_readiness_and_plot_toggle(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    output_path = str(tmp_path / "industrial.xlsx")
    dialog = IndustrialExportDialog(
        db_file=db_path,
        filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
        grouping_state=IndustrialGroupingState(fields=("station",)),
        include_plots=False,
    )

    assert not dialog.start_button.isEnabled()
    assert dialog.include_plots_checkbox.text() == "Include plots"
    assert dialog.plot_status_label.text() == "Plots disabled"
    assert dialog.clear_filter_button.isEnabled()
    assert dialog.clear_grouping_button.isEnabled()

    dialog.clear_filter()
    dialog.clear_grouping()

    assert dialog.filter_state.references == ()
    assert dialog.grouping_state.fields == ()
    assert not dialog.clear_filter_button.isEnabled()
    assert not dialog.clear_grouping_button.isEnabled()

    dialog.output_file = output_path
    dialog._sync_ui_state()
    thread = dialog.create_export_thread()

    assert dialog.start_button.isEnabled()
    assert thread.output_file == output_path
    assert thread.filter_state.references == ()
    assert thread.grouping_state.fields == ()
    assert thread.include_charts is False
    dialog.close()


def test_export_dialog_has_no_live_oznak_fetch_dependency():
    assert "fetch_oznak_records_for_source_profile" not in vars(industrial_export_dialog)
    assert "create_oznak_cancellation_token" not in vars(industrial_export_dialog)


def test_export_dialog_direct_mode_loads_source_and_creates_live_thread(tmp_path):
    _app()
    config_path = tmp_path / "industrial_sources.yaml"
    output_path = tmp_path / "industrial_live.xlsx"
    upsert_source_profile_in_config(
        config_path,
        build_source_profile(
            profile_key="assembly_mes",
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "station"),
            default_pagination_column="event_id",
        ),
    )
    dialog = IndustrialExportDialog(db_file=None, config_path=config_path)

    assert dialog.live_mode is True
    assert dialog.remember_credentials_checkbox.isChecked()
    assert dialog.profile_combo.count() == 1
    assert not dialog.start_button.isEnabled()

    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("secret-password")
    dialog.output_file = str(output_path)
    dialog._sync_ui_state()
    thread = dialog.create_export_thread()

    assert dialog.start_button.isEnabled()
    assert isinstance(thread, IndustrialLiveExportThread)
    assert thread.profile.profile_key == "assembly_mes"
    assert thread.output_file == str(output_path)
    assert thread.limit == 5000
    dialog.close()


def test_export_dialog_profile_switch_replaces_stored_credentials(tmp_path, monkeypatch):
    _app()
    config_path = tmp_path / "industrial_sources.yaml"
    for profile_key, profile_name in (("assembly_mes", "Assembly MES"), ("paint_mes", "Paint MES")):
        upsert_source_profile_in_config(
            config_path,
            build_source_profile(
                profile_key=profile_key,
                profile_name=profile_name,
                source_db_alias=profile_key,
                database_type="mssql",
                host=f"{profile_key}.example.invalid",
                port=1433,
                database_name="plantdb",
                source_object_name="events",
                allowed_columns=("event_id", "station"),
                default_pagination_column="event_id",
            ),
        )
    stored_credentials = {
        "assembly_mes": IndustrialStoredCredentials(username="assembly-user", password="assembly-secret"),
        "paint_mes": IndustrialStoredCredentials(),
    }
    monkeypatch.setattr(
        industrial_export_dialog,
        "load_industrial_credentials",
        lambda profile_key: stored_credentials[profile_key],
    )

    dialog = IndustrialExportDialog(db_file=None, config_path=config_path)

    assert dialog.username_edit.text() == "assembly-user"
    assert dialog.password_edit.text() == "assembly-secret"

    dialog.profile_combo.setCurrentIndex(1)

    assert dialog.username_edit.text() == ""
    assert dialog.password_edit.text() == ""
    assert not dialog.start_button.isEnabled()
    dialog.close()


def test_export_dialog_saves_remembered_credentials_only_after_success(tmp_path, monkeypatch):
    _app()
    config_path = tmp_path / "industrial_sources.yaml"
    output_path = tmp_path / "industrial_live.xlsx"
    upsert_source_profile_in_config(
        config_path,
        build_source_profile(
            profile_key="assembly_mes",
            profile_name="Assembly MES",
            source_db_alias="assembly_mes",
            database_type="mssql",
            host="mes.example.invalid",
            port=1433,
            database_name="plantdb",
            source_object_name="events",
            allowed_columns=("event_id", "station"),
            default_pagination_column="event_id",
        ),
    )
    monkeypatch.setattr(
        industrial_export_dialog,
        "load_industrial_credentials",
        lambda _profile_key: IndustrialStoredCredentials(),
    )
    saved_credentials = []
    monkeypatch.setattr(
        industrial_export_dialog,
        "save_industrial_credentials",
        lambda profile_key, *, username, password: saved_credentials.append(
            (profile_key, username, password)
        ),
    )
    fake_export_dialog = types.SimpleNamespace(
        show_export_result_message=lambda *args, **kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "modules.export_dialog", fake_export_dialog)
    monkeypatch.setattr(industrial_export_dialog.QMessageBox, "warning", lambda *args, **kwargs: None)
    dialog = IndustrialExportDialog(db_file=None, config_path=config_path)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("secret-password")
    dialog.output_file = str(output_path)
    dialog._sync_ui_state()

    dialog.create_export_thread()

    assert saved_credentials == []
    assert dialog._pending_credentials_to_save == ("assembly_mes", "operator", "secret-password")

    dialog.on_export_error("login failed")

    assert saved_credentials == []
    assert dialog._pending_credentials_to_save is None

    dialog.create_export_thread()
    dialog.on_export_finished(
        {
            "output_file": str(output_path),
            "row_count": 3,
            "summary_rows": 2,
            "charts": True,
        }
    )

    assert saved_credentials == [("assembly_mes", "operator", "secret-password")]
    assert dialog._pending_credentials_to_save is None
    dialog.close()


def test_export_dialog_completion_uses_export_style_workbook_link(tmp_path, monkeypatch):
    _app()
    output_path = tmp_path / "industrial.xlsx"
    calls = []
    fake_export_dialog = types.SimpleNamespace(
        show_export_result_message=lambda parent, level, title, message, excel_file=None: calls.append(
            (parent, level, title, message, excel_file)
        )
    )
    monkeypatch.setitem(sys.modules, "modules.export_dialog", fake_export_dialog)
    dialog = IndustrialExportDialog(db_file=str(tmp_path / "industrial.db"))

    dialog.on_export_finished(
        {
            "output_file": str(output_path),
            "row_count": 3,
            "summary_rows": 2,
            "charts": True,
        }
    )

    assert calls == [
        (
            dialog,
            "info",
            "Industrial export complete",
            (
                "Industrial export complete.\n\n"
                f"Industrial workbook: {output_path.resolve().as_uri()}\n\n"
                "Rows: 3\n"
                "Summary rows: 2"
            ),
            str(output_path),
        )
    ]
    dialog.close()
