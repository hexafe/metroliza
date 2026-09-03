import io
import logging
import logging.handlers
import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from metroliza.shared import diagnostic_events
from metroliza.shared.diagnostic_events import (
    DiagnosticOperation,
    ExceptionDiagnosticEvent,
    SourceClass,
)
from metroliza.shared.logging_utils import (
    LoggingConfig,
    ManagedSafeFormatter,
    ensure_application_logging,
    resolve_logging_config,
)


def _close_handlers(logger):
    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@contextmanager
def _managed_sinks(tmp_path, *, config=None, home=None, cwd=None, fallback=None):
    root = Path(tmp_path)
    fake_home = home or root / "home"
    fake_cwd = cwd or root / "project"
    if home is None:
        fake_home.mkdir()
    if cwd is None:
        fake_cwd.mkdir()
    console = io.StringIO()
    logger = logging.getLogger(f"metroliza.tests.{uuid.uuid4().hex}")
    _close_handlers(logger)
    logger.propagate = False
    selected = config or LoggingConfig(logging.DEBUG, logging.DEBUG, logging.DEBUG)
    patches = [
        patch("metroliza.shared.logging_utils.logging.getLogger", return_value=logger),
        patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home),
        patch("metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd),
        patch.object(sys, "stderr", console),
    ]
    if fallback is not None:
        patches.append(
            patch(
                "metroliza.shared.logging_utils.tempfile.gettempdir",
                return_value=str(fallback),
            )
        )

    try:
        with patches[0], patches[1], patches[2], patches[3]:
            if len(patches) == 5:
                with patches[4]:
                    ensure_application_logging(config=selected)
            else:
                ensure_application_logging(config=selected)
        yield SimpleNamespace(
            logger=logger,
            console=console,
            home_log=fake_home / ".metroliza" / "metroliza.log",
            cwd_log=fake_cwd / "metroliza.log",
        )
    finally:
        _close_handlers(logger)


def _outputs(sinks):
    return (
        sinks.home_log.read_text(encoding="utf-8"),
        sinks.cwd_log.read_text(encoding="utf-8"),
        sinks.console.getvalue(),
    )


def _assert_marker_absent(marker, outputs):
    if any(marker in output for output in outputs):
        pytest.fail("generated marker reached managed output")


def test_managed_sinks_suppress_unknown_legacy_payload(tmp_path):
    marker = f"generated-{uuid.uuid4().hex}"
    with _managed_sinks(tmp_path) as sinks:
        sinks.logger.error("completelyNovelField=%s", marker)
        outputs = _outputs(sinks)

    _assert_marker_absent(marker, outputs)
    assert all('"event_code":"legacy_log_suppressed"' in output for output in outputs)


def test_legacy_adversarial_corpus_never_renders_arbitrary_values(tmp_path):
    marker = f"generated-{uuid.uuid4().hex}"

    class Hostile:
        def __str__(self):
            raise AssertionError("legacy __str__ was called")

        def __repr__(self):
            raise AssertionError("legacy __repr__ was called")

    try:
        try:
            cause = ValueError(marker)
            cause.add_note(marker)
            raise cause
        except ValueError as cause:
            raise ExceptionGroup(marker, [RuntimeError(marker), KeyError(marker)]) from cause
    except ExceptionGroup as exception:
        exc_info = (type(exception), exception, exception.__traceback__)

    legacy_inputs = (
        ("unknown field", (marker,)),
        (f"https://user:{marker}{'x' * 20_000}@host", ()),
        ("%(clientSecret)s %(apiKey)s %(accessToken)s", ({"clientSecret": marker},)),
        ("credentials=%s passwd=%s pwd=%s", (marker, marker, marker)),
        ("entirelyNovelDesignation=%s", (marker,)),
        (f'Authorization: "Bearer {marker}\n{[marker]}"', ()),
        ("nested=%s", ({"items": [[marker], {"novel": marker}]},)),
        (Hostile(), (Hostile(),)),
    )

    with _managed_sinks(tmp_path) as sinks:
        for message, arguments in legacy_inputs:
            record = logging.LogRecord(
                f"thirdparty.{marker}",
                logging.ERROR,
                f"/{marker}/module.py",
                7,
                message,
                arguments,
                exc_info,
                func=marker,
            )
            record.threadName = marker
            record.exc_text = marker
            record.stack_info = marker
            setattr(record, f"unknown_{marker}", Hostile())
            sinks.logger.handle(record)

        for source_name in (f"metroliza.{marker}", f"external.{marker}"):
            record = logging.LogRecord(
                source_name,
                logging.WARNING,
                f"/{marker}",
                1,
                marker,
                (),
                None,
                func=marker,
            )
            sinks.logger.handle(record)
        outputs = _outputs(sinks)

    _assert_marker_absent(marker, outputs)
    assert all("legacy_log_suppressed" in output for output in outputs)


