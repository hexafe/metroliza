from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QComboBox, QMessageBox, QWidget  # noqa: F401

    from modules import industrial_data_dialog
    from modules import industrial_source_profiles_dialog
    from modules import industrial_workers
    from modules.industrial_data_dialog import (
        IndustrialDataDialog,
    )
    from modules.industrial_export_dialog import IndustrialExportDialog
    from modules.industrial_source_profiles_dialog import IndustrialSourceProfilesDialog
    from modules.industrial_sync_dialog import IndustrialSyncDialog
    from modules.industrial_workers import IndustrialOznakSyncThread
    from modules.industrial_workflow_state import (
        IndustrialFilterState,
        IndustrialGroupingState,
        parse_reference_values,
    )
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    industrial_data_dialog = None
    industrial_source_profiles_dialog = None
    industrial_workers = None
    IndustrialDataDialog = None
    IndustrialExportDialog = None
    IndustrialSourceProfilesDialog = None
    IndustrialSyncDialog = None
    IndustrialOznakSyncThread = None
    IndustrialFilterState = None
    IndustrialGroupingState = None
    parse_reference_values = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None
from modules.industrial_data_repository import IndustrialDataRepository
from modules.db import sqlite_connection_scope
from modules.industrial_source_config import build_source_profile, upsert_source_profile_in_config
from modules.oznak_adapter import OznakAdapterFetchResult, OznakAdapterStatus


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _populate_industrial_cache(database: str) -> None:
    repository = IndustrialDataRepository(database)
    profile = repository.upsert_source_profile(
        profile_key="line_a",
        profile_name="Line A",
        source_db_alias="line_a",
        database_type="sqlite",
        source_object_name="events",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=({"source_record_key": "row-1", "measurement": 12.5},),
    )


def test_dialog_saves_non_secret_source_metadata_without_credentials(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    config_path = tmp_path / "industrial_sources.yaml"
    dialog = IndustrialSourceProfilesDialog(db_file=db_path, config_path=config_path)

    dialog.source_name_edit.setText("Assembly MES")
    dialog.alias_edit.setText("assembly_mes")
    dialog.host_edit.setText("mes.example.invalid")
    dialog.port_spin.setValue(1433)
    dialog.database_edit.setText("plantdb")
    dialog.table_edit.setText("events")
    dialog.columns_edit.setText("event_id, event_at, reference, station")
    dialog.record_key_edit.setText("event_id")
    dialog.timestamp_column_edit.setText("event_at")
    dialog.order_by_checkbox.setChecked(False)

    dialog.save_source()
    profiles = IndustrialDataRepository(db_path).list_source_profiles(include_disabled=True)

    assert len(profiles) == 1
    assert profiles[0].profile_key == "assembly_mes"
    assert profiles[0].host == "mes.example.invalid"
    assert profiles[0].port == 1433
    assert profiles[0].database_name == "plantdb"
    assert profiles[0].source_object_name == "events"
    assert profiles[0].allowed_columns == ("event_id", "event_at", "reference", "station")
    assert profiles[0].order_by_enabled is False
    assert "assembly_mes:" in config_path.read_text(encoding="utf-8")
    assert "order_by_enabled: false" in config_path.read_text(encoding="utf-8")
    assert not hasattr(dialog, "password_edit")
    dialog.close()


def test_source_dialog_saves_copy_pasted_csv_header_columns(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    config_path = tmp_path / "industrial_sources.yaml"
    dialog = IndustrialSourceProfilesDialog(db_file=db_path, config_path=config_path)

    dialog.source_name_edit.setText("Assembly MES")
    dialog.alias_edit.setText("assembly_mes")
    dialog.host_edit.setText("mes.example.invalid")
    dialog.database_edit.setText("plantdb")
    dialog.table_edit.setText("events")
    dialog.columns_edit.setText('"TimeStamp","OP100RetestNumber3"')

    dialog.save_source()
    profiles = IndustrialDataRepository(db_path).list_source_profiles(include_disabled=True)

    assert profiles[0].allowed_columns == ("TimeStamp", "OP100RetestNumber3")
    assert "allowed_columns:" in config_path.read_text(encoding="utf-8")
    dialog.close()


@pytest.mark.parametrize("columns_text", ["", "   ", "*"])
def test_source_dialog_keeps_empty_or_star_columns_unrestricted(tmp_path, columns_text):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    config_path = tmp_path / "industrial_sources.yaml"
    dialog = IndustrialSourceProfilesDialog(db_file=db_path, config_path=config_path)

    dialog.source_name_edit.setText("Assembly MES")
    dialog.alias_edit.setText("assembly_mes")
    dialog.host_edit.setText("mes.example.invalid")
    dialog.database_edit.setText("plantdb")
    dialog.table_edit.setText("events")
    dialog.columns_edit.setText(columns_text)
    dialog.record_key_edit.setText("OP100RetestNumber3")
    dialog.timestamp_column_edit.setText("TimeStamp")

    dialog.save_source()
    profiles = IndustrialDataRepository(db_path).list_source_profiles(include_disabled=True)

    assert profiles[0].allowed_columns == ()
    assert "allowed_columns" not in config_path.read_text(encoding="utf-8")
    dialog.close()


def test_source_dialog_can_configure_file_before_metroliza_database_is_selected(tmp_path):
    _app()
    config_path = tmp_path / "industrial_sources.yaml"
    dialog = IndustrialSourceProfilesDialog(db_file=None, config_path=config_path)

    dialog.source_name_edit.setText("Assembly MES")
    dialog.alias_edit.setText("assembly_mes")
    dialog.host_edit.setText("mes.example.invalid")
    dialog.database_edit.setText("plantdb")
    dialog.table_edit.setText("events")
    dialog.columns_edit.setText("event_id, station")
    dialog.record_key_edit.setText("event_id")

    dialog.save_source()

    assert config_path.exists()
    config_text = config_path.read_text(encoding="utf-8")
    assert "assembly_mes:" in config_text
    assert "reference" not in config_text
    assert "order_by_enabled" not in config_text
    assert "password" not in config_text.lower()
    assert "Fetch to CSV Summary" in dialog.status_label.text()
    assert "local cache" in dialog.status_label.text()
    dialog.close()


def test_source_dialog_form_helpers_and_config_browse(monkeypatch, tmp_path):
    _app()
    selected_path = tmp_path / "plant_sources"
    monkeypatch.setattr(
        industrial_source_profiles_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(selected_path), "YAML config (*.yaml *.yml)"),
    )
    dialog = IndustrialSourceProfilesDialog(db_file=None, config_path=tmp_path / "initial.yaml")

    dialog.browse_config_file()
    dialog.source_name_edit.setText("123 Assembly MES")
    dialog.alias_edit.clear()
    dialog.db_type_combo.setCurrentIndex(dialog.db_type_combo.findData("mysql"))
    dialog.host_edit.setText("mes.example.invalid")
    dialog.database_edit.setText("plantdb")
    dialog.table_edit.setText("events")
    dialog.columns_edit.setText("reference, station")
    dialog.record_key_edit.setText("event_id")
    dialog.timestamp_column_edit.setText("event_at")
    profile = dialog.profile_from_form()

    assert dialog.config_path == selected_path.with_suffix(".yaml")
    assert dialog.port_spin.value() == 3306
    assert profile.profile_key == "source_123_assembly_mes"
    assert profile.allowed_columns == ("reference", "station", "event_id", "event_at")

    dialog.clear_form()

    assert dialog.source_name_edit.text() == ""
    assert dialog.order_by_checkbox.isChecked()
    assert "New production source" in dialog.status_label.text()
    dialog.close()


@pytest.mark.parametrize("exit_action", ("reject", "escape", "close", "close_button"))
def test_source_dialog_guards_unsaved_draft_on_every_native_exit(
    monkeypatch,
    tmp_path,
    exit_action,
):
    app = _app()
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: answers.pop(0),
    )
    dialog = IndustrialSourceProfilesDialog(
        db_file=None,
        config_path=tmp_path / "industrial_sources.yaml",
    )
    dialog.show()
    app.processEvents()
    dialog.source_name_edit.setText("Unsaved production source")

    def request_exit():
        if exit_action == "reject":
            dialog.reject()
        elif exit_action == "escape":
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        elif exit_action == "close_button":
            dialog.close_button.click()
        else:
            dialog.close()
        app.processEvents()

    request_exit()

    assert dialog.isVisible()
    assert dialog.source_name_edit.text() == "Unsaved production source"

    request_exit()

    assert not dialog.isVisible()
    assert dialog.source_name_edit.text() == ""
    assert answers == []


