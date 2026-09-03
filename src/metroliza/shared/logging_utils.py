"""Safe managed logging configuration for Metroliza."""

from __future__ import annotations

import datetime as dt
import logging
import logging.handlers
import math
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from metroliza.shared.diagnostic_events import (
    DiagnosticEventValidationError,
    ExceptionDiagnosticEvent,
    InvalidDiagnosticEvent,
    LegacyLogSuppressedEvent,
    SourceClass,
    serialize_diagnostic_event,
)
from metroliza.shared.env_utils import parse_bool


LOG_FILE_NAME = "metroliza.log"
_GLOBAL_LEVEL_ENV = "METROLIZA_LOG_LEVEL"
_FILE_LEVEL_ENV = "METROLIZA_FILE_LOG_LEVEL"
_CONSOLE_LEVEL_ENV = "METROLIZA_CONSOLE_LOG_LEVEL"
_SUPPORT_BUILD_ENV = "METROLIZA_SUPPORT_BUILD"
_FILE_MAX_BYTES = 10 * 1024 * 1024
_FILE_BACKUP_COUNT = 7
_LOGGING_SETUP_LOCK = threading.RLock()
_LEVEL_NAMES = {
    logging.NOTSET: "NOTSET",
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}
_APP_LOGGER_PREFIXES = ("metroliza", "modules")
_STRUCTURED_EVENT_TYPES = (
    LegacyLogSuppressedEvent,
    InvalidDiagnosticEvent,
    ExceptionDiagnosticEvent,
)


@dataclass(frozen=True)
class LoggingConfig:
    """Resolved root, file, and optional console logging levels."""

    global_level: int
    file_level: int
    console_level: int | None


def _record_attribute(record: logging.LogRecord, name: str, default: object) -> object:
    try:
        return object.__getattribute__(record, name)
    except BaseException:
        return default