def test_legacy_formatter_never_calls_get_message(tmp_path):
    with _managed_sinks(tmp_path) as sinks:
        formatter = sinks.logger.handlers[0].formatter
        record = logging.LogRecord(
            "metroliza.application",
            logging.ERROR,
            __file__,
            1,
            object(),
            (object(),),
            None,
        )
        called = False

        def fail_get_message():
            nonlocal called
            called = True
            raise AssertionError("LogRecord.getMessage was called")

        record.getMessage = fail_get_message
        output = formatter.format(record)

    assert called is False
    assert "legacy_log_suppressed" in output


def test_valid_structured_event_has_deterministic_output(monkeypatch):
    correlation_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(diagnostic_events.uuid, "uuid4", lambda: correlation_id)
    event = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        exception_type="builtins.RuntimeError",
        has_traceback=False,
        traceback_frames=0,
        cause_count=0,
        context_count=0,
        group_count=0,
        group_member_count=0,
        structure_truncated=False,
    )
    record = logging.LogRecord(
        "metroliza.application", logging.ERROR, __file__, 1, event, (), None
    )
    record.created = 0.0

    output = ManagedSafeFormatter().format(record)

    assert output == (
        "1970-01-01T00:00:00.000Z ERROR "
        '{"event_code":"exception_diagnostic",'
        '"operation":"unhandled_exception",'
        '"exception_type":"builtins.RuntimeError",'
        '"correlation_id":"12345678123456781234567812345678",'
        '"has_traceback":false,"traceback_frames":0,'
        '"cause_count":0,"context_count":0,"group_count":0,'
        '"group_member_count":0,"structure_truncated":false}'
    )


def test_malformed_and_forged_events_fail_closed_without_stringification():
    marker = f"generated-{uuid.uuid4().hex}"

    class Hostile:
        def __eq__(self, _other):
            raise AssertionError("malformed event value was compared")

        def __str__(self):
            raise AssertionError("malformed event value was stringified")

        def __repr__(self):
            raise AssertionError("malformed event value was represented")

    malformed = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        exception_type="builtins.RuntimeError",
        has_traceback=False,
        traceback_frames=0,
        cause_count=0,
        context_count=0,
        group_count=0,
        group_member_count=0,
        structure_truncated=False,
    )
    object.__setattr__(malformed, "exception_type", Hostile())
    malformed_record = logging.LogRecord(
        "metroliza.application", logging.ERROR, __file__, 1, malformed, (), None
    )
    malformed_uuid = ExceptionDiagnosticEvent(
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        exception_type="builtins.RuntimeError",
        has_traceback=False,
        traceback_frames=0,
        cause_count=0,
        context_count=0,
        group_count=0,
        group_member_count=0,
        structure_truncated=False,
    )
    object.__setattr__(malformed_uuid, "correlation_id", object.__new__(uuid.UUID))
    malformed_uuid_record = logging.LogRecord(
        "metroliza.application", logging.ERROR, __file__, 1, malformed_uuid, (), None
    )

    class ForgedEvent(ExceptionDiagnosticEvent):
        pass

    forged = ForgedEvent(
        operation=DiagnosticOperation.UNHANDLED_EXCEPTION,
        exception_type="builtins.RuntimeError",
        has_traceback=False,
        traceback_frames=0,
        cause_count=0,
        context_count=0,
        group_count=0,
        group_member_count=0,
        structure_truncated=False,
    )
    forged_record = logging.LogRecord(
        f"external.{marker}", logging.ERROR, __file__, 1, forged, (), None
    )

    malformed_output = ManagedSafeFormatter().format(malformed_record)
    malformed_uuid_output = ManagedSafeFormatter().format(malformed_uuid_record)
    forged_output = ManagedSafeFormatter().format(forged_record)

    assert "invalid_diagnostic_event" in malformed_output
    assert "invalid_diagnostic_event" in malformed_uuid_output
    assert "legacy_log_suppressed" in forged_output
    _assert_marker_absent(marker, (malformed_output, forged_output))


