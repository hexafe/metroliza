from __future__ import annotations

import pytest

try:
    from PyQt6.QtWidgets import QApplication

    from modules.industrial_data_repository import IndustrialDataRepository
    from modules.industrial_sync_dialog import IndustrialSyncDialog
    from modules.industrial_workflow_state import IndustrialFilterState
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QApplication = None
    IndustrialDataRepository = None
    IndustrialSyncDialog = None
    IndustrialFilterState = None
    PYQT_IMPORT_ERROR = exc
else:
    PYQT_IMPORT_ERROR = None


pytestmark = pytest.mark.skipif(
    QApplication is None,
    reason=f"PyQt6 industrial sync dialog widgets are not available: {PYQT_IMPORT_ERROR}",
)
_QT_APP = None


def _app():
    global _QT_APP
    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_sync_dialog_keeps_credentials_session_only_and_requires_saved_source(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    dialog = IndustrialSyncDialog(db_file=db_path)

    assert dialog.profile_combo.count() == 0
    assert not dialog.sync_now_button.isEnabled()
    assert dialog.password_edit.echoMode() == dialog.password_edit.EchoMode.Password
    dialog.close()


def test_sync_dialog_adds_filter_column_to_runtime_profile_without_persisting(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    repository.upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
        allowed_columns=("event_id", "station"),
        default_pagination_column="event_id",
    )

    dialog = IndustrialSyncDialog(
        db_file=db_path,
        filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
    )
    runtime_profile = dialog._profile_for_current_filter()
    stored_profile = repository.list_source_profiles()[0]

    assert "reference" in runtime_profile.allowed_columns
    assert stored_profile.allowed_columns == ("event_id", "station")
    dialog.close()


def test_sync_dialog_keeps_connection_test_enabled_until_references_are_selected(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    dialog = IndustrialSyncDialog(db_file=db_path)

    assert dialog.test_connection_button.isEnabled()
    assert not dialog.sync_now_button.isEnabled()

    dialog.set_industrial_filter_state(
        IndustrialFilterState(reference_column="reference", references=("REF-1",))
    )

    assert dialog.test_connection_button.isEnabled()
    assert dialog.sync_now_button.isEnabled()
    dialog.close()


def test_sync_dialog_shows_sanitized_failed_and_cancelled_status(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    dialog = IndustrialSyncDialog(db_file=db_path)

    dialog.on_oznak_result(
        {
            "test_only": False,
            "status": "failed",
            "error": "Fetch failed password=super-secret",
            "diagnostics": {},
        }
    )

    assert dialog.status_label.text() == "Industrial sync failed: Fetch failed password=<redacted>"
    assert "super-secret" not in dialog.status_label.text()

    dialog.on_oznak_result(
        {
            "test_only": False,
            "status": "cancelled",
            "error": "Sync cancelled by user.",
            "diagnostics": {},
        }
    )

    assert dialog.status_label.text() == "Industrial sync cancelled: Sync cancelled by user."
    dialog.close()


def test_sync_dialog_validates_session_credentials(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    IndustrialDataRepository(db_path).upsert_source_profile(
        profile_key="assembly_mes",
        profile_name="Assembly MES",
        source_db_alias="assembly_mes",
        database_type="mssql",
        source_object_name="events",
        host="mes.example.invalid",
        port=1433,
        database_name="plantdb",
    )
    dialog = IndustrialSyncDialog(db_file=db_path)

    with pytest.raises(ValueError, match="username"):
        dialog._read_credentials()
    dialog.username_edit.setText("operator")
    with pytest.raises(ValueError, match="password"):
        dialog._read_credentials()
    dialog.password_edit.setText("secret-password")
    assert dialog._read_credentials() == ("operator", "secret-password")
    dialog.close()
