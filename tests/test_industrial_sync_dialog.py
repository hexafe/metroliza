from __future__ import annotations

import pytest

try:
    from PyQt6.QtGui import QCloseEvent
    from PyQt6.QtWidgets import QApplication

    import modules.industrial_sync_dialog as industrial_sync_dialog
    from modules.industrial_credentials import IndustrialStoredCredentials
    from modules.industrial_data_repository import IndustrialDataRepository
    from modules.industrial_source_config import build_source_profile, upsert_source_profile_in_config
    from modules.industrial_sync_dialog import IndustrialSyncDialog
    from modules.industrial_workflow_state import IndustrialFilterState
except Exception as exc:  # pragma: no cover - depends on local Qt runtime availability.
    QCloseEvent = None
    QApplication = None
    industrial_sync_dialog = None
    IndustrialDataRepository = None
    IndustrialStoredCredentials = None
    build_source_profile = None
    upsert_source_profile_in_config = None
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


def test_sync_dialog_requires_saved_source_and_masks_password(tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    dialog = IndustrialSyncDialog(db_file=db_path)

    assert dialog.profile_combo.count() == 0
    assert not dialog.sync_now_button.isEnabled()
    assert dialog.password_edit.echoMode() == dialog.password_edit.EchoMode.Password
    assert dialog.remember_credentials_checkbox.text() == "Remember on this computer"
    assert "File store:" in dialog.credentials_location_label.text()
    assert dialog.forget_credentials_button.text() == "Forget saved credentials"
    assert not dialog.forget_credentials_button.isEnabled()
    dialog.close()


def test_sync_dialog_prefills_locally_saved_credentials(monkeypatch, tmp_path):
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
    monkeypatch.setattr(
        industrial_sync_dialog,
        "load_industrial_credentials",
        lambda _profile_key: IndustrialStoredCredentials(
            username="operator",
            password="secret-password",
            source="test",
        ),
    )

    dialog = IndustrialSyncDialog(db_file=db_path)

    assert dialog.username_edit.text() == "operator"
    assert dialog.password_edit.text() == "secret-password"
    assert "Credentials loaded from test" in dialog.credentials_location_label.text()
    assert dialog.forget_credentials_button.isEnabled()
    assert not dialog.remember_credentials_checkbox.isChecked()
    dialog.close()


def test_sync_dialog_forgets_locally_saved_credentials(monkeypatch, tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    credential_path = tmp_path / "industrial_credentials.env"
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
    forgotten = []
    monkeypatch.setattr(
        industrial_sync_dialog,
        "load_industrial_credentials",
        lambda _profile_key: IndustrialStoredCredentials(
            username="operator",
            password="secret-password",
            source=str(credential_path),
        ),
    )
    monkeypatch.setattr(
        industrial_sync_dialog,
        "forget_industrial_credentials",
        lambda profile_key: forgotten.append(profile_key) or credential_path,
    )
    dialog = IndustrialSyncDialog(db_file=db_path)

    dialog.remember_credentials_checkbox.setChecked(True)
    dialog.forget_saved_credentials()

    assert forgotten == ["assembly_mes"]
    assert dialog.username_edit.text() == ""
    assert dialog.password_edit.text() == ""
    assert not dialog.remember_credentials_checkbox.isChecked()
    assert "No saved credentials" in dialog.credentials_location_label.text()
    assert "Saved credentials forgotten" in dialog.status_label.text()
    dialog.close()


def test_sync_dialog_profile_switch_replaces_or_clears_stored_credentials(monkeypatch, tmp_path):
    _app()
    db_path = str(tmp_path / "industrial.db")
    repository = IndustrialDataRepository(db_path)
    for profile_key, profile_name in (
        ("assembly_mes", "Assembly MES"),
        ("paint_mes", "Paint MES"),
        ("weld_mes", "Weld MES"),
    ):
        repository.upsert_source_profile(
            profile_key=profile_key,
            profile_name=profile_name,
            source_db_alias=profile_key,
            database_type="mssql",
            source_object_name="events",
            host=f"{profile_key}.example.invalid",
            port=1433,
            database_name="plantdb",
        )
    stored_credentials = {
        "assembly_mes": IndustrialStoredCredentials(
            username="assembly-user",
            password="assembly-secret",
        ),
        "paint_mes": IndustrialStoredCredentials(),
        "weld_mes": IndustrialStoredCredentials(
            username="weld-user",
            password="weld-secret",
        ),
    }
    monkeypatch.setattr(
        industrial_sync_dialog,
        "load_industrial_credentials",
        lambda profile_key: stored_credentials[profile_key],
    )

    dialog = IndustrialSyncDialog(db_file=db_path)

    assert dialog.username_edit.text() == "assembly-user"
    assert dialog.password_edit.text() == "assembly-secret"

    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findText("Paint MES"))

    assert dialog.username_edit.text() == ""
    assert dialog.password_edit.text() == ""

    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findText("Weld MES"))

    assert dialog.username_edit.text() == "weld-user"
    assert dialog.password_edit.text() == "weld-secret"
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


