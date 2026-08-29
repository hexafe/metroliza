import builtins
import io
import logging
import uuid

from modules import custom_logger


def test_notify_user_does_not_raise_when_qt_import_fails(monkeypatch, caplog):
    original_import = builtins.__import__
    marker = f"generated-{uuid.uuid4().hex}"

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PyQt6.QtWidgets":
            raise ImportError(f"DLL load failed; access_token={marker}")
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


def _chained_exception(marker):
    try:
        try:
            raise ValueError(f"password={marker}")
        except ValueError as inner:
            raise RuntimeError(f"query={marker}") from inner
    except RuntimeError as outer:
        return outer


def test_log_exception_fails_closed_but_preserves_diagnostic_structure():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_safe_exception")
    exception = _chained_exception(marker)

    custom_logger.log_exception(
        exception,
        logger_name=active_logger.name,
        context=f"database query={marker}",
    )

    output = stream.getvalue()
    assert marker not in output
    assert "RuntimeError" in output
    assert "ValueError" in output
    assert "database" in output
    assert "traceback=present" in output
    assert "chain=present" in output


def test_handle_exception_reraises_same_object_without_leaking_message():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_safe_reraise")
    cause = ValueError(f"password={marker}")
    exception = RuntimeError(f"credential={marker}")
    exception.__cause__ = cause

    caught = None
    try:
        custom_logger.handle_exception(
            exception,
            behavior=custom_logger.LOG_ONLY,
            logger_name=active_logger.name,
            context="synthetic operation",
        )
    except RuntimeError as raised:
        caught = raised

    assert caught is exception
    assert caught.__cause__ is cause
    assert caught.__traceback__ is not None
    assert marker not in stream.getvalue()
    assert "RuntimeError" in stream.getvalue()
    assert "ValueError" in stream.getvalue()


def test_log_exception_reports_single_traceback_without_message_text():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_single_traceback")

    try:
        raise RuntimeError(marker)
    except RuntimeError as exception:
        custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "RuntimeError" in output
    assert "traceback=present" in output
    assert "traceback_frames=1" in output


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