def _safe_timestamp(record: logging.LogRecord) -> str:
    created = _record_attribute(record, "created", None)
    try:
        finite_created = type(created) in (int, float) and math.isfinite(created)
    except (OverflowError, TypeError, ValueError):
        finite_created = False
    if not finite_created:
        created = time.time()
    try:
        timestamp = dt.datetime.fromtimestamp(created, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        timestamp = dt.datetime.fromtimestamp(time.time(), tz=dt.UTC)
    milliseconds = timestamp.microsecond // 1000
    return f"{timestamp:%Y-%m-%dT%H:%M:%S}.{milliseconds:03d}Z"


def _safe_level(record: logging.LogRecord) -> str:
    level = _record_attribute(record, "levelno", None)
    return _LEVEL_NAMES.get(level, "UNKNOWN") if type(level) is int else "UNKNOWN"


def _source_class(record: logging.LogRecord) -> SourceClass:
    name = _record_attribute(record, "name", None)
    if type(name) is not str or not name:
        return SourceClass.UNKNOWN
    for prefix in _APP_LOGGER_PREFIXES:
        if name == prefix or name.startswith(f"{prefix}."):
            return SourceClass.APPLICATION
    return SourceClass.EXTERNAL


def _has_empty_arguments(record: logging.LogRecord) -> bool:
    arguments = _record_attribute(record, "args", None)
    return arguments is None or (type(arguments) is tuple and len(arguments) == 0)


def _safe_event(record: logging.LogRecord) -> object:
    source_class = _source_class(record)
    message = _record_attribute(record, "msg", None)
    if type(message) not in _STRUCTURED_EVENT_TYPES:
        return LegacyLogSuppressedEvent(source_class)
    if not _has_empty_arguments(record):
        return InvalidDiagnosticEvent(source_class)
    try:
        serialize_diagnostic_event(message)
    except DiagnosticEventValidationError:
        return InvalidDiagnosticEvent(source_class)
    return message


class ManagedSafeFormatter(logging.Formatter):
    """Render only closed diagnostic events and fixed legacy suppression output."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = _safe_timestamp(record)
        level = _safe_level(record)
        event = _safe_event(record)
        try:
            serialized = serialize_diagnostic_event(event)
        except DiagnosticEventValidationError:
            serialized = serialize_diagnostic_event(InvalidDiagnosticEvent(SourceClass.UNKNOWN))
        return f"{timestamp} {level} {serialized}"


class _ManagedTerminalHandler(logging.NullHandler):
    """Consume records without rendering when no managed sink is available."""


def _is_truthy(raw_value: str | None) -> bool:
    return parse_bool(raw_value, default=False)


def _parse_level(raw_value: str | None, *, fallback: int) -> int:
    if raw_value is None or str(raw_value).strip() == "":
        return fallback
    normalized = str(raw_value).strip().upper()
    if normalized.isdigit() or (normalized.startswith("-") and normalized[1:].isdigit()):
        return int(normalized)
    level_value = logging.getLevelName(normalized)
    return level_value if isinstance(level_value, int) else fallback


def _parse_optional_level(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    stripped = str(raw_value).strip()
    if not stripped or stripped.lower() in {"off", "none", "disable", "disabled", "null"}:
        return None
    return _parse_level(stripped, fallback=logging.INFO)


def resolve_logging_config() -> LoggingConfig:
    """Resolve the existing environment-driven logging level contract."""
    default_global = logging.DEBUG if _is_truthy(os.getenv(_SUPPORT_BUILD_ENV)) else logging.INFO
    global_level = _parse_level(os.getenv(_GLOBAL_LEVEL_ENV), fallback=default_global)
    file_level = _parse_level(os.getenv(_FILE_LEVEL_ENV), fallback=global_level)
    console_level = _parse_optional_level(os.getenv(_CONSOLE_LEVEL_ENV))
    return LoggingConfig(global_level, file_level, console_level)


def _prepare_managed_handler(
    handler: logging.Handler,
    *,
    marker: str,
    level: int,
    formatter: ManagedSafeFormatter,
) -> None:
    setattr(handler, marker, True)
    handler.setLevel(level)
    handler.setFormatter(formatter)


def _add_managed_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    *,
    marker: str,
    level: int,
    formatter: ManagedSafeFormatter,
) -> None:
    _prepare_managed_handler(handler, marker=marker, level=level, formatter=formatter)
    logger.addHandler(handler)


def _harden_attached_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    *,
    marker: str,
    level: int,
    formatter: ManagedSafeFormatter,
) -> None:
    if type(handler.formatter) is ManagedSafeFormatter:
        setattr(handler, marker, True)
        handler.setLevel(level)
        return
    handler.acquire()
    try:
        logger.removeHandler(handler)
        _prepare_managed_handler(handler, marker=marker, level=level, formatter=formatter)
        logger.addHandler(handler)
    finally:
        handler.release()


def _remove_and_close_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    formatter: ManagedSafeFormatter,
) -> None:
    handler.acquire()
    try:
        logger.removeHandler(handler)
        handler.setFormatter(formatter)
        handler.close()
    finally:
        handler.release()


def _has_expected_rotation(handler: logging.Handler | None) -> bool:
    return (
        isinstance(handler, logging.handlers.RotatingFileHandler)
        and handler.maxBytes == _FILE_MAX_BYTES
        and handler.backupCount == _FILE_BACKUP_COUNT
    )


def _collect_managed_file_handlers(
    logger: logging.Logger,
    allowed_paths: set[Path],
    formatter: ManagedSafeFormatter,
) -> dict[Path, logging.FileHandler]:
    by_path: dict[Path, logging.FileHandler] = {}
    for handler in tuple(logger.handlers):
        if not isinstance(handler, logging.FileHandler) or not getattr(
            handler, "baseFilename", None
        ):
            continue
        resolved = Path(handler.baseFilename).resolve()
        managed = getattr(handler, "_metroliza_file_handler", False) or (
            resolved.name == LOG_FILE_NAME
        )
        if not managed:
            continue
        if resolved not in allowed_paths:
            _remove_and_close_handler(logger, handler, formatter)
            continue
        previous = by_path.get(resolved)
        if previous is None:
            by_path[resolved] = handler
        elif _has_expected_rotation(handler) and not _has_expected_rotation(previous):
            _remove_and_close_handler(logger, previous, formatter)
            by_path[resolved] = handler
        else:
            _remove_and_close_handler(logger, handler, formatter)
    return by_path


def _ensure_file_handler(
    logger: logging.Logger,
    path: Path,
    handler: logging.FileHandler | None,
    formatter: ManagedSafeFormatter,
    level: int,
) -> bool:
    if not _has_expected_rotation(handler):
        if handler is not None:
            _remove_and_close_handler(logger, handler, formatter)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=_FILE_MAX_BYTES,
                backupCount=_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            return False
        _add_managed_handler(
            logger,
            handler,
            marker="_metroliza_file_handler",
            level=level,
            formatter=formatter,
        )
        return True
    assert handler is not None
    _harden_attached_handler(
        logger,
        handler,
        marker="_metroliza_file_handler",
        level=level,
        formatter=formatter,
    )
    return True


def _configure_file_handlers(
    logger: logging.Logger,
    formatter: ManagedSafeFormatter,
    level: int,
) -> bool:
    fallback = Path(tempfile.gettempdir()) / "metroliza" / LOG_FILE_NAME
    primary_paths = [Path.home() / ".metroliza" / LOG_FILE_NAME, Path.cwd() / LOG_FILE_NAME]
    primary_by_resolved = {path.resolve(): path for path in primary_paths}
    fallback_resolved = fallback.resolve()
    existing = _collect_managed_file_handlers(
        logger,
        set(primary_by_resolved) | {fallback_resolved},
        formatter,
    )
    configured = 0
    for resolved, path in primary_by_resolved.items():
        if _ensure_file_handler(logger, path, existing.get(resolved), formatter, level):
            configured += 1
    fallback_handler = existing.get(fallback_resolved)
    if configured:
        if fallback_handler is not None and fallback_resolved not in primary_by_resolved:
            _remove_and_close_handler(logger, fallback_handler, formatter)
        return True
    return _ensure_file_handler(logger, fallback, fallback_handler, formatter, level)


def _configure_console_handler(
    logger: logging.Logger,
    formatter: ManagedSafeFormatter,
    level: int | None,
) -> bool:
    handlers = [
        handler
        for handler in tuple(logger.handlers)
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        and getattr(handler, "_metroliza_console_handler", False)
    ]
    if level is None:
        for handler in handlers:
            _remove_and_close_handler(logger, handler, formatter)
        return False
    selected = next(
        (handler for handler in handlers if type(handler.formatter) is ManagedSafeFormatter),
        handlers[0] if handlers else None,
    )
    for duplicate in handlers:
        if duplicate is not selected:
            _remove_and_close_handler(logger, duplicate, formatter)
    if selected is None:
        _add_managed_handler(
            logger,
            logging.StreamHandler(),
            marker="_metroliza_console_handler",
            level=level,
            formatter=formatter,
        )
    else:
        _harden_attached_handler(
            logger,
            selected,
            marker="_metroliza_console_handler",
            level=level,
            formatter=formatter,
        )
    return True


def _configure_terminal_handler(
    logger: logging.Logger,
    formatter: ManagedSafeFormatter,
    *,
    enabled: bool,
) -> None:
    handlers = [
        handler
        for handler in tuple(logger.handlers)
        if getattr(handler, "_metroliza_terminal_handler", False)
    ]
    selected = next(
        (handler for handler in handlers if type(handler) is _ManagedTerminalHandler),
        None,
    )
    for duplicate in handlers:
        if duplicate is not selected:
            _remove_and_close_handler(logger, duplicate, formatter)
    if not enabled:
        if selected is not None:
            _remove_and_close_handler(logger, selected, formatter)
        return
    if selected is None:
        _add_managed_handler(
            logger,
            _ManagedTerminalHandler(),
            marker="_metroliza_terminal_handler",
            level=logging.NOTSET,
            formatter=formatter,
        )
    else:
        _harden_attached_handler(
            logger,
            selected,
            marker="_metroliza_terminal_handler",
            level=logging.NOTSET,
            formatter=formatter,
        )


def ensure_application_logging(
    config: LoggingConfig | None = None,
    level: int | None = None,
) -> LoggingConfig:
    """Attach only fully prepared managed handlers and preserve unmanaged handlers."""
    with _LOGGING_SETUP_LOCK:
        logger = logging.getLogger()
        resolved = config or resolve_logging_config()
        if level is not None and config is None:
            resolved = LoggingConfig(level, level, resolved.console_level)
        logger.setLevel(resolved.global_level)
        formatter = ManagedSafeFormatter()
        _configure_terminal_handler(logger, formatter, enabled=True)
        file_available = _configure_file_handlers(logger, formatter, resolved.file_level)
        console_available = _configure_console_handler(logger, formatter, resolved.console_level)
        _configure_terminal_handler(
            logger,
            formatter,
            enabled=not (file_available or console_available),
        )
        return resolved