def test_sync_thread_upserts_rows_and_finishes_sync_run(monkeypatch, tmp_path):
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        allowed_columns=("event_id", "reference", "station"),
        default_pagination_column="event_id",
    )

    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=(
            {
                "source_primary_key": "ROW-1",
                "reference": "REF-1",
                "station": "S1",
                "raw_record": {"event_id": "ROW-1", "reference": "REF-1", "station": "S1"},
            },
        ),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )

    monkeypatch.setattr(
        industrial_workers,
        "get_oznak_adapter_status",
        lambda: status,
    )
    monkeypatch.setattr(
        industrial_workers,
        "create_oznak_cancellation_token",
        lambda: SimpleNamespace(cancel=lambda: None),
    )
    monkeypatch.setattr(
        industrial_workers,
        "fetch_oznak_records_for_source_profile",
        lambda *args, **kwargs: result,
    )
    monkeypatch.setattr(
        industrial_workers,
        "materialize_industrial_report_links",
        lambda _db: SimpleNamespace(accepted_links=0, ambiguous_reports=0, unmatched_reports=0),
    )

    thread = IndustrialOznakSyncThread(
        db_file=db_path,
        profile=profile,
        username="operator",
        password="secret-password",
        limit=50,
        timeout_seconds=30,
        reference_filter_column="reference",
        reference_values=("REF-1",),
        test_only=False,
    )
    emitted = []
    thread.result_ready.connect(emitted.append)

    thread.run()
    counts = repository.summarize_counts(source_profile_id=profile.id)

    assert emitted
    assert emitted[0]["status"] == "succeeded"
    assert emitted[0]["row_count"] == 1
    assert emitted[0]["upsert_summary"]["processed"] == 1
    assert counts.sync_runs == 1
    assert counts.records == 1


