"""Utilities for resolving and applying application-wide logging configuration.

This module centralizes environment-driven log level resolution and handler setup
for Metroliza's root logger, including rotating file sinks and optional console
output.
"""

import logging
import logging.handlers
import os
import re
import tempfile
import threading
from collections.abc import Mapping
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from metroliza.shared.env_utils import parse_bool


LOG_FILE_NAME = "metroliza.log"
_GLOBAL_LEVEL_ENV = "METROLIZA_LOG_LEVEL"
_FILE_LEVEL_ENV = "METROLIZA_FILE_LOG_LEVEL"
_CONSOLE_LEVEL_ENV = "METROLIZA_CONSOLE_LOG_LEVEL"
_SUPPORT_BUILD_ENV = "METROLIZA_SUPPORT_BUILD"
_FILE_MAX_BYTES = 10 * 1024 * 1024
_FILE_BACKUP_COUNT = 7
_MAX_LOG_INPUT = 16_384
_MAX_LOG_OUTPUT = 16_384
_MAX_EXCEPTION_NODES = 32
_MAX_TRACEBACK_FRAMES = 64
_MAX_FORMAT_ARGUMENT_DEPTH = 8
_MAX_FORMAT_ARGUMENT_NODES = 128
_REDACTED = "[REDACTED]"
_UNSAFE_LOG_ARGUMENTS = "[unsafe log arguments]"
_UNSAFE_FORMAT_ARGUMENTS = object()
_LOGGING_SETUP_LOCK = threading.RLock()
_SENSITIVE_MAPPING_KEYS = frozenset(
    {
        "password",
        "passphrase",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "private_key",
        "secret_key",
        "credential",
        "authorization",
        "proxy_authorization",
        "dsn",
        "connection_string",
        "sql",
        "query",
        "source",
        "path",
    }
)
_URI_USERINFO_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]{0,31}://|//)[^\s/@]+@")
_AUTHORIZATION_FIELD_RE = re.compile(
    r"(?i)((?:\\?[\"'])?\b(?:proxy[-_ ]?)?authorization\b"
    r"(?:\\?[\"'])?\s*[:=]\s*)"
)
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[^\s,;\"']+")
_STRUCTURED_LABEL_RE = re.compile(
    r"(?i)([\"']?\b(?:"
    r"dsn|connection[-_ ]?string|sql|query|source|path"
    r")\b[\"']?\s*[:=]\s*)(?!\[REDACTED\])"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n]+)"
)
_VALUE_LABEL_RE = re.compile(
    r"(?i)([\"']?\b(?:"
    r"password|passphrase|token|access[-_ ]?token|refresh[-_ ]?token|"
    r"api[-_ ]?key|private[-_ ]?key|secret[-_ ]?key|credential"
    r")\b[\"']?\s*[:=]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;&]+)"
)


def _bounded_text(value: object) -> str:
    """Return bounded text without allowing broken formatting to escape."""
    try:
        text = value if type(value) is str else str(value)
    except BaseException:
        return "[unprintable log value]"
    if len(text) <= _MAX_LOG_INPUT:
        return text
    return f"{text[:_MAX_LOG_INPUT]}...[truncated]"


def _redact_authorization_tail(text: str) -> str:
    """Discard content after the first unredacted Authorization field boundary."""
    search_from = 0
    while match := _AUTHORIZATION_FIELD_RE.search(text, search_from):
        field_end = match.end()
        if text.startswith(_REDACTED, field_end):
            search_from = field_end + len(_REDACTED)
            continue
        return f"{text[:field_end]}{_REDACTED}"
    return text


def redact_log_text(value: object) -> str:
    """Redact explicit sensitive labels and connection forms from bounded text.

    This deliberately is not an arbitrary-secret detector. Unlabelled values are
    retained, while exception objects and traceback fields are handled separately
    by :class:`RedactingFormatter`.
    """
    text = _bounded_text(value)
    text = _URI_USERINFO_RE.sub(lambda match: f"{match.group(1)}{_REDACTED}@", text)
    text = _redact_authorization_tail(text)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
    text = _STRUCTURED_LABEL_RE.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
    text = _VALUE_LABEL_RE.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
    if len(text) <= _MAX_LOG_OUTPUT:
        return text
    return f"{text[:_MAX_LOG_OUTPUT]}...[truncated]"