def test_formatter_does_not_mutate_shared_record():
    marker = f"generated-{uuid.uuid4().hex}"
    message = object()
    arguments = (object(), marker)
    exception = RuntimeError(marker)
    exc_info = (type(exception), exception, None)
    record = logging.LogRecord(
        "metroliza.application", logging.ERROR, marker, 1, message, arguments, exc_info
    )
    record.exc_text = marker
    record.stack_info = marker
    original = (record.msg, record.args, record.exc_info, record.exc_text, record.stack_info)

    output = ManagedSafeFormatter().format(record)

    assert (record.msg, record.args, record.exc_info, record.exc_text, record.stack_info) == original
    _assert_marker_absent(marker, (output,))


def test_file_and_console_boundaries_are_equivalent_and_bounded(tmp_path):
    with _managed_sinks(tmp_path) as sinks:
        sinks.logger.error("x" * 100_000)
        outputs = _outputs(sinks)

    assert outputs[0] == outputs[1] == outputs[2]
    assert len(outputs[0]) < 300


def test_rotation_levels_and_fallback_behavior_are_preserved(tmp_path):
    config = LoggingConfig(logging.DEBUG, logging.ERROR, logging.WARNING)
    with _managed_sinks(tmp_path, config=config) as sinks:
        files = [
            handler
            for handler in sinks.logger.handlers
            if isinstance(handler, logging.handlers.RotatingFileHandler)
        ]
        consoles = [
            handler
            for handler in sinks.logger.handlers
            if getattr(handler, "_metroliza_console_handler", False)
        ]
        assert len(files) == 2
        assert len(consoles) == 1
        assert all(handler.maxBytes == 10 * 1024 * 1024 for handler in files)
        assert all(handler.backupCount == 7 for handler in files)
        assert all(handler.level == logging.ERROR for handler in files)
        assert consoles[0].level == logging.WARNING

    home_file = tmp_path / "home_file"
    cwd_file = tmp_path / "cwd_file"
    home_file.write_text("not a directory", encoding="utf-8")
    cwd_file.write_text("not a directory", encoding="utf-8")
    fallback = tmp_path / "runtime"
    with _managed_sinks(
        tmp_path,
        config=LoggingConfig(logging.INFO, logging.INFO, None),
        home=home_file,
        cwd=cwd_file,
        fallback=fallback,
    ) as sinks:
        handlers = [
            handler
            for handler in sinks.logger.handlers
            if getattr(handler, "_metroliza_file_handler", False)
        ]
        assert len(handlers) == 1
        assert Path(handlers[0].baseFilename) == fallback / "metroliza" / "metroliza.log"


def test_unmanaged_handler_is_independent(tmp_path):
    stream = io.StringIO()
    with _managed_sinks(tmp_path) as sinks:
        unmanaged = logging.StreamHandler(stream)
        formatter = logging.Formatter("%(message)s")
        unmanaged.setFormatter(formatter)
        sinks.logger.addHandler(unmanaged)
        sinks.logger.info("unmanaged-visible")
        managed = _outputs(sinks)

        assert unmanaged in sinks.logger.handlers
        assert unmanaged.formatter is formatter
        assert stream.getvalue() == "unmanaged-visible\n"
        assert all("unmanaged-visible" not in output for output in managed)