def test_sync_thread_test_only_does_not_persist_rows(monkeypatch, tmp_path):
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=({"source_primary_key": "ROW-1", "raw_record": {"event_id": "ROW-1"}},),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )
    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(
        industrial_workers,
        "create_oznak_cancellation_token",
        lambda: SimpleNamespace(cancel=lambda: None),
    )
    fetch_kwargs = {}

    def fake_fetch(*args, **kwargs):
        fetch_kwargs.update(kwargs)
        return result

    monkeypatch.setattr(industrial_workers, "fetch_oznak_records_for_source_profile", fake_fetch)

    thread = IndustrialOznakSyncThread(
        db_file=db_path,
        profile=profile,
        username="operator",
        password="secret-password",
        limit=50,
        timeout_seconds=30,
        reference_filter_column=None,
        reference_values=(),
        test_only=True,
    )
    emitted = []
    thread.result_ready.connect(emitted.append)

    thread.run()
    counts = repository.summarize_counts(source_profile_id=profile.id)

    assert emitted[0]["status"] == "succeeded"
    assert emitted[0]["test_only"] is True
    assert emitted[0]["access_check_method"] == "bounded_fetch"
    assert fetch_kwargs["limit"] == 1
    assert counts.sync_runs == 0
    assert counts.records == 0


def test_sync_thread_records_sanitized_failed_sync_run(monkeypatch, tmp_path):
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=(),
        row_count=0,
        implemented=True,
        diagnostics={"stage": "fetch_call"},
        error="database rejected password=super-secret",
    )
    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(industrial_workers, "create_oznak_cancellation_token", lambda: None)
    monkeypatch.setattr(
        industrial_workers,
        "fetch_oznak_records_for_source_profile",
        lambda *args, **kwargs: result,
    )

    thread = IndustrialOznakSyncThread(
        db_file=db_path,
        profile=profile,
        username="operator",
        password="secret-password",
        limit=50,
        timeout_seconds=30,
        reference_filter_column="reference",
        reference_values=("REF-1",),
        test_only=False,
    )
    emitted = []
    thread.result_ready.connect(emitted.append)

    thread.run()

    assert emitted[0]["status"] == "failed"
    assert emitted[0]["error"] == "database rejected password=<redacted>"
    with sqlite_connection_scope(db_path) as conn:
        status_row = conn.execute(
            "SELECT status, error_summary FROM industrial_sync_runs"
        ).fetchone()
    assert status_row == ("failed", "database rejected password=<redacted>")


def test_sync_thread_reports_partial_success_as_completed_with_warnings(monkeypatch, tmp_path):
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=({"source_primary_key": "ROW-1", "raw_record": {"event_id": "ROW-1"}},),
        row_count=1,
        implemented=True,
        diagnostics={
            "stage": "mapped",
            "partial_success": True,
            "completed_with_warnings": True,
            "warnings": ("secondary source timed out password=<redacted>",),
        },
    )
    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(industrial_workers, "create_oznak_cancellation_token", lambda: None)
    monkeypatch.setattr(
        industrial_workers,
        "fetch_oznak_records_for_source_profile",
        lambda *args, **kwargs: result,
    )
    monkeypatch.setattr(
        industrial_workers,
        "materialize_industrial_report_links",
        lambda _db: SimpleNamespace(accepted_links=0, ambiguous_reports=0, unmatched_reports=0),
    )

    thread = IndustrialOznakSyncThread(
        db_file=db_path,
        profile=profile,
        username="operator",
        password="secret-password",
        limit=50,
        timeout_seconds=30,
        reference_filter_column="reference",
        reference_values=("REF-1",),
        test_only=False,
    )
    emitted = []
    thread.result_ready.connect(emitted.append)

    thread.run()

    assert emitted[0]["status"] == "completed_with_warnings"
    assert emitted[0]["error"] == "secondary source timed out password=<redacted>"
    assert emitted[0]["upsert_summary"]["processed"] == 1
    with sqlite_connection_scope(db_path) as conn:
        status_row = conn.execute(
            "SELECT status, error_summary FROM industrial_sync_runs"
        ).fetchone()
    assert status_row == ("completed_with_warnings", "secondary source timed out password=<redacted>")


def test_sync_thread_records_cancelled_run_without_upserting_rows(monkeypatch, tmp_path):
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    status = OznakAdapterStatus(available=True, version="0.1.0", fetch_available=True)
    result = OznakAdapterFetchResult(
        status=status,
        records=({"source_primary_key": "ROW-1", "raw_record": {"event_id": "ROW-1"}},),
        row_count=1,
        implemented=True,
        diagnostics={"stage": "mapped"},
    )
    monkeypatch.setattr(industrial_workers, "get_oznak_adapter_status", lambda: status)
    monkeypatch.setattr(industrial_workers, "create_oznak_cancellation_token", lambda: None)
    monkeypatch.setattr(
        industrial_workers,
        "fetch_oznak_records_for_source_profile",
        lambda *args, **kwargs: result,
    )

    thread = IndustrialOznakSyncThread(
        db_file=db_path,
        profile=profile,
        username="operator",
        password="secret-password",
        limit=50,
        timeout_seconds=30,
        reference_filter_column="reference",
        reference_values=("REF-1",),
        test_only=False,
    )
    emitted = []
    thread.result_ready.connect(emitted.append)
    thread.cancel()

    thread.run()
    counts = repository.summarize_counts(source_profile_id=profile.id)

    assert emitted[0]["status"] == "cancelled"
    assert emitted[0]["error"] == "Sync cancelled by user."
    assert counts.records == 0
    with sqlite_connection_scope(db_path) as conn:
        status_row = conn.execute(
            "SELECT status, error_summary FROM industrial_sync_runs"
        ).fetchone()
    assert status_row == ("cancelled", "Sync cancelled by user.")