def _safe_exception_type(exception: BaseException) -> str:
    try:
        name = type(exception).__name__
    except BaseException:
        return "Exception"
    if type(name) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name):
        return "Exception"
    return name


def _exception_attribute(exception: BaseException, name: str, default: object) -> object:
    try:
        return object.__getattribute__(exception, name)
    except BaseException:
        return default


def _traceback_frame_count(exception: BaseException) -> int:
    traceback = _exception_attribute(exception, "__traceback__", None)
    count = 0
    seen: set[int] = set()
    while traceback is not None and count < _MAX_TRACEBACK_FRAMES:
        identity = id(traceback)
        if identity in seen:
            break
        seen.add(identity)
        count += 1
        try:
            traceback = traceback.tb_next
        except BaseException:
            break
    return count


def _linked_exception(exception: BaseException) -> BaseException | None:
    cause = _exception_attribute(exception, "__cause__", None)
    context = _exception_attribute(exception, "__context__", None)
    suppressed = _exception_attribute(exception, "__suppress_context__", False) is True
    if isinstance(cause, BaseException):
        return cause
    if not suppressed and isinstance(context, BaseException):
        return context
    return None


def summarize_exception(exception: BaseException) -> str:
    """Describe exception structure without reading messages, notes, or traceback text."""
    if not isinstance(exception, BaseException):
        return "exception_type=Exception; chain=absent; group=absent; traceback=absent"

    pending = [exception]
    seen: set[int] = set()
    types: list[str] = []
    chain_present = False
    group_present = False
    group_children = 0
    traceback_frames = 0
    notes_present = False

    while pending and len(seen) < _MAX_EXCEPTION_NODES:
        current = pending.pop()
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        exception_type = _safe_exception_type(current)
        if exception_type not in types and len(types) < 8:
            types.append(exception_type)
        traceback_frames = min(
            _MAX_TRACEBACK_FRAMES, traceback_frames + _traceback_frame_count(current)
        )

        notes = _exception_attribute(current, "__notes__", ())
        if isinstance(notes, (list, tuple)) and notes:
            notes_present = True

        linked = _linked_exception(current)
        if linked is not None:
            chain_present = True
            pending.append(linked)

        children = _exception_attribute(current, "exceptions", ())
        if isinstance(children, tuple) and children:
            group_present = True
            for child in children[: _MAX_EXCEPTION_NODES - len(seen)]:
                if isinstance(child, BaseException):
                    pending.append(child)
                    group_children += 1

    traceback_state = "present" if traceback_frames else "absent"
    return (
        f"exception_types={','.join(types) or 'Exception'}; "
        f"chain={'present' if chain_present else 'absent'}; "
        f"group={'present' if group_present else 'absent'}; "
        f"group_children={group_children}; traceback={traceback_state}; "
        f"traceback_frames={traceback_frames}; "
        f"notes={'present' if notes_present else 'absent'}"
    )