def test_exception_type_name_cannot_execute_custom_formatting():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_exception_type_name")

    class EvilName(str):
        def __format__(self, _format_spec):
            return marker

    class SyntheticError(RuntimeError):
        pass

    SyntheticError.__name__ = EvilName("SyntheticError")
    custom_logger.log_exception(SyntheticError(marker), logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "exception_type=Exception" in output


def test_log_exception_preserves_message_free_exception_group_structure():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_exception_group")
    exception = ExceptionGroup(
        marker,
        [
            ValueError(marker),
            ExceptionGroup(marker, [KeyError(marker)]),
        ],
    )

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "exception_type=ExceptionGroup" in output
    assert "group=present" in output
    assert "group_nodes=4" in output
    assert "group_count=2" in output
    assert "group_leaf_count=2" in output
    assert "group_depth=3" in output
    assert "ValueError" in output
    assert "KeyError" in output


def test_log_exception_preserves_group_child_chain_and_traceback_structure():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_group_child_chain")

    try:
        try:
            raise ValueError(marker)
        except ValueError as inner:
            raise RuntimeError(marker) from inner
    except RuntimeError as leaf:
        exception = ExceptionGroup(marker, [leaf])

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "RuntimeError" in output
    assert "ValueError" in output
    assert "group_child_chain=present" in output
    assert "group_child_chain_nodes=1" in output
    assert "group_traceback=present" in output
    assert "traceback=present" in output


def test_log_exception_bounds_wide_exception_group_diagnostics():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_wide_exception_group")
    exception = ExceptionGroup(marker, [ValueError(marker) for _ in range(512)])

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "group_nodes=128" in output
    assert "group_truncated=yes" in output


def test_log_exception_preserves_group_structure_from_exception_chain():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_chained_exception_group")
    group = ExceptionGroup(
        marker,
        [ValueError(marker), ExceptionGroup(marker, [KeyError(marker)])],
    )
    exception = RuntimeError(marker)
    exception.__cause__ = group

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "exception_type=RuntimeError" in output
    assert "group=present" in output
    assert "group_roots=1" in output
    assert "group_nodes=4" in output
    assert "ValueError" in output
    assert "KeyError" in output


def test_handle_exception_reraises_object_with_unreadable_traceback():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_unreadable_traceback")

    class BrokenTracebackError(RuntimeError):
        def __getattribute__(self, name):
            if name == "__traceback__":
                raise KeyboardInterrupt(marker)
            return super().__getattribute__(name)

    exception = BrokenTracebackError(marker)
    caught = None
    try:
        custom_logger.handle_exception(
            exception,
            behavior=custom_logger.LOG_ONLY,
            logger_name=active_logger.name,
            context="synthetic operation",
        )
    except BrokenTracebackError as raised:
        caught = raised

    assert caught is exception
    assert marker not in stream.getvalue()
    assert "BrokenTracebackError" in stream.getvalue()
    assert "traceback=absent" in stream.getvalue()


def test_log_exception_distinguishes_explicit_cause_from_implicit_context():
    marker = f"generated-{uuid.uuid4().hex}"
    cause_logger, cause_stream = _capturing_logger(
        "metroliza_test_explicit_cause_edges"
    )
    context_logger, context_stream = _capturing_logger(
        "metroliza_test_implicit_context_edges"
    )

    try:
        try:
            raise ValueError(marker)
        except ValueError as inner:
            raise RuntimeError(marker) from inner
    except RuntimeError as explicit_cause:
        custom_logger.log_exception(
            explicit_cause,
            logger_name=cause_logger.name,
        )

    try:
        try:
            raise ValueError(marker)
        except ValueError:
            raise RuntimeError(marker)
    except RuntimeError as implicit_context:
        custom_logger.log_exception(
            implicit_context,
            logger_name=context_logger.name,
        )

    cause_output = cause_stream.getvalue()
    context_output = context_stream.getvalue()
    assert marker not in cause_output
    assert marker not in context_output
    assert "cause_edges=1" in cause_output
    assert "context_edges=0" in cause_output
    assert "cause_edges=0" in context_output
    assert "context_edges=1" in context_output


def test_log_exception_reports_notes_without_reading_note_text():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger("metroliza_test_exception_notes")
    exception = RuntimeError(marker)
    exception.add_note(f"password={marker}")

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "notes=present" in output
    assert "note_count=1" in output
    assert "notes_truncated=no" in output


def test_log_exception_note_lookup_bypasses_hostile_instance_hooks_and_keys():
    marker = f"generated-{uuid.uuid4().hex}"
    calls: list[str] = []
    active_logger, stream = _capturing_logger(
        "metroliza_test_hostile_exception_notes"
    )

    class HostileKey:
        def __hash__(self):
            return hash("__notes__")

        def __eq__(self, _other):
            calls.append("key-equality")
            return False

    class HostileException(RuntimeError):
        @property
        def __dict__(self):
            calls.append("dict-property")
            return {"__notes__": [marker]}

    exception = HostileException(marker)
    exception.add_note(marker)
    values = BaseException.__dict__["__dict__"].__get__(
        exception,
        type(exception),
    )
    values[HostileKey()] = marker
    calls.clear()

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    assert calls == []
    assert marker not in stream.getvalue()
    assert "note_count=1" in stream.getvalue()


def test_log_exception_reports_causal_group_subtree_separately():
    marker = f"generated-{uuid.uuid4().hex}"
    active_logger, stream = _capturing_logger(
        "metroliza_test_causal_group_subtree"
    )
    leaf = RuntimeError(marker)
    leaf.__cause__ = ExceptionGroup(
        marker,
        [KeyError(marker), ValueError(marker)],
    )
    exception = ExceptionGroup(marker, [leaf])

    custom_logger.log_exception(exception, logger_name=active_logger.name)

    output = stream.getvalue()
    assert marker not in output
    assert "group_nodes=2" in output
    assert "group_count=1" in output
    assert "group_leaf_count=1" in output
    assert "group_depth=2" in output
    assert "group_causal_group_nodes=3" in output
    assert "group_causal_group_count=1" in output
    assert "group_causal_group_leaf_count=2" in output
    assert "group_causal_group_depth=2" in output