def test_dialog_requires_reference_scope_for_sync_but_not_connection_test(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    dialog = IndustrialDataDialog(db_file=db_path)

    with pytest.raises(ValueError, match="at least one reference"):
        dialog.sync_filter_state.validate_for_sync()
    dialog.set_sync_filter_state(
        IndustrialFilterState(reference_column="reference", references=("REF-1",))
    )
    dialog.sync_filter_state.validate_for_sync()
    dialog.close()


def test_launcher_dialog_keeps_connection_fields_out_of_main_surface(tmp_path):
    _app()
    dialog = IndustrialDataDialog(db_file=str(tmp_path / "metroliza.db"))

    assert not hasattr(dialog, "source_name_edit")
    assert not hasattr(dialog, "password_edit")
    assert dialog.use_temp_button.text() == "Temp"
    assert dialog.select_database_button.text() == "Open..."
    assert dialog.create_database_button.text() == "Create..."
    assert dialog.sources_button.text() == "Production sources..."
    assert dialog.sync_button.text() == "Fetch to cache..."
    assert "Fetch rows" in dialog.sync_button.toolTip()
    assert dialog.links_button.text() == "Production links..."
    assert dialog.export_button.text() == "Export workbook..."
    assert dialog.analyze_button.text() == "CSV Summary..."
    assert dialog.diagnostics_button.text() == "Diagnostics..."
    assert dialog.initialize_button.isHidden()
    assert "Source -> Access -> Cache -> CSV Summary" in dialog.workflow_label.text()
    assert "Last sync/cache outcome" in dialog.sync_summary_label.text()
    # The persistent lifecycle/status rows are part of the safety contract;
    # keep the launcher compact enough for a 720 px working area without
    # forcing those rows into overlays or transient messages.
    assert dialog.sizeHint().height() <= 640
    dialog.close()


def test_sync_dialog_labels_bounded_access_check_clearly(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        allowed_columns=("event_id", "reference"),
    )

    dialog = IndustrialSyncDialog(db_file=db_path)

    assert dialog.test_connection_button.text() == "Check access"
    assert "one production row" in dialog.test_connection_button.toolTip()
    assert dialog.sync_now_button.text() == "Fetch to cache"
    assert "saves them in the local industrial cache" in dialog.sync_now_button.toolTip()
    assert dialog.edit_filter_button.text() == "Edit filters..."
    dialog.close()


def test_launcher_analytics_uses_csv_summary_tabular_cache_workflow(monkeypatch, tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
    )
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=({"source_record_key": "row-1", "reference": "REF-1", "length_mm": "12.5"},),
    )
    launched = {}

    class FakeAnalyticsDialog:
        def __init__(
            self,
            parent,
            *,
            db_file,
            source_kind,
            tabular_load_result=None,
            input_file=None,
            source_label_override=None,
            presentation_mode=None,
        ):
            launched["parent"] = parent
            launched["db_file"] = db_file
            launched["source_kind"] = source_kind
            launched["tabular_load_result"] = tabular_load_result
            launched["input_file"] = input_file
            launched["source_label_override"] = source_label_override
            launched["presentation_mode"] = presentation_mode
            self.executed = False

        def exec(self):
            launched["executed"] = True

    monkeypatch.setattr(industrial_data_dialog, "IndustrialAnalyticsDialog", FakeAnalyticsDialog)
    dialog = IndustrialDataDialog(db_file=db_path)
    source_index = dialog.analysis_source_combo.findData(profile.id)
    assert source_index >= 0
    dialog.analysis_source_combo.setCurrentIndex(source_index)

    dialog.open_analytics_dialog()

    assert launched["parent"] is dialog
    assert launched["db_file"] == db_path
    assert launched["source_kind"] == "tabular_file"
    assert launched["tabular_load_result"].row_count == 1
    assert launched["input_file"] == db_path
    assert launched["presentation_mode"] == "industrial_cache"
    assert "Industrial cache for CSV Summary" in launched["source_label_override"]
    assert "Assembly MES" in launched["source_label_override"]
    assert launched["executed"] is True
    dialog.close()


def test_launcher_keeps_source_configuration_available_without_database(tmp_path):
    _app()
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = tmp_path / "industrial_sources.yaml"
    dialog.refresh_status()
    cache_path = Path(dialog.db_file)

    assert dialog.sources_button.isEnabled()
    assert dialog.sync_button.isEnabled()
    assert not dialog.links_button.isEnabled()
    assert dialog.export_button.isEnabled()
    assert dialog.initialize_button.isEnabled()
    assert not dialog.analysis_source_combo.isEnabled()
    assert "needs fetched rows" in dialog.analytics_status_label.text()
    assert dialog.select_database_button.isEnabled()
    assert dialog.create_database_button.isEnabled()
    assert dialog.report_db_file is None
    assert "Temporary cache" in dialog.database_field.text()
    assert cache_path.exists()
    dialog.close()
    assert not cache_path.exists()