def test_sync_dialog_does_not_add_default_reference_column_without_filter_values(tmp_path):
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

    dialog = IndustrialSyncDialog(db_file=db_path)
    runtime_profile = dialog._profile_for_current_filter()

    assert runtime_profile.allowed_columns == ("event_id", "station")
    dialog.close()


def test_sync_dialog_allows_limited_sync_without_reference_values(tmp_path):
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
    assert dialog.sync_now_button.isEnabled()
    assert dialog.limit_spin.value() == 5000

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

    assert dialog.status_label.text() == "Industrial fetch failed: Fetch failed password=<redacted>"
    assert "super-secret" not in dialog.status_label.text()

    dialog.on_oznak_result(
        {
            "test_only": False,
            "status": "cancelled",
            "error": "Sync cancelled by user.",
            "diagnostics": {},
        }
    )

    assert dialog.status_label.text() == "Industrial fetch cancelled: Sync cancelled by user."
    dialog.close()


def test_sync_dialog_shows_completed_with_warnings_status(tmp_path):
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
            "status": "completed_with_warnings",
            "error": "secondary source timed out password=super-secret",
            "row_count": 3,
            "upsert_summary": {"processed": 3},
            "diagnostics": {},
        }
    )

    assert (
        dialog.status_label.text()
        == "Fetch complete with warnings: 3 rows: secondary source timed out password=<redacted>"
    )
    assert "super-secret" not in dialog.status_label.text()
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


def test_sync_dialog_access_only_loads_profiles_from_config(tmp_path):
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
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        ),
    )
    dialog = IndustrialSyncDialog(
        db_file=None,
        config_path=config_path,
        access_only=True,
    )

    assert dialog.profile_combo.count() == 1
    assert dialog.test_connection_button.isEnabled()
    assert dialog.sync_now_button.isHidden()
    assert dialog.edit_filter_button.isHidden()
    assert dialog.limit_spin.isHidden()
    assert dialog.fetch_all_checkbox.isHidden()
    assert dialog.filter_status_label.isHidden()
    assert "Access-only mode" in dialog.status_label.text()
    assert "never saves data" in dialog.status_label.text()
    dialog.close()


def test_sync_dialog_no_database_non_access_mode_stays_disabled(tmp_path):
    _app()
    dialog = IndustrialSyncDialog(db_file=None, access_only=False, config_path=tmp_path / "sources.yaml")

    assert dialog.current_profile() is None
    assert not dialog.test_connection_button.isEnabled()
    assert not dialog.sync_now_button.isEnabled()
    assert "Create a production source before fetching rows" in dialog.status_label.text()
    with pytest.raises(ValueError, match="Create or select"):
        dialog._profile_for_current_filter()
    dialog.close()


def test_sync_dialog_starts_sync_thread_without_external_connection(monkeypatch, tmp_path):
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
        allowed_columns=("event_id", "reference"),
        default_pagination_column="event_id",
    )
    saved_credentials = []
    monkeypatch.setattr(
        industrial_sync_dialog,
        "save_industrial_credentials",
        lambda profile_key, *, username, password: saved_credentials.append(
            (profile_key, username, password)
        ),
    )
    started_threads = []

    class Signal:
        def __init__(self):
            self.callbacks = []

        def connect(self, callback):
            self.callbacks.append(callback)

    class FakeSyncThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            self.started = False
            started_threads.append(self)

        def start(self):
            self.started = True

        def isRunning(self):
            return self.started

        def cancel(self):
            self.started = False

    monkeypatch.setattr(industrial_sync_dialog, "IndustrialOznakSyncThread", FakeSyncThread)
    dialog = IndustrialSyncDialog(
        db_file=db_path,
        filter_state=IndustrialFilterState(reference_column="reference", references=("REF-1",)),
    )
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("secret-password")
    dialog.remember_credentials_checkbox.setChecked(True)

    dialog.sync_now()

    assert saved_credentials == []
    assert started_threads[0].started is True
    assert started_threads[0].kwargs["reference_filter_column"] == "reference"
    assert started_threads[0].kwargs["reference_values"] == ("REF-1",)
    assert dialog.cancel_sync_button.isEnabled()

    dialog.on_oznak_result(
        {
            "status": "succeeded",
            "test_only": False,
            "row_count": 1,
            "upsert_summary": {"processed": 1},
        }
    )

    assert saved_credentials == [("assembly_mes", "operator", "secret-password")]

    dialog.cancel_sync()
    assert "Cancelling industrial fetch" in dialog.status_label.text()
    dialog.on_oznak_thread_stopped()
    assert dialog.oznak_sync_thread is None
    assert not dialog.cancel_sync_button.isEnabled()
    dialog.close()


