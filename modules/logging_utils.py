import logging
from pathlib import Path


LOG_FILE_NAME = "metroliza.log"


def ensure_application_logging(level=logging.ERROR):
    """Ensure Metroliza logging writes to both current and user config locations."""
    logger = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    target_paths = []
    user_log_dir = Path.home() / '.metroliza'
    user_log_dir.mkdir(parents=True, exist_ok=True)
    target_paths.append(user_log_dir / LOG_FILE_NAME)
    target_paths.append(Path.cwd() / LOG_FILE_NAME)

    existing_file_handlers = {
        Path(handler.baseFilename).resolve()
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler) and getattr(handler, 'baseFilename', None)
    }

    for log_path in target_paths:
        resolved_path = log_path.resolve()
        if resolved_path in existing_file_handlers:
            continue

        handler = logging.FileHandler(str(log_path), encoding='utf-8')
        handler.setLevel(level)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.setLevel(min(logger.level if logger.level else level, level))