def test_launcher_keeps_cache_actions_enabled_when_source_config_exists_without_database(tmp_path):
    _app()
    config_path = tmp_path / "industrial_sources.yaml"
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
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = config_path
    dialog.refresh_status()

    assert dialog.sources_button.isEnabled()
    assert dialog.export_button.isEnabled()
    assert dialog.sync_button.isEnabled()
    assert not dialog.links_button.isEnabled()
    assert dialog.initialize_button.isEnabled()
    assert not dialog.refresh_links_button.isEnabled()
    assert dialog.analyze_button.isEnabled()
    assert not dialog.analysis_source_combo.isEnabled()
    assert "needs fetched rows" in dialog.analytics_status_label.text()
    assert "Fetch selected production rows" in dialog.status_label.text()
    dialog.close()


def test_launcher_fetch_uses_temporary_cache_without_metroliza_database(monkeypatch, tmp_path):
    _app()
    launched = {}
    warnings = []

    class FakeSyncDialog:
        def __init__(
            self,
            parent,
            *,
            db_file,
            report_db_file,
            config_path,
            access_only,
            filter_state,
        ):
            launched["parent"] = parent
            launched["db_file"] = db_file
            launched["report_db_file"] = report_db_file
            launched["config_path"] = config_path
            launched["access_only"] = access_only
            launched["filter_state"] = filter_state

        def exec(self):
            launched["executed"] = True

    monkeypatch.setattr(industrial_data_dialog, "IndustrialSyncDialog", FakeSyncDialog)
    monkeypatch.setattr(industrial_data_dialog.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = tmp_path / "industrial_sources.yaml"
    temp_cache = dialog.db_file

    dialog.open_sync_dialog()

    assert launched["parent"] is dialog
    assert launched["db_file"] == temp_cache
    assert launched["report_db_file"] is None
    assert launched["access_only"] is False
    assert warnings == []
    dialog.close()


def test_launcher_export_uses_temporary_cache_without_metroliza_database(monkeypatch, tmp_path):
    _app()
    launched = {}
    warnings = []

    class FakeExportDialog:
        def __init__(
            self,
            parent,
            *,
            db_file,
            report_db_file,
            filter_state,
            grouping_state,
            include_plots,
            config_path,
        ):
            launched["parent"] = parent
            launched["db_file"] = db_file
            launched["report_db_file"] = report_db_file
            launched["config_path"] = config_path
            launched["filter_state"] = filter_state
            launched["grouping_state"] = grouping_state
            launched["include_plots"] = include_plots

        def exec(self):
            launched["executed"] = True

    monkeypatch.setattr(industrial_data_dialog, "IndustrialExportDialog", FakeExportDialog)
    monkeypatch.setattr(industrial_data_dialog.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = tmp_path / "industrial_sources.yaml"
    temp_cache = dialog.db_file

    dialog.open_export_dialog()

    assert launched["parent"] is dialog
    assert launched["db_file"] == temp_cache
    assert launched["report_db_file"] is None
    assert warnings == []
    dialog.close()


def test_launcher_can_select_metroliza_database_and_enable_oznak_actions(monkeypatch, tmp_path):
    _app()
    db_path = tmp_path / "metroliza.db"

    class ParentWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.selected_db_file = None

        def set_db_file(self, db_file):
            self.selected_db_file = db_file

    parent = ParentWindow()
    dialog = IndustrialDataDialog(parent=parent, db_file=None)
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(db_path), "SQLite database (*.db *.sqlite *.sqlite3)"),
    )

    dialog.select_database_file()

    assert parent.selected_db_file == str(db_path)
    assert dialog.db_file == str(db_path)
    assert dialog.sync_button.isEnabled()
    assert dialog.initialize_button.isEnabled()
    assert dialog.links_button.isEnabled()
    assert dialog.export_button.isEnabled()
    assert "Industrial cache empty" in dialog.status_label.text()
    assert "needs fetched rows" in dialog.analytics_status_label.text()
    dialog.close()
    parent.close()


def test_launcher_can_create_persistent_industrial_cache_without_report_context(monkeypatch, tmp_path):
    _app()
    db_path = tmp_path / "industrial_cache.sqlite"

    class ParentWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.selected_db_file = None

        def set_db_file(self, db_file):
            self.selected_db_file = db_file

    parent = ParentWindow()
    dialog = IndustrialDataDialog(parent=parent, db_file=None)
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(db_path), "SQLite database (*.db *.sqlite *.sqlite3)"),
    )
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a new final path must not request overwrite confirmation")
        ),
    )

    dialog.create_database_file()

    assert parent.selected_db_file is None
    assert dialog.db_file == str(db_path)
    assert dialog.report_db_file is None
    assert dialog.sync_button.isEnabled()
    assert dialog.export_button.isEnabled()
    assert dialog.initialize_button.isEnabled()
    assert not dialog.links_button.isEnabled()
    assert not dialog.refresh_links_button.isEnabled()
    with sqlite_connection_scope(str(db_path)) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert "industrial_records" in tables
    assert "report_metadata" not in tables
    dialog.close()
    parent.close()


