import logging
import logging.handlers
import os
from dataclasses import dataclass
from pathlib import Path


LOG_FILE_NAME = "metroliza.log"
_GLOBAL_LEVEL_ENV = "METROLIZA_LOG_LEVEL"
_FILE_LEVEL_ENV = "METROLIZA_FILE_LOG_LEVEL"
_CONSOLE_LEVEL_ENV = "METROLIZA_CONSOLE_LOG_LEVEL"
_SUPPORT_BUILD_ENV = "METROLIZA_SUPPORT_BUILD"
_FILE_MAX_BYTES = 10 * 1024 * 1024
_FILE_BACKUP_COUNT = 7


@dataclass(frozen=True)
class LoggingConfig:
    global_level: int
    file_level: int
    console_level: int | None


def _is_truthy(raw_value: str | None) -> bool:
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


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
    if raw_value is None:
        return None

    stripped = str(raw_value).strip()
    if stripped == "":
        return None

    if stripped.lower() in {"off", "none", "disable", "disabled", "null"}:
        return None

    return _parse_level(stripped, fallback=logging.INFO)


def resolve_logging_config() -> LoggingConfig:
    default_global = logging.DEBUG if _is_truthy(os.getenv(_SUPPORT_BUILD_ENV)) else logging.INFO
    global_level = _parse_level(os.getenv(_GLOBAL_LEVEL_ENV), fallback=default_global)
    file_level = _parse_level(os.getenv(_FILE_LEVEL_ENV), fallback=global_level)
    console_level = _parse_optional_level(os.getenv(_CONSOLE_LEVEL_ENV))
    return LoggingConfig(global_level=global_level, file_level=file_level, console_level=console_level)


def _configure_file_handlers(logger: logging.Logger, formatter: logging.Formatter, file_level: int) -> None:
    target_paths = []
    user_log_dir = Path.home() / '.metroliza'
    user_log_dir.mkdir(parents=True, exist_ok=True)
    target_paths.append(user_log_dir / LOG_FILE_NAME)
    target_paths.append(Path.cwd() / LOG_FILE_NAME)
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

    for log_path in target_paths:
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
            handler = logging.handlers.RotatingFileHandler(
                str(log_path),
                maxBytes=_FILE_MAX_BYTES,
                backupCount=_FILE_BACKUP_COUNT,
                encoding='utf-8',
            )
            setattr(handler, '_metroliza_file_handler', True)
            logger.addHandler(handler)
        else:
            setattr(handler, '_metroliza_file_handler', True)

        handler.setLevel(file_level)
        handler.setFormatter(formatter)


def _configure_console_handler(logger: logging.Logger, formatter: logging.Formatter, console_level: int | None) -> None:
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
    """Ensure Metroliza logging writes to configured sinks with independent thresholds."""
    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    resolved_config = config or resolve_logging_config()
    if level is not None and config is None:
        resolved_config = LoggingConfig(global_level=level, file_level=level, console_level=resolved_config.console_level)
    logger.setLevel(resolved_config.global_level)

    _configure_file_handlers(logger, formatter, resolved_config.file_level)
    _configure_console_handler(logger, formatter, resolved_config.console_level)

    return resolved_config