def _normalized_key(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    safe_value = value if type(value) is str else str.__str__(value)
    normalized = re.sub(r"[-\s]+", "_", safe_value.strip().casefold())
    return normalized if normalized in _SENSITIVE_MAPPING_KEYS else None


@dataclass
class _ArgumentTraversal:
    active_containers: set[int]
    nodes: int = 0


def _consume_argument_node(state: _ArgumentTraversal) -> None:
    state.nodes += 1
    if state.nodes > _MAX_FORMAT_ARGUMENT_NODES:
        raise ValueError("log argument node budget exceeded")


def _sanitize_argument_mapping(
    value: Mapping[object, object], *, depth: int, state: _ArgumentTraversal
) -> dict[object, object]:
    sanitized: dict[object, object] = {}
    for key, item in value.items():
        safe_key = _sanitize_format_argument(key, depth=depth + 1, state=state)
        if _normalized_key(key):
            _consume_argument_node(state)
            safe_item = _REDACTED
        else:
            safe_item = _sanitize_format_argument(item, depth=depth + 1, state=state)
        sanitized[safe_key] = safe_item
    return sanitized


def _sanitize_format_argument(value: object, *, depth: int, state: _ArgumentTraversal) -> object:
    if depth > _MAX_FORMAT_ARGUMENT_DEPTH:
        raise ValueError("log argument depth exceeded")
    _consume_argument_node(state)
    if isinstance(value, str):
        return value if type(value) is str else str.__str__(value)
    if isinstance(value, BaseException):
        return summarize_exception(value)
    if not isinstance(value, (list, tuple, Mapping)):
        return value

    identity = id(value)
    if identity in state.active_containers:
        raise ValueError("cyclic log arguments")
    state.active_containers.add(identity)
    try:
        if isinstance(value, list):
            return [_sanitize_format_argument(item, depth=depth + 1, state=state) for item in value]
        if isinstance(value, tuple):
            return tuple(
                _sanitize_format_argument(item, depth=depth + 1, state=state) for item in value
            )
        return _sanitize_argument_mapping(value, depth=depth, state=state)
    finally:
        state.active_containers.discard(identity)


def _safe_format_arguments(arguments: object) -> object:
    try:
        return _sanitize_format_argument(
            arguments,
            depth=0,
            state=_ArgumentTraversal(active_containers=set()),
        )
    except BaseException:
        return _UNSAFE_FORMAT_ARGUMENTS


def _sanitize_record_message_and_arguments(record: logging.LogRecord) -> None:
    if isinstance(record.msg, BaseException):
        record.msg = summarize_exception(record.msg)
        record.args = ()
        return

    if isinstance(record.msg, (list, tuple, Mapping)):
        record.msg = _safe_format_arguments(record.msg)
    safe_arguments = _safe_format_arguments(record.args)
    if record.msg is _UNSAFE_FORMAT_ARGUMENTS or safe_arguments is _UNSAFE_FORMAT_ARGUMENTS:
        record.msg = _UNSAFE_LOG_ARGUMENTS
        record.args = ()
    else:
        record.args = safe_arguments


class RedactingFormatter(logging.Formatter):
    """Format an isolated record and redact the final managed-handler output."""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy(record)
        structural: list[str] = []
        _sanitize_record_message_and_arguments(safe_record)

        if safe_record.exc_info:
            exception = safe_record.exc_info[1]
            if isinstance(exception, BaseException):
                structural.append(summarize_exception(exception))
            else:
                structural.append("exception=present")
        elif safe_record.exc_text:
            structural.append("cached_exception_text=present")
        if safe_record.stack_info:
            structural.append("stack_info=present")

        safe_record.exc_info = None
        safe_record.exc_text = None
        safe_record.stack_info = None
        try:
            rendered = super().format(safe_record)
        except BaseException:
            safe_record.msg = "log_message=[unformattable]"
            safe_record.args = ()
            rendered = super().format(safe_record)

        rendered = redact_log_text(rendered)
        if structural:
            suffix = f" [{'; '.join(structural)}]"
            if len(rendered) + len(suffix) > _MAX_LOG_OUTPUT:
                truncation = "...[truncated]"
                budget = max(0, _MAX_LOG_OUTPUT - len(suffix) - len(truncation))
                rendered = f"{rendered[:budget]}{truncation}"
            rendered = f"{rendered}{suffix}"
        return redact_log_text(rendered)


@dataclass(frozen=True)
class LoggingConfig:
    """Resolved logging levels for global, file, and console handlers.

    Attributes:
        global_level: Root logger level that gates all log records.
        file_level: Per-file-handler threshold for persisted logs.
        console_level: Stream handler threshold, or ``None`` to disable
            console logging.
    """

    global_level: int
    file_level: int
    console_level: int | None


def _is_truthy(raw_value: str | None) -> bool:
    return parse_bool(raw_value, default=False)


def _parse_level(raw_value: str | None, *, fallback: int) -> int:
    if raw_value is None or str(raw_value).strip() == "":
        return fallback

    normalized = str(raw_value).strip().upper()
    if normalized.isdigit() or (normalized.startswith("-") and normalized[1:].isdigit()):
        return int(normalized)

    level_value = logging.getLevelName(normalized)
    if isinstance(level_value, int):
        return level_value
    return fallback


def _parse_optional_level(raw_value: str | None) -> int | None:
    """Parse a potentially disabled log level for optional console logging.

    Args:
        raw_value: Raw environment value.

    Returns:
        An integer logging level, or ``None`` when logging should be disabled.

    Notes:
        Values ``off``, ``none``, ``disable``, ``disabled``, and ``null`` are
        treated as explicit disablement signals.
    """

    if raw_value is None:
        return None

    stripped = str(raw_value).strip()
    if stripped == "":
        return None

    if stripped.lower() in {"off", "none", "disable", "disabled", "null"}:
        return None

    return _parse_level(stripped, fallback=logging.INFO)


def resolve_logging_config() -> LoggingConfig:
    """Resolve effective logging configuration from environment variables.

    Returns:
        A :class:`LoggingConfig` with resolved global, file, and console levels.

    Notes:
        Precedence is:

        1. ``METROLIZA_LOG_LEVEL`` for the root logger level.
        2. ``METROLIZA_FILE_LOG_LEVEL`` for file handlers, falling back to the
           resolved global level.
        3. ``METROLIZA_CONSOLE_LOG_LEVEL`` for console handlers, where
           ``off/none/disable/disabled/null`` disables console output.

        When ``METROLIZA_LOG_LEVEL`` is unset, support builds
        (``METROLIZA_SUPPORT_BUILD`` truthy) default to ``DEBUG`` and other
        builds default to ``INFO``.
    """

    default_global = logging.DEBUG if _is_truthy(os.getenv(_SUPPORT_BUILD_ENV)) else logging.INFO
    global_level = _parse_level(os.getenv(_GLOBAL_LEVEL_ENV), fallback=default_global)
    file_level = _parse_level(os.getenv(_FILE_LEVEL_ENV), fallback=global_level)
    console_level = _parse_optional_level(os.getenv(_CONSOLE_LEVEL_ENV))
    return LoggingConfig(global_level=global_level, file_level=file_level, console_level=console_level)


def _prepare_managed_handler(
    handler: logging.Handler,
    *,
    marker: str,
    level: int,
    formatter: RedactingFormatter,
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
    formatter: RedactingFormatter,
) -> None:
    _prepare_managed_handler(handler, marker=marker, level=level, formatter=formatter)
    logger.addHandler(handler)


def _harden_attached_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    *,
    marker: str,
    level: int,
    formatter: RedactingFormatter,
) -> None:
    if type(handler.formatter) is RedactingFormatter:
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
    formatter: RedactingFormatter,
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
    formatter: RedactingFormatter,
) -> dict[Path, logging.FileHandler]:
    handlers_by_path: dict[Path, logging.FileHandler] = {}
    for handler in list(logger.handlers):
        if not isinstance(handler, logging.FileHandler) or not getattr(
            handler, "baseFilename", None
        ):
            continue

        resolved_path = Path(handler.baseFilename).resolve()
        is_managed = (
            getattr(handler, "_metroliza_file_handler", False)
            or resolved_path.name == LOG_FILE_NAME
        )
        if not is_managed:
            continue
        if resolved_path not in allowed_paths:
            _remove_and_close_handler(logger, handler, formatter)
            continue

        current = handlers_by_path.get(resolved_path)
        if current is None:
            handlers_by_path[resolved_path] = handler
        elif _has_expected_rotation(handler) and not _has_expected_rotation(current):
            _remove_and_close_handler(logger, current, formatter)
            handlers_by_path[resolved_path] = handler
        else:
            _remove_and_close_handler(logger, handler, formatter)
    return handlers_by_path