@pytest.mark.parametrize(
    "response_name",
    ("No", "Cancel"),
)
def test_launcher_confirms_extension_normalized_existing_destination(
    monkeypatch,
    tmp_path,
    response_name,
):
    _app()
    selected_path = tmp_path / "existing-cache"
    destination = selected_path.with_suffix(".db")
    with sqlite_connection_scope(str(destination)) as connection:
        connection.execute("CREATE TABLE unrelated_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated_marker VALUES ('preserve-me')")
        connection.commit()
    original = destination.read_bytes()
    confirmations = []
    warnings = []
    response = getattr(QMessageBox.StandardButton, response_name)
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(selected_path), "SQLite database (*.db *.sqlite *.sqlite3)"),
    )
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda _parent, title, message, *args, **kwargs: (
            confirmations.append((str(title), str(message), args)) or response
        ),
    )
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "warning",
        lambda _parent, title, message, *args, **kwargs: warnings.append(
            (str(title), str(message))
        ),
    )
    dialog = IndustrialDataDialog(db_file=None)
    temporary_path = Path(dialog.db_file)
    try:
        dialog.create_database_file()

        assert dialog.cache_target.is_temporary
        assert dialog.db_file == str(temporary_path)
        assert temporary_path.exists()
        assert destination.read_bytes() == original
        assert len(confirmations) == 1
        assert warnings == []
        assert str(destination.resolve()) in confirmations[0][1]
        assert "permanently lost" in confirmations[0][1]
        buttons, default = confirmations[0][2]
        assert buttons & QMessageBox.StandardButton.Yes
        assert buttons & QMessageBox.StandardButton.No
        assert buttons & QMessageBox.StandardButton.Cancel
        assert default == QMessageBox.StandardButton.No
        with sqlite_connection_scope(str(destination)) as connection:
            marker = connection.execute(
                "SELECT value FROM unrelated_marker"
            ).fetchone()[0]
        assert marker == "preserve-me"
    finally:
        monkeypatch.setattr(
            industrial_data_dialog.QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()


def test_launcher_accepts_exact_extension_normalized_overwrite_after_publication(
    monkeypatch,
    tmp_path,
):
    _app()
    selected_path = tmp_path / "accepted-cache"
    destination = selected_path.with_suffix(".db")
    with sqlite_connection_scope(str(destination)) as connection:
        connection.execute("CREATE TABLE unrelated_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated_marker VALUES ('replace-me')")
        connection.commit()
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(selected_path), "SQLite database (*.db *.sqlite *.sqlite3)"),
    )
    confirmations = []
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda _parent, _title, message, *args, **kwargs: (
            confirmations.append(str(message)) or QMessageBox.StandardButton.Yes
        ),
    )
    real_persist = industrial_data_dialog.persist_temporary_industrial_cache
    authorizations = []

    def observed_persist(target, final_destination, **kwargs):
        authorizations.append(kwargs.get("overwrite_authorization"))
        return real_persist(target, final_destination, **kwargs)

    monkeypatch.setattr(
        industrial_data_dialog,
        "persist_temporary_industrial_cache",
        observed_persist,
    )
    real_cleanup = industrial_data_dialog.cleanup_temporary_industrial_cache
    publication_observations = []

    def observed_cleanup(target):
        if (
            target is not None
            and target.is_temporary
            and Path(target.cache_db_file).exists()
            and destination.exists()
        ):
            with sqlite_connection_scope(str(destination)) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            publication_observations.append(
                (
                    integrity,
                    IndustrialDataRepository(str(destination)).summarize_counts().records,
                )
            )
        real_cleanup(target)

    monkeypatch.setattr(
        industrial_data_dialog,
        "cleanup_temporary_industrial_cache",
        observed_cleanup,
    )
    dialog = IndustrialDataDialog(db_file=None)
    source = Path(dialog.db_file)
    _populate_industrial_cache(dialog.db_file)
    try:
        dialog.create_database_file()

        assert dialog.cache_target.is_temporary is False
        assert dialog.db_file == str(destination.resolve())
        assert not source.exists()
        assert len(authorizations) == 1
        assert authorizations[0] is not None
        assert not isinstance(authorizations[0], (bool, str, Path))
        assert publication_observations == [("ok", 1)]
        assert str(destination.resolve()) in confirmations[0]
        with sqlite_connection_scope(str(destination)) as connection:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'unrelated_marker'"
            ).fetchone() is None
    finally:
        dialog.close()


