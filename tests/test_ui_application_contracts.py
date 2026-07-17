from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from PyQt6.QtCore import QByteArray, QCoreApplication, QEvent, QSettings, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from metroliza.ui.ui_outcomes import (
    SafeQtOutcomePresenter,
    UiArtifact,
    UiIssue,
    UiOutcome,
    UiOutcomeStatus,
)
from metroliza.ui.ui_preferences import UiPreferenceKeyError, UiPreferences
from metroliza.ui.ui_tasks import UiTaskClosePolicy, UiTaskController, UiTaskState
from metroliza.ui.window_coordinator import (
    ModelessWindowSpec,
    WindowContextPolicy,
    WindowCoordinator,
)
from metroliza.ui.workspace_context import WorkspaceContext, WorkspaceField


_APP = None


@pytest.fixture(scope="module")
def qapp():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def _flush_deferred_deletes(app: QApplication) -> None:
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_workspace_context_emits_one_immutable_versioned_snapshot_per_update(tmp_path) -> None:
    context = WorkspaceContext()
    initial = context.snapshot
    snapshots: list[tuple[object, object]] = []
    source_changes: list[tuple[object, int]] = []
    database_changes: list[tuple[object, int]] = []
    context.snapshot_changed.connect(lambda current, previous: snapshots.append((current, previous)))
    context.source_directory_changed.connect(
        lambda value, version: source_changes.append((value, version))
    )
    context.database_file_changed.connect(
        lambda value, version: database_changes.append((value, version))
    )

    source = tmp_path / "reports"
    database = tmp_path / "reports.db"
    current = context.update(source_directory=source, database_file=database)

    assert current.version == 1
    assert current.source_directory == str(source)
    assert current.database_file == str(database)
    assert current.changed_fields(initial) == {
        WorkspaceField.SOURCE_DIRECTORY,
        WorkspaceField.DATABASE_FILE,
    }
    assert snapshots == [(current, initial)]
    assert source_changes == [(str(source), 1)]
    assert database_changes == [(str(database), 1)]
    with pytest.raises(FrozenInstanceError):
        current.version = 10  # type: ignore[misc]

    assert context.update(source_directory=source, database_file=database) is current
    assert len(snapshots) == 1

    cleared = context.clear()
    assert cleared.version == 2
    assert cleared.source_directory is None
    assert cleared.database_file is None


def test_workspace_context_rejects_non_path_values() -> None:
    context = WorkspaceContext()

    with pytest.raises(TypeError, match="Workspace paths"):
        context.set_database_file(123)  # type: ignore[arg-type]


def test_ui_task_controller_cancels_and_completes_exactly_once() -> None:
    controller = UiTaskController(close_policy=UiTaskClosePolicy.CANCEL_AND_DEFER)
    state_changes: list[tuple[UiTaskState, UiTaskState]] = []
    cancellation_requests: list[None] = []
    deferred_requests: list[None] = []
    terminal_outcomes: list[UiOutcome[object]] = []
    close_ready: list[None] = []
    controller.state_changed.connect(
        lambda current, previous: state_changes.append((current, previous))
    )
    controller.cancel_requested.connect(lambda: cancellation_requests.append(None))
    controller.close_deferred.connect(lambda: deferred_requests.append(None))
    controller.terminal.connect(terminal_outcomes.append)
    controller.close_ready.connect(lambda: close_ready.append(None))

    controller.start()
    assert controller.state is UiTaskState.RUNNING
    assert controller.request_close() is False
    assert controller.request_close() is False
    assert controller.state is UiTaskState.CANCEL_REQUESTED
    assert controller.cancellation_requested is True
    assert cancellation_requests == [None]
    assert deferred_requests == [None]

    assert controller.cancel(message="Stopped safely.") is True
    assert controller.cancel(message="Duplicate terminal signal.") is False
    assert controller.succeed("late result") is False
    assert controller.state is UiTaskState.CANCELLED
    assert controller.outcome is terminal_outcomes[0]
    assert controller.outcome is not None
    assert controller.outcome.message == "Stopped safely."
    assert close_ready == [None]
    assert [change[0] for change in state_changes] == [
        UiTaskState.RUNNING,
        UiTaskState.CANCEL_REQUESTED,
        UiTaskState.CANCELLED,
    ]

    controller.reset()
    assert controller.state is UiTaskState.IDLE
    controller.start()
    issue = UiIssue(
        code="validation_failed",
        title="Invalid request",
        message="Review the selected inputs.",
    )
    assert controller.fail(issue) is True
    assert controller.outcome is not None
    assert controller.outcome.status is UiOutcomeStatus.FAILED


