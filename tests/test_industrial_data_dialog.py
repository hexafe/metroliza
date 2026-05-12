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

    dialog.save_source()
    profiles = IndustrialDataRepository(db_path).list_source_profiles(include_disabled=True)

    assert len(profiles) == 1
    assert profiles[0].profile_key == "assembly_mes"
    assert profiles[0].host == "mes.example.invalid"
    assert profiles[0].port == 1433
    assert profiles[0].database_name == "plantdb"
    assert profiles[0].source_object_name == "events"
    assert profiles[0].allowed_columns == ("event_id", "event_at", "reference", "station")
    assert "assembly_mes:" in config_path.read_text(encoding="utf-8")
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
    dialog.columns_edit.setText("event_id, reference")
    dialog.record_key_edit.setText("event_id")

    dialog.save_source()

    assert config_path.exists()
    config_text = config_path.read_text(encoding="utf-8")
    assert "assembly_mes:" in config_text
    assert "password" not in config_text.lower()
    assert "Select a Metroliza report database" in dialog.status_label.text()
    assert "Connect and sync" in dialog.status_label.text()
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
    assert counts.sync_runs == 0
    assert counts.records == 0


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
    assert dialog.sync_button.text() == "Connect and sync..."
    assert dialog.links_button.text() == "Production links..."
    assert dialog.export_button.text() == "Export..."
    assert dialog.sizeHint().height() <= 520
    dialog.close()


def test_launcher_keeps_source_configuration_available_without_database():
    _app()
    dialog = IndustrialDataDialog(db_file=None)

    assert dialog.sources_button.isEnabled()
    assert not dialog.sync_button.isEnabled()
    assert not dialog.links_button.isEnabled()
    assert not dialog.export_button.isEnabled()
    assert not dialog.initialize_button.isEnabled()
    assert dialog.select_database_button.isEnabled()
    assert "Select a Metroliza report database here" in dialog.status_label.text()
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
    assert "Local industrial cache ready" in dialog.status_label.text()
    dialog.close()
    parent.close()


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