@pytest.mark.parametrize(
    "overwrite_response_name",
    ("No", "Cancel"),
)
def test_save_before_discard_decline_keeps_temporary_cache_and_destination(
    monkeypatch,
    tmp_path,
    overwrite_response_name,
):
    _app()
    destination = tmp_path / "existing.db"
    with sqlite_connection_scope(str(destination)) as connection:
        connection.execute("CREATE TABLE unrelated_marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO unrelated_marker VALUES ('preserve-me')")
        connection.commit()
    original = destination.read_bytes()
    dialog = IndustrialDataDialog(db_file=None)
    source = Path(dialog.db_file)
    _populate_industrial_cache(dialog.db_file)
    overwrite_response = getattr(QMessageBox.StandardButton, overwrite_response_name)
    answers = iter((QMessageBox.StandardButton.Save, overwrite_response))
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "SQLite database"),
    )
    try:
        assert dialog._resolve_temporary_cache_before_discard(dialog.cache_target) is False
        assert source.exists()
        assert dialog.cache_target.is_temporary
        assert destination.read_bytes() == original
    finally:
        monkeypatch.setattr(
            industrial_data_dialog.QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()


def test_save_before_discard_accepts_overwrite_without_deleting_temporary_cache(
    monkeypatch,
    tmp_path,
):
    _app()
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"replace after explicit confirmation")
    dialog = IndustrialDataDialog(db_file=None)
    source = Path(dialog.db_file)
    _populate_industrial_cache(dialog.db_file)
    answers = iter((QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda *args, **kwargs: next(answers),
    )
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "SQLite database"),
    )
    try:
        assert dialog._resolve_temporary_cache_before_discard(dialog.cache_target) is True
        assert source.exists()
        assert dialog.cache_target.is_temporary
        assert IndustrialDataRepository(str(destination)).summarize_counts().records == 1
    finally:
        monkeypatch.setattr(
            industrial_data_dialog.QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()


def test_save_before_discard_picker_cancel_keeps_temporary_cache(
    monkeypatch,
):
    _app()
    dialog = IndustrialDataDialog(db_file=None)
    source = Path(dialog.db_file)
    _populate_industrial_cache(dialog.db_file)
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Save,
    )
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: ("", "SQLite database"),
    )
    try:
        assert dialog._resolve_temporary_cache_before_discard(dialog.cache_target) is False
        assert source.exists()
        assert dialog.cache_target.is_temporary
    finally:
        monkeypatch.setattr(
            industrial_data_dialog.QMessageBox,
            "question",
            lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
        )
        dialog.close()


def test_non_temporary_create_path_uses_protected_publisher_for_destination_race(
    monkeypatch,
    tmp_path,
):
    _app()
    active = tmp_path / "active.db"
    IndustrialDataRepository(str(active)).ensure_schema()
    destination = tmp_path / "raced.db"
    raced_bytes = b"appeared after the UI existence check"
    dialog = IndustrialDataDialog(db_file=str(active))
    monkeypatch.setattr(
        industrial_data_dialog.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "SQLite database"),
    )
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "question",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("the destination did not exist at confirmation time")
        ),
    )
    warnings = []
    monkeypatch.setattr(
        industrial_data_dialog.QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )
    real_persist = industrial_data_dialog.persist_temporary_industrial_cache

    def raced_persist(target, final_destination, **kwargs):
        destination.write_bytes(raced_bytes)
        return real_persist(target, final_destination, **kwargs)

    monkeypatch.setattr(
        industrial_data_dialog,
        "persist_temporary_industrial_cache",
        raced_persist,
    )
    try:
        dialog.create_database_file()

        assert dialog.db_file == str(active)
        assert dialog.cache_target.is_temporary is False
        assert destination.read_bytes() == raced_bytes
        assert warnings and "already exists" in warnings[0]
    finally:
        dialog.close()


def test_launcher_initializes_cache_and_opens_owned_child_dialogs(monkeypatch, tmp_path):
    _app()
    opened = []

    class FakeSourcesDialog:
        def __init__(self, parent, *, db_file, config_path):
            opened.append(("sources", parent, db_file, config_path))
            self.config_path = tmp_path / "new_sources.yaml"

        def exec(self):
            opened.append(("sources_exec",))

    class FakeLinkingDialog:
        def __init__(self, parent, *, db_file):
            opened.append(("links", parent, db_file))

        def exec(self):
            opened.append(("links_exec",))

    monkeypatch.setattr(industrial_data_dialog, "IndustrialSourceProfilesDialog", FakeSourcesDialog)
    monkeypatch.setattr(industrial_data_dialog, "IndustrialLinkingDialog", FakeLinkingDialog)
    db_path = str(tmp_path / "metroliza.db")
    dialog = IndustrialDataDialog(db_file=None)
    initial_config_path = dialog.config_path

    dialog.initialize_cache()
    dialog.update_db_file(db_path)
    dialog.initialize_cache()
    dialog.open_sources_dialog()
    dialog.open_links_dialog()

    assert "Industrial cache empty" in dialog.status_label.text()
    assert opened[0] == ("sources", dialog, db_path, initial_config_path)
    assert opened[1] == ("sources_exec",)
    assert dialog.config_path == tmp_path / "new_sources.yaml"
    assert opened[2] == ("links", dialog, db_path)
    assert opened[3] == ("links_exec",)
    dialog.close()


