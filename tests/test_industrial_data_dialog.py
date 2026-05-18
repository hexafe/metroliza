from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    from PyQt6.QtWidgets import QApplication, QComboBox, QWidget  # noqa: F401

    from modules import industrial_data_dialog
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
    assert "Use Export" in dialog.status_label.text()
    assert "sync rows into the local cache" in dialog.status_label.text()
    dialog.close()


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
    assert dialog.select_database_button.text() == "Select DB..."
    assert dialog.sources_button.text() == "Production sources..."
    assert dialog.sync_button.text() == "Check access / sync..."
    assert "Test connection performs a one-row read" in dialog.sync_button.toolTip()
    assert dialog.links_button.text() == "Production links..."
    assert dialog.export_button.text() == "Export..."
    assert dialog.sizeHint().height() <= 520
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
    assert dialog.sync_now_button.text() == "Sync now"
    assert "saves them in the local Metroliza cache" in dialog.sync_now_button.toolTip()
    assert dialog.edit_filter_button.text() == "Edit references..."
    dialog.close()


def test_launcher_analytics_uses_shared_production_cache_workflow(monkeypatch, tmp_path):
    _app()
    db_path = str(tmp_path / "metroliza.db")
    launched = {}

    class FakeAnalyticsDialog:
        def __init__(self, parent, *, db_file, source_kind):
            launched["parent"] = parent
            launched["db_file"] = db_file
            launched["source_kind"] = source_kind
            self.executed = False

        def exec(self):
            launched["executed"] = True

    monkeypatch.setattr(industrial_data_dialog, "IndustrialAnalyticsDialog", FakeAnalyticsDialog)
    dialog = IndustrialDataDialog(db_file=db_path)

    dialog.open_analytics_dialog()

    assert launched["parent"] is dialog
    assert launched["db_file"] == db_path
    assert launched["source_kind"] == "production_cache"
    assert launched["executed"] is True
    dialog.close()


def test_launcher_keeps_source_configuration_available_without_database(tmp_path):
    _app()
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = tmp_path / "industrial_sources.yaml"
    dialog.refresh_status()

    assert dialog.sources_button.isEnabled()
    assert not dialog.sync_button.isEnabled()
    assert not dialog.links_button.isEnabled()
    assert not dialog.export_button.isEnabled()
    assert not dialog.initialize_button.isEnabled()
    assert "Select a report DB" in dialog.analytics_status_label.text()
    assert dialog.select_database_button.isEnabled()
    assert "use Export to fetch directly" in dialog.status_label.text()
    dialog.close()


def test_launcher_enables_direct_export_when_source_config_exists(tmp_path):
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
    assert not dialog.initialize_button.isEnabled()
    assert not dialog.refresh_links_button.isEnabled()
    assert not dialog.analyze_button.isEnabled()
    assert "Select a report DB" in dialog.analytics_status_label.text()
    dialog.close()


def test_launcher_opens_access_only_sync_without_metroliza_database(monkeypatch, tmp_path):
    _app()
    launched = {}

    class FakeSyncDialog:
        def __init__(self, parent, *, db_file, config_path, access_only, filter_state):
            launched["parent"] = parent
            launched["db_file"] = db_file
            launched["config_path"] = config_path
            launched["access_only"] = access_only
            launched["filter_state"] = filter_state

        def exec(self):
            launched["executed"] = True

    monkeypatch.setattr(industrial_data_dialog, "IndustrialSyncDialog", FakeSyncDialog)
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = tmp_path / "industrial_sources.yaml"

    dialog.open_sync_dialog()

    assert launched["parent"] is dialog
    assert launched["db_file"] is None
    assert launched["config_path"] == dialog.config_path
    assert launched["access_only"] is True
    assert launched["filter_state"] is dialog.sync_filter_state
    assert launched["executed"] is True
    dialog.close()


def test_launcher_opens_direct_export_without_metroliza_database(monkeypatch, tmp_path):
    _app()
    launched = {}

    class FakeExportDialog:
        def __init__(
            self,
            parent,
            *,
            db_file,
            filter_state,
            grouping_state,
            include_plots,
            config_path,
        ):
            launched["parent"] = parent
            launched["db_file"] = db_file
            launched["config_path"] = config_path
            launched["filter_state"] = filter_state
            launched["grouping_state"] = grouping_state
            launched["include_plots"] = include_plots

        def exec(self):
            launched["executed"] = True

    monkeypatch.setattr(industrial_data_dialog, "IndustrialExportDialog", FakeExportDialog)
    dialog = IndustrialDataDialog(db_file=None)
    dialog.config_path = tmp_path / "industrial_sources.yaml"

    dialog.open_export_dialog()

    assert launched["parent"] is dialog
    assert launched["db_file"] is None
    assert launched["config_path"] == dialog.config_path
    assert launched["executed"] is True
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
    assert "Local industrial cache empty" in dialog.status_label.text()
    assert "needs synced rows" in dialog.analytics_status_label.text()
    dialog.close()
    parent.close()


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

    assert "Local industrial cache ready with synced production rows" in dialog.status_label.text()
    assert "Analytics ready" in dialog.analytics_status_label.text()
    assert dialog.cache_label.accessibleName() == "Industrial cache readiness"
    assert dialog.analytics_status_label.accessibleName() == "Industrial analytics readiness"
    assert dialog.sync_button.accessibleName() == "Open industrial access check and sync"
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
        for dialog in dialogs:
            assert dialog.sizeHint().height() <= dialog.height()
            assert dialog.sizeHint().width() <= dialog.width()
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
