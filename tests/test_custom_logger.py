import builtins
import logging
import uuid

import pytest

from metroliza.shared import custom_logger
from metroliza.shared.diagnostic_events import (
    DiagnosticOperation,
    ExceptionDiagnosticEvent,
    serialize_diagnostic_event,
)
from metroliza.shared.logging_utils import ManagedSafeFormatter


class RecordHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _capturing_logger(name):
    active_logger = logging.getLogger(name)
    active_logger.handlers.clear()
    active_logger.propagate = False
    active_logger.setLevel(logging.DEBUG)
    handler = RecordHandler()
    active_logger.addHandler(handler)
    return active_logger, handler


def _assert_marker_absent(marker, value):
    if marker in value:
        pytest.fail("generated exception marker reached diagnostic output")


def test_log_exception_emits_only_structural_event():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, handler = _capturing_logger(f"metroliza.custom.{marker}")
    try:
        try:
            cause = ValueError(marker)
            cause.add_note(marker)
            raise cause
        except ValueError as cause:
            raise ExceptionGroup(marker, [RuntimeError(marker), KeyError(marker)]) from cause
    except ExceptionGroup as exception:
        custom_logger.log_exception(
            exception,
            logger_name=active_logger.name,
            context=f"arbitrary-operation-{marker}",
        )

    assert len(handler.records) == 1
    record = handler.records[0]
    assert type(record.msg) is ExceptionDiagnosticEvent
    assert record.args == ()
    assert record.exc_info is None
    assert record.msg.operation is DiagnosticOperation.UNHANDLED_EXCEPTION
    output = serialize_diagnostic_event(record.msg)
    _assert_marker_absent(marker, output)
    assert record.msg.exception_type == "builtins.ExceptionGroup"
    assert record.msg.cause_count == 1
    assert record.msg.group_count == 1
    assert record.msg.group_member_count == 2


def test_handle_exception_reraises_original_object():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, handler = _capturing_logger("metroliza.custom.reraise")
    exception = RuntimeError(marker)

    with pytest.raises(RuntimeError) as raised:
        custom_logger.handle_exception(
            exception,
            behavior=custom_logger.LOG_ONLY,
            logger_name=active_logger.name,
            context=marker,
        )

    assert raised.value is exception
    assert type(handler.records[0].msg) is ExceptionDiagnosticEvent


def test_handle_exception_without_reraise_preserves_dialog_behavior(monkeypatch):
    active_logger, handler = _capturing_logger("metroliza.custom.dialog")
    calls = []
    monkeypatch.setattr(custom_logger, "notify_user", lambda **kwargs: calls.append(kwargs))

    custom_logger.handle_exception(
        RuntimeError("not persisted"),
        behavior=custom_logger.LOG_AND_DIALOG,
        logger_name=active_logger.name,
        dialog_title="Title",
        dialog_message="Message",
        dialog_parent=object(),
        reraise=False,
    )

    assert len(handler.records) == 1
    assert calls[0]["title"] == "Title"
    assert calls[0]["message"] == "Message"


def test_notify_user_qt_import_failure_is_non_throwing_and_structural(monkeypatch):
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, handler = _capturing_logger("metroliza.custom.qt_import")
    monkeypatch.setattr(custom_logger, "logger", active_logger)
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PyQt6.QtWidgets":
            raise ImportError(marker)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    custom_logger.notify_user(message="message")

    assert len(handler.records) == 1
    event = handler.records[0].msg
    assert type(event) is ExceptionDiagnosticEvent
    assert event.operation is DiagnosticOperation.QT_DIALOG_IMPORT_FAILURE
    _assert_marker_absent(marker, serialize_diagnostic_event(event))


def test_custom_logger_legacy_wrapper_preserves_non_reraise_control_flow():
    active_logger, handler = _capturing_logger("metroliza.custom.wrapper")

    custom_logger.CustomLogger(
        RuntimeError("not persisted"),
        reraise=False,
        behavior=custom_logger.LOG_ONLY,
        logger_name=active_logger.name,
    )

    assert len(handler.records) == 1
    assert type(handler.records[0].msg) is ExceptionDiagnosticEvent


def test_dynamic_logger_and_context_metadata_are_not_rendered_by_managed_formatter():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, handler = _capturing_logger(f"dynamic.{marker}")

    custom_logger.log_exception(
        RuntimeError(marker),
        logger_name=active_logger.name,
        context=marker,
    )

    output = ManagedSafeFormatter().format(handler.records[0])
    _assert_marker_absent(marker, output)
    assert "exception_diagnostic" in output