def test_launcher_refresh_links_thread_states(monkeypatch, tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    next_db_path = str(tmp_path / "next-metroliza.db")
    started = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

    class FakeLinkRefreshThread:
        def __init__(self, db_file):
            self.db_file = db_file
            self.summary_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            started.append(self)

        def start(self):
            self.started = True

        def isRunning(self):
            return False

    monkeypatch.setattr(industrial_data_dialog, "IndustrialLinkRefreshThread", FakeLinkRefreshThread)
    warnings = []
    monkeypatch.setattr(industrial_data_dialog.QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog = IndustrialDataDialog(db_file=db_path)

    dialog.refresh_links()
    assert started[0].db_file == db_path
    assert started[0].started is True
    assert not dialog.initialize_button.isEnabled()
    assert not dialog.select_database_button.isEnabled()
    assert not dialog.create_database_button.isEnabled()
    assert not dialog.use_temp_button.isEnabled()

    assert dialog.update_db_file(next_db_path) is False
    assert dialog.db_file == db_path
    assert dialog.report_db_file == db_path

    dialog.use_temporary_cache()
    assert dialog.db_file == db_path
    assert dialog.report_db_file == db_path
    assert "finish before changing storage" in dialog.status_label.text()

    summary = SimpleNamespace(accepted_links=2, ambiguous_reports=1, unmatched_reports=3)
    dialog.on_link_refresh_finished(summary)
    assert "2 accepted, 1 ambiguous, 3 unmatched" in dialog.status_label.text()
    assert not dialog.select_database_button.isEnabled()

    dialog.on_link_refresh_error("boom")
    assert "Could not refresh links: boom" in warnings[0][2]
    assert not dialog.select_database_button.isEnabled()

    dialog.on_link_refresh_thread_stopped()
    assert dialog.link_refresh_thread is None
    assert dialog.initialize_button.isEnabled()
    assert dialog.select_database_button.isEnabled()
    assert dialog.update_db_file(next_db_path) is True
    assert dialog.db_file == next_db_path
    dialog.close()


def test_launcher_reports_ready_state_when_cache_has_synced_rows(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    repository.upsert_industrial_records_from_rows(
        source_profile_id=profile.id,
        source_db_alias=profile.source_db_alias,
        rows=({"source_primary_key": "ROW-1", "raw_record": {"event_id": "ROW-1"}},),
        sync_run_id=sync_run_id,
    )
    repository.finish_sync_run(sync_run_id=sync_run_id, status="succeeded", row_count=1)

    dialog = IndustrialDataDialog(db_file=db_path)

    assert "Industrial cache ready" in dialog.status_label.text()
    assert "CSV Summary ready" in dialog.analytics_status_label.text()
    assert "Source -> Access -> Cache -> CSV Summary" in dialog.workflow_label.text()
    assert "Source: 1 configured" in dialog.workflow_label.text()
    assert "Access: last passed" in dialog.workflow_label.text()
    assert "Cache: 1 row" in dialog.workflow_label.text()
    assert "CSV Summary: ready" in dialog.workflow_label.text()
    assert "Last sync/cache outcome: Assembly MES succeeded, 1 row" in (
        dialog.sync_summary_label.text()
    )
    assert dialog.cache_label.accessibleName() == "Industrial cache readiness"
    assert dialog.workflow_label.accessibleName() == "Industrial workflow status"
    assert dialog.sync_summary_label.accessibleName() == "Industrial last cache outcome"
    assert dialog.analytics_status_label.accessibleName() == "Industrial CSV Summary readiness"
    assert dialog.sync_button.accessibleName() == "Fetch industrial rows into cache"
    dialog.close()


def test_launcher_reports_last_sync_warning_from_cached_diagnostics(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    repository = IndustrialDataRepository(db_path)
    profile = repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    sync_run_id = repository.create_sync_run(source_profile_id=profile.id)
    repository.finish_sync_run(
        sync_run_id=sync_run_id,
        status="failed",
        row_count=0,
        error_summary="fetch failed password=super-secret",
        diagnostics={"warnings": ["timeout password=also-secret"]},
    )

    dialog = IndustrialDataDialog(db_file=db_path)

    assert "Access: failed" in dialog.workflow_label.text()
    assert "fetch failed password=<redacted>" in dialog.sync_summary_label.text()
    assert "super-secret" not in dialog.sync_summary_label.text()
    assert "also-secret" not in dialog.sync_summary_label.text()
    dialog.close()


def test_industrial_workflow_dialogs_fit_their_initial_heights(tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        allowed_columns=("event_id", "reference", "station"),
    )

    dialogs = [
        IndustrialDataDialog(db_file=db_path),
        IndustrialSourceProfilesDialog(db_file=db_path, config_path=tmp_path / "industrial_sources.yaml"),
        IndustrialSyncDialog(
            db_file=db_path,
            filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
        ),
        IndustrialExportDialog(
            db_file=db_path,
            filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
            grouping_state=IndustrialGroupingState(fields=("station",)),
        ),
    ]
    try:
        available = _app().primaryScreen().availableGeometry()
        for dialog in dialogs:
            assert dialog.sizeHint().height() <= dialog.height()
            assert dialog.width() <= available.width()
    finally:
        for dialog in dialogs:
            dialog.close()


def test_reference_paste_parser_accepts_common_user_formats():
    assert parse_reference_values("REF1, REF2;REF3\nREF4 REF5\tREF6") == (
        "REF1",
        "REF2",
        "REF3",
        "REF4",
        "REF5",
        "REF6",
    )
    assert parse_reference_values("REF1 REF1,REF2") == ("REF1", "REF2")
