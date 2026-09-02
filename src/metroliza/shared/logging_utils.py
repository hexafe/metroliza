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
_REDACTED = "[REDACTED]"
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
        "dsn",
        "connection_string",
        "sql",
        "query",
        "source",
        "path",
    }
)
_URI_USERINFO_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]{0,31}://|//)[^\s/@]+@")
_AUTHORIZATION_RE = re.compile(
    r"(?i)\b((?:proxy[-_ ]?)?authorization\s*[:=]\s*)"
    r"(?:[\"']?(?:bearer|basic)\s+)?[^\s,;\"']+"
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


def redact_log_text(value: object) -> str:
    """Redact explicit sensitive labels and connection forms from bounded text.

    This deliberately is not an arbitrary-secret detector. Unlabelled values are
    retained, while exception objects and traceback fields are handled separately
    by :class:`RedactingFormatter`.
    """
    text = _bounded_text(value)
    text = _URI_USERINFO_RE.sub(lambda match: f"{match.group(1)}{_REDACTED}@", text)
    text = _AUTHORIZATION_RE.sub(lambda match: f"{match.group(1)}{_REDACTED}", text)
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
    if type(value) is not str:
        return None
    normalized = re.sub(r"[-\s]+", "_", value.strip().casefold())
    return normalized if normalized in _SENSITIVE_MAPPING_KEYS else None


def _safe_argument(value: object) -> object:
    if isinstance(value, BaseException):
        return summarize_exception(value)
    return value


def _safe_format_arguments(arguments: object) -> object:
    if isinstance(arguments, tuple):
        return tuple(_safe_argument(value) for value in arguments)
    if isinstance(arguments, Mapping):
        try:
            return {
                key: _REDACTED if _normalized_key(key) else _safe_argument(value)
                for key, value in arguments.items()
            }
        except BaseException:
            return {}
    return arguments


class RedactingFormatter(logging.Formatter):
    """Format an isolated record and redact the final managed-handler output."""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy(record)
        structural: list[str] = []

        if isinstance(safe_record.msg, BaseException):
            safe_record.msg = summarize_exception(safe_record.msg)
            safe_record.args = ()
        else:
            safe_record.args = _safe_format_arguments(safe_record.args)

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


def _configure_file_handlers(logger: logging.Logger, formatter: logging.Formatter, file_level: int) -> None:
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
    target_resolved_paths = {path.resolve() for path in target_paths}

    existing_file_handlers = {
        Path(handler.baseFilename).resolve(): handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler) and getattr(handler, 'baseFilename', None)
    }

    for handler in list(logger.handlers):
        if not isinstance(handler, logging.FileHandler) or not getattr(handler, 'baseFilename', None):
            continue

        resolved_path = Path(handler.baseFilename).resolve()
        is_metroliza_handler = getattr(handler, '_metroliza_file_handler', False) or resolved_path.name == LOG_FILE_NAME
        if is_metroliza_handler and resolved_path not in target_resolved_paths:
            logger.removeHandler(handler)
            handler.close()

    configured_handlers = 0
    for index, log_path in enumerate([*target_paths, fallback_log_path]):
        if index >= len(target_paths) and configured_handlers > 0:
            break

        resolved_path = log_path.resolve()
        handler = existing_file_handlers.get(resolved_path)
        requires_rotation_handler = not isinstance(handler, logging.handlers.RotatingFileHandler)
        has_expected_rotation = (
            isinstance(handler, logging.handlers.RotatingFileHandler)
            and handler.maxBytes == _FILE_MAX_BYTES
            and handler.backupCount == _FILE_BACKUP_COUNT
        )

        if handler is None or requires_rotation_handler or not has_expected_rotation:
            if handler is not None:
                logger.removeHandler(handler)
                handler.close()
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                handler = logging.handlers.RotatingFileHandler(
                    str(log_path),
                    maxBytes=_FILE_MAX_BYTES,
                    backupCount=_FILE_BACKUP_COUNT,
                    encoding='utf-8',
                )
            except OSError:
                continue
            setattr(handler, '_metroliza_file_handler', True)
            logger.addHandler(handler)
        else:
            setattr(handler, '_metroliza_file_handler', True)

        handler.setLevel(file_level)
        handler.setFormatter(formatter)
        configured_handlers += 1


def _configure_console_handler(logger: logging.Logger, formatter: logging.Formatter, console_level: int | None) -> None:
    """Ensure a managed console handler matches the requested configuration.

    Args:
        logger: Logger to modify.
        formatter: Formatter to apply to the managed console handler.
        console_level: Desired console threshold, or ``None`` to remove the
            managed console handler.
    """

    console_handler = next((
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        and getattr(handler, '_metroliza_console_handler', False)
    ), None)

    if console_level is None:
        if console_handler is not None:
            logger.removeHandler(console_handler)
        return

    if console_handler is None:
        console_handler = logging.StreamHandler()
        setattr(console_handler, '_metroliza_console_handler', True)
        logger.addHandler(console_handler)

    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)


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
    logger = logging.getLogger()
    formatter = RedactingFormatter(
        '%(asctime)s %(levelname)s [%(name)s] [%(threadName)s] %(message)s'
    )

    resolved_config = config or resolve_logging_config()
    if level is not None and config is None:
        resolved_config = LoggingConfig(global_level=level, file_level=level, console_level=resolved_config.console_level)
    logger.setLevel(resolved_config.global_level)

    _configure_file_handlers(logger, formatter, resolved_config.file_level)
    _configure_console_handler(logger, formatter, resolved_config.console_level)

    return resolved_config
