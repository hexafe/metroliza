import builtins
import io
import logging
import uuid

from metroliza.shared import custom_logger


def test_notify_user_does_not_raise_when_qt_import_fails(monkeypatch, caplog):
    original_import = builtins.__import__
    marker = f"generated-{uuid.uuid4().hex}"

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PyQt6.QtWidgets":
            raise ImportError(f"access_token={marker}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with caplog.at_level(logging.ERROR):
        custom_logger.notify_user(message="message")

    assert "Could not show error dialog because Qt failed to import" in caplog.text
    assert "ImportError" in caplog.text
    assert marker not in caplog.text


def _capturing_logger(name):
    stream = io.StringIO()
    active_logger = logging.getLogger(name)
    active_logger.handlers.clear()
    active_logger.propagate = False
    active_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    active_logger.addHandler(handler)
    return active_logger, stream


def test_log_exception_preserves_structure_without_messages_notes_or_tracebacks():
    markers = [f"generated-{uuid.uuid4().hex}" for _ in range(4)]
    active_logger, stream = _capturing_logger("metroliza_test_structural_exception")

    try:
        try:
            raise ValueError(f"password={markers[0]}")
        except ValueError as inner:
            inner.add_note(f"token={markers[1]}")
            raise RuntimeError(f"query={markers[2]}") from inner
    except RuntimeError as chained:
        exception = ExceptionGroup(markers[3], [chained, KeyError(markers[3])])

    custom_logger.log_exception(
        exception,
        logger_name=active_logger.name,
        context="generated group operation",
    )

    output = stream.getvalue()
    assert all(marker not in output for marker in markers)
    assert "ExceptionGroup" in output
    assert "RuntimeError" in output
    assert "ValueError" in output
    assert "KeyError" in output
    assert "chain=present" in output
    assert "group=present" in output
    assert "traceback=present" in output
    assert "notes=present" in output


def test_log_exception_redacts_labelled_operation_context():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_safe_context")

    custom_logger.log_exception(
        RuntimeError(marker),
        logger_name=active_logger.name,
        context=f"loading source={marker}",
    )

    output = stream.getvalue()
    assert marker not in output
    assert "loading source=[REDACTED]" in output
    assert "RuntimeError" in output


def test_handle_exception_reraises_the_original_object():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_reraise_identity")
    exception = RuntimeError(marker)

    caught = None
    try:
        custom_logger.handle_exception(
            exception,
            behavior=custom_logger.LOG_ONLY,
            logger_name=active_logger.name,
            context="generated operation",
        )
    except RuntimeError as raised:
        caught = raised

    assert caught is exception
    assert marker not in stream.getvalue()
    assert "RuntimeError" in stream.getvalue()


def test_log_exception_honors_suppressed_context():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_suppressed_context")

    try:
        try:
            raise ValueError(marker)
        except ValueError:
            raise RuntimeError(marker) from None
    except RuntimeError as exception:
        custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "RuntimeError" in output
    assert "ValueError" not in output
    assert "chain=absent" in output