def test_ui_task_close_policies_do_not_infer_cancellation() -> None:
    blocked = UiTaskController(close_policy=UiTaskClosePolicy.BLOCK)
    blocked_requests: list[None] = []
    blocked.cancel_requested.connect(lambda: blocked_requests.append(None))
    blocked.start()
    assert blocked.request_close() is False
    assert blocked.state is UiTaskState.RUNNING
    assert blocked_requests == []

    detached = UiTaskController(close_policy=UiTaskClosePolicy.DETACH)
    detached.start()
    assert detached.request_close() is True
    assert detached.state is UiTaskState.RUNNING
    assert detached.succeed("result") is True

    with pytest.raises(RuntimeError, match="terminal"):
        blocked.reset()


def test_ui_outcomes_are_typed_and_require_failed_issue(tmp_path) -> None:
    artifact = UiArtifact(kind="workbook", label="Workbook", path=tmp_path / "report.xlsx")
    outcome = UiOutcome.succeeded(
        {"rows": 12},
        message="Workbook created.",
        artifacts=(artifact,),
    )

    assert outcome.status is UiOutcomeStatus.SUCCEEDED
    assert outcome.artifacts == (artifact,)
    with pytest.raises(ValueError, match="failed UI outcome"):
        UiOutcome(status=UiOutcomeStatus.FAILED)
    with pytest.raises(ValueError, match="either path or uri"):
        UiArtifact(kind="workbook", label="Workbook")