def test_new_handlers_are_safe_before_attachment(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_cwd = tmp_path / "project"
    fake_cwd.mkdir()
    logger = logging.getLogger(f"metroliza.order.{uuid.uuid4().hex}")
    _close_handlers(logger)
    logger.propagate = False
    observed = []
    original_add = logger.addHandler

    def observe_add(handler):
        observed.append(
            (
                getattr(handler, "_metroliza_file_handler", False)
                or getattr(handler, "_metroliza_console_handler", False),
                type(handler.formatter),
            )
        )
        original_add(handler)

    try:
        with patch(
            "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
        ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
            "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
        ), patch.object(logger, "addHandler", side_effect=observe_add):
            ensure_application_logging(
                config=LoggingConfig(logging.INFO, logging.INFO, logging.INFO)
            )
        assert len(observed) == 3
        assert all(managed and formatter is ManagedSafeFormatter for managed, formatter in observed)
    finally:
        _close_handlers(logger)


def test_unsafe_attached_handlers_are_detached_before_formatter_change(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_cwd = tmp_path / "project"
    fake_cwd.mkdir()
    home_log = fake_home / ".metroliza" / "metroliza.log"
    home_log.parent.mkdir()
    logger = logging.getLogger(f"metroliza.reharden.{uuid.uuid4().hex}")
    _close_handlers(logger)
    logger.propagate = False
    unsafe = logging.handlers.RotatingFileHandler(
        home_log,
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
        encoding="utf-8",
    )
    setattr(unsafe, "_metroliza_file_handler", True)
    unsafe.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(unsafe)
    reachability = []
    original_set = unsafe.setFormatter

    def observe_set(formatter):
        reachability.append(unsafe in logger.handlers)
        original_set(formatter)

    try:
        with patch(
            "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
        ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
            "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
        ), patch.object(unsafe, "setFormatter", side_effect=observe_set):
            ensure_application_logging(config=LoggingConfig(logging.INFO, logging.INFO, None))
        assert reachability and not any(reachability)
        assert type(unsafe.formatter) is ManagedSafeFormatter
    finally:
        _close_handlers(logger)


def test_repeated_and_concurrent_setup_is_idempotent(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_cwd = tmp_path / "project"
    fake_cwd.mkdir()
    logger = logging.getLogger(f"metroliza.concurrent.{uuid.uuid4().hex}")
    _close_handlers(logger)
    logger.propagate = False
    config = LoggingConfig(logging.INFO, logging.INFO, logging.INFO)
    barrier = threading.Barrier(4)
    failures = []

    def configure():
        try:
            barrier.wait()
            ensure_application_logging(config=config)
        except BaseException as exc:
            failures.append(type(exc).__name__)

    try:
        with patch(
            "metroliza.shared.logging_utils.logging.getLogger", return_value=logger
        ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
            "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
        ):
            workers = [threading.Thread(target=configure) for _ in range(4)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
            first = tuple(logger.handlers)
            ensure_application_logging(config=config)

        assert not failures
        assert not any(worker.is_alive() for worker in workers)
        assert tuple(logger.handlers) == first
        assert len(first) == 3
        assert len({id(handler) for handler in first}) == 3
        assert all(type(handler.formatter) is ManagedSafeFormatter for handler in first)
    finally:
        _close_handlers(logger)


def test_aliased_primary_paths_reuse_one_handler(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_cwd = fake_home / ".metroliza"
    fake_cwd.mkdir()
    with _managed_sinks(
        tmp_path,
        config=LoggingConfig(logging.INFO, logging.INFO, None),
        home=fake_home,
        cwd=fake_cwd,
    ) as sinks:
        first = tuple(sinks.logger.handlers)
        with patch(
            "metroliza.shared.logging_utils.logging.getLogger", return_value=sinks.logger
        ), patch("metroliza.shared.logging_utils.Path.home", return_value=fake_home), patch(
            "metroliza.shared.logging_utils.Path.cwd", return_value=fake_cwd
        ):
            ensure_application_logging(
                config=LoggingConfig(logging.INFO, logging.INFO, None)
            )
        assert tuple(sinks.logger.handlers) == first
        assert len(first) == 1


def test_resolve_logging_config_preserves_level_contract():
    environment = {
        "METROLIZA_LOG_LEVEL": "INFO",
        "METROLIZA_FILE_LOG_LEVEL": "ERROR",
        "METROLIZA_CONSOLE_LOG_LEVEL": "WARNING",
        "METROLIZA_SUPPORT_BUILD": "0",
    }
    with patch.dict("os.environ", environment, clear=False):
        config = resolve_logging_config()

    assert config == LoggingConfig(logging.INFO, logging.ERROR, logging.WARNING)


def test_source_classification_is_closed_and_does_not_emit_source():
    marker = f"generated-{uuid.uuid4().hex}"
    formatter = ManagedSafeFormatter()
    outputs = []
    expected = (
        (f"metroliza.{marker}", SourceClass.APPLICATION.value),
        (f"thirdparty.{marker}", SourceClass.EXTERNAL.value),
        (None, SourceClass.UNKNOWN.value),
    )
    for name, source_class in expected:
        record = logging.LogRecord("placeholder", logging.INFO, __file__, 1, marker, (), None)
        record.name = name
        output = formatter.format(record)
        outputs.append(output)
        assert f'"source_class":"{source_class}"' in output

    _assert_marker_absent(marker, outputs)