def _ensure_file_handler(
    logger: logging.Logger,
    log_path: Path,
    handler: logging.FileHandler | None,
    formatter: RedactingFormatter,
    file_level: int,
) -> bool:
    if not _has_expected_rotation(handler):
        if handler is not None:
            _remove_and_close_handler(logger, handler, formatter)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            rotating_handler = logging.handlers.RotatingFileHandler(
                str(log_path),
                maxBytes=_FILE_MAX_BYTES,
                backupCount=_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            return False
        _add_managed_handler(
            logger,
            rotating_handler,
            marker="_metroliza_file_handler",
            level=file_level,
            formatter=formatter,
        )
        return True

    assert handler is not None
    _harden_attached_handler(
        logger,
        handler,
        marker="_metroliza_file_handler",
        level=file_level,
        formatter=formatter,
    )
    return True


def _configure_file_handlers(
    logger: logging.Logger, formatter: RedactingFormatter, file_level: int
) -> None:
    """Ensure managed file handlers exist and use expected rotation settings.

    Existing Metroliza-managed handlers that target unexpected paths are removed.
    Handlers at target paths are replaced when they are not rotating handlers or
    when their rotation parameters differ from expected values.
    """

    fallback_log_path = Path(tempfile.gettempdir()) / 'metroliza' / LOG_FILE_NAME
    target_paths = [
        Path.home() / '.metroliza' / LOG_FILE_NAME,
        Path.cwd() / LOG_FILE_NAME,
    ]
    target_paths_by_resolved = {path.resolve(): path for path in target_paths}
    target_resolved_paths = set(target_paths_by_resolved)
    fallback_resolved_path = fallback_log_path.resolve()
    existing_file_handlers = _collect_managed_file_handlers(
        logger,
        target_resolved_paths | {fallback_resolved_path},
        formatter,
    )

    configured_handlers = 0
    for resolved_path, log_path in target_paths_by_resolved.items():
        handler = existing_file_handlers.get(resolved_path)
        if _ensure_file_handler(logger, log_path, handler, formatter, file_level):
            configured_handlers += 1

    fallback_handler = existing_file_handlers.get(fallback_resolved_path)
    if configured_handlers:
        if fallback_handler is not None and fallback_resolved_path not in target_resolved_paths:
            _remove_and_close_handler(logger, fallback_handler, formatter)
        return
    _ensure_file_handler(
        logger,
        fallback_log_path,
        fallback_handler,
        formatter,
        file_level,
    )


def _configure_console_handler(
    logger: logging.Logger,
    formatter: RedactingFormatter,
    console_level: int | None,
) -> None:
    """Ensure a managed console handler matches the requested configuration.

    Args:
        logger: Logger to modify.
        formatter: Formatter to apply to the managed console handler.
        console_level: Desired console threshold, or ``None`` to remove the
            managed console handler.
    """

    console_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        and getattr(handler, "_metroliza_console_handler", False)
    ]

    if console_level is None:
        for console_handler in console_handlers:
            _remove_and_close_handler(logger, console_handler, formatter)
        return

    console_handler = next(
        (handler for handler in console_handlers if type(handler.formatter) is RedactingFormatter),
        console_handlers[0] if console_handlers else None,
    )
    for duplicate in console_handlers:
        if duplicate is not console_handler:
            _remove_and_close_handler(logger, duplicate, formatter)

    if console_handler is None:
        console_handler = logging.StreamHandler()
        _add_managed_handler(
            logger,
            console_handler,
            marker="_metroliza_console_handler",
            level=console_level,
            formatter=formatter,
        )
    else:
        _harden_attached_handler(
            logger,
            console_handler,
            marker="_metroliza_console_handler",
            level=console_level,
            formatter=formatter,
        )


def ensure_application_logging(config: LoggingConfig | None = None, level: int | None = None):
    """Apply resolved logging configuration to the root logger.

    Args:
        config: Optional pre-resolved logging configuration. When omitted,
            :func:`resolve_logging_config` is used.
        level: Optional override for root and file levels when ``config`` is not
            provided. Console level still follows resolved environment behavior.

    Returns:
        The effective :class:`LoggingConfig` applied to logging.
    """
    with _LOGGING_SETUP_LOCK:
        logger = logging.getLogger()
        formatter = RedactingFormatter(
            "%(asctime)s %(levelname)s [%(name)s] [%(threadName)s] %(message)s"
        )

        resolved_config = config or resolve_logging_config()
        if level is not None and config is None:
            resolved_config = LoggingConfig(
                global_level=level,
                file_level=level,
                console_level=resolved_config.console_level,
            )
        logger.setLevel(resolved_config.global_level)

        _configure_file_handlers(logger, formatter, resolved_config.file_level)
        _configure_console_handler(logger, formatter, resolved_config.console_level)

        return resolved_config