def test_safe_qt_presenter_never_interpolates_exception_copy(monkeypatch, caplog) -> None:
    raw_exception_copy = "database password TOP-SECRET-RAW"
    issue = UiIssue.unexpected(
        RuntimeError(raw_exception_copy),
        operation="export",
        message="Export could not be completed safely.",
    )
    presented: list[tuple[object, str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, message: presented.append((parent, title, message)),
    )

    SafeQtOutcomePresenter().present_issue(issue)

    assert len(presented) == 1
    _parent, title, primary_copy = presented[0]
    assert title == "Could not complete export"
    assert "Export could not be completed safely." in primary_copy
    assert issue.diagnostic_id in primary_copy
    assert raw_exception_copy not in title
    assert raw_exception_copy not in primary_copy
    assert raw_exception_copy not in caplog.text
    assert "cause_type=RuntimeError" in caplog.text


def _settings(path: Path) -> QSettings:
    return QSettings(str(path), QSettings.Format.IniFormat)


def test_ui_preferences_round_trip_typed_ui_only_values(tmp_path) -> None:
    settings_path = tmp_path / "ui.ini"
    preferences = UiPreferences(_settings(settings_path), schema_version=2)
    geometry = QByteArray(b"window-geometry")

    assert preferences.schema_healthy is True
    assert preferences.set("windows/main/geometry", geometry) is True
    assert preferences.set("theme/mode", "system") is True
    assert preferences.set("accessibility/reduce_motion", True) is True

    reloaded = UiPreferences(_settings(settings_path), schema_version=2)
    assert reloaded.get(
        "windows/main/geometry",
        QByteArray(),
        expected_type=QByteArray,
    ) == geometry
    assert reloaded.get("theme/mode", "light", expected_type=str) == "system"
    assert reloaded.get("accessibility/reduce_motion", False, expected_type=bool) is True

    with pytest.raises(UiPreferenceKeyError, match="Sensitive"):
        reloaded.set("presentation/token", "never-store-this")
    with pytest.raises(UiPreferenceKeyError, match="must start"):
        reloaded.set("database/last_path", "not-ui-state")


def test_ui_preferences_use_safe_fallback_for_corrupt_schema_and_values(tmp_path) -> None:
    settings_path = tmp_path / "corrupt-ui.ini"
    raw = _settings(settings_path)
    raw.beginGroup("metroliza_ui")
    raw.setValue("_schema_version", "broken")
    raw.setValue("v3/theme/mode", {"unexpected": "mapping"})
    raw.endGroup()
    raw.setValue("domain/value", "preserve-me")
    raw.sync()

    preferences = UiPreferences(_settings(settings_path), schema_version=3)
    assert preferences.schema_healthy is False
    assert preferences.get("theme/mode", "light", expected_type=str) == "light"

    assert preferences.set("theme/mode", "dark") is True
    assert preferences.schema_healthy is True
    assert preferences.stored_schema_version == 3
    assert preferences.get("theme/mode", "light", expected_type=str) == "dark"
    assert preferences.reset() is True
    assert _settings(settings_path).value("domain/value") == "preserve-me"


def test_ui_preferences_fall_back_on_wrong_value_type(tmp_path) -> None:
    settings_path = tmp_path / "wrong-type.ini"
    UiPreferences(_settings(settings_path))
    raw = _settings(settings_path)
    raw.setValue("metroliza_ui/v1/theme/mode", 42)
    raw.sync()

    reloaded = UiPreferences(_settings(settings_path))
    assert reloaded.get("theme/mode", "system", expected_type=str) == "system"
    assert reloaded.corrupt_keys == ("theme/mode",)


def test_window_coordinator_reuses_and_cleans_modeless_windows(
    qapp: QApplication,
) -> None:
    context = WorkspaceContext(database_file="first.db")
    coordinator = WindowCoordinator(context)
    created: list[QDialog] = []
    opened: list[str] = []
    reused: list[str] = []
    closed: list[str] = []
    coordinator.window_opened.connect(lambda window_id, _widget: opened.append(window_id))
    coordinator.window_reused.connect(lambda window_id, _widget: reused.append(window_id))
    coordinator.window_closed.connect(closed.append)

    def factory(snapshot):
        dialog = QDialog()
        dialog.setProperty("opened_database", snapshot.database_file)
        created.append(dialog)
        return dialog

    coordinator.register_modeless(
        ModelessWindowSpec(
            window_id="export",
            factory=factory,
            context_policy=WindowContextPolicy.CLOSE,
            context_fields=frozenset({WorkspaceField.DATABASE_FILE}),
        )
    )

    first = coordinator.open_modeless("export")
    assert first.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    assert first.property("opened_database") == "first.db"
    assert coordinator.open_modeless("export") is first
    assert len(created) == 1
    assert opened == ["export"]
    assert reused == ["export"]

    context.set_source_directory("reports")
    assert coordinator.get("export") is first
    context.set_database_file("second.db")
    _flush_deferred_deletes(qapp)
    assert coordinator.get("export") is None
    assert closed == ["export"]

    second = coordinator.open_modeless("export")
    assert second is not first
    assert second.property("opened_database") == "second.db"
    assert coordinator.unregister("export") is False
    assert coordinator.close("export") is True
    _flush_deferred_deletes(qapp)
    assert coordinator.unregister("export") is True


def test_window_coordinator_updates_relevant_context_and_reports_failures(
    qapp: QApplication,
) -> None:
    context = WorkspaceContext(database_file="first.db")
    coordinator = WindowCoordinator(context)
    updated_versions: list[int] = []
    update_failures: list[tuple[str, object]] = []
    coordinator.context_update_failed.connect(
        lambda window_id, error: update_failures.append((window_id, error))
    )

    def update_context(widget, snapshot) -> None:
        widget.setProperty("database", snapshot.database_file)
        updated_versions.append(snapshot.version)

    coordinator.open_modeless(
        "monitor",
        lambda _snapshot: QDialog(),
        context_policy=WindowContextPolicy.UPDATE,
        context_fields=frozenset({WorkspaceField.DATABASE_FILE}),
        context_updater=update_context,
    )
    monitor = coordinator.get("monitor")
    assert monitor is not None
    context.set_source_directory("reports")
    assert updated_versions == []
    context.set_database_file("second.db")
    assert monitor.property("database") == "second.db"
    assert updated_versions == [2]

    def fail_update(_widget, _snapshot) -> None:
        raise RuntimeError("update failed")

    coordinator.open_modeless(
        "broken",
        lambda _snapshot: QDialog(),
        context_policy=WindowContextPolicy.UPDATE,
        context_updater=fail_update,
    )
    context.set_database_file("third.db")
    assert len(update_failures) == 1
    assert update_failures[0][0] == "broken"
    assert isinstance(update_failures[0][1], RuntimeError)
    assert coordinator.close_all() == ()
    _flush_deferred_deletes(qapp)
    assert coordinator.open_window_ids == ()