def test_sync_dialog_access_check_thread_and_result_statuses(monkeypatch, tmp_path):
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
            allowed_columns=("event_id", "reference"),
            default_pagination_column="event_id",
        ),
    )
    started = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

    class FakeAccessThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            started.append(self)

        def start(self):
            self.started = True

        def isRunning(self):
            return False

    monkeypatch.setattr(industrial_sync_dialog, "IndustrialOznakAccessCheckThread", FakeAccessThread)
    saved_credentials = []
    monkeypatch.setattr(
        industrial_sync_dialog,
        "save_industrial_credentials",
        lambda profile_key, *, username, password: saved_credentials.append(
            (profile_key, username, password)
        ),
    )
    dialog = IndustrialSyncDialog(db_file=None, config_path=config_path, access_only=True)
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("secret-password")
    dialog.remember_credentials_checkbox.setChecked(True)

    dialog.test_connection()
    assert saved_credentials == []
    dialog.on_oznak_progress("Reading one row")
    dialog.on_oznak_result({"status": "succeeded", "test_only": True, "row_count": 0})
    assert saved_credentials == [("assembly_mes", "operator", "secret-password")]
    assert started[0].kwargs["profile"].profile_key == "assembly_mes"
    assert started[0].kwargs["reference_filter_column"] is None
    assert started[0].kwargs["reference_values"] == ()
    assert "0 rows visible" in dialog.status_label.text()

    dialog.on_oznak_result({"status": "succeeded", "test_only": True, "row_count": 2})
    assert "Access check passed: 2 row(s)" in dialog.status_label.text()
    assert dialog._format_failed_result_status(
        {"status": "failed", "test_only": True, "diagnostics": {"warnings": ["password=secret"]}}
    ) == "Access check failed: password=<redacted>"
    dialog.close()


def test_sync_dialog_access_check_forwards_configured_reference_filter(monkeypatch, tmp_path):
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
    started = []

    class Signal:
        def connect(self, callback):
            self.callback = callback

    class FakeAccessThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.progress_message = Signal()
            self.result_ready = Signal()
            self.error_occurred = Signal()
            self.finished = Signal()
            started.append(self)

        def start(self):
            self.started = True

        def isRunning(self):
            return False

    monkeypatch.setattr(industrial_sync_dialog, "IndustrialOznakAccessCheckThread", FakeAccessThread)
    dialog = IndustrialSyncDialog(
        db_file=None,
        config_path=config_path,
        access_only=True,
        filter_state=IndustrialFilterState(reference_column="serial_number", references=("SN-1",)),
    )
    dialog.username_edit.setText("operator")
    dialog.password_edit.setText("secret-password")

    dialog.test_connection()

    assert started[0].kwargs["reference_filter_column"] == "serial_number"
    assert started[0].kwargs["reference_values"] == ("SN-1",)
    assert "serial_number" in started[0].kwargs["profile"].allowed_columns
    dialog.close()


def test_sync_dialog_error_and_close_running_paths(monkeypatch, tmp_path):
    _app()
    warnings = []
    infos = []
    monkeypatch.setattr(industrial_sync_dialog.QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(
        industrial_sync_dialog.QMessageBox,
        "information",
        lambda *args: infos.append(args),
    )

    class RunningThread:
        def isRunning(self):
            return True

    dialog = IndustrialSyncDialog(parent=None, db_file=str(tmp_path / "industrial.db"))
    dialog.on_oznak_error("password=super-secret")
    dialog.oznak_sync_thread = RunningThread()
    event = QCloseEvent()
    dialog.closeEvent(event)

    assert "password=<redacted>" in warnings[0][2]
    assert "super-secret" not in warnings[0][2]
    assert infos[0][2] == "Cancel or wait for the operation to finish."
    assert not event.isAccepted()
    dialog.oznak_sync_thread = None
    dialog.close()
