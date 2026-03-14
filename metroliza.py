import logging
import os
import sys
from dataclasses import dataclass

import VersionDate

from modules.license_bootstrap import show_invalid_license_message, validate_license_bootstrap
from modules.logging_utils import ensure_application_logging

VERSION_DATE = VersionDate.VERSION_DATE
STARTUP_SMOKE_ENV = "METROLIZA_STARTUP_SMOKE"
LICENSE_MODE_ENV = "METROLIZA_LICENSE_VERIFICATION"


@dataclass(frozen=True)
class StartupConfig:
    startup_smoke_mode: bool
    license_verification_enabled: bool


def parse_env_flag(value: str | None, default: bool) -> bool:
    """Parse common truthy/falsy env values with a secure fallback default."""
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def load_startup_config() -> StartupConfig:
    """Load startup behavior from environment with secure defaults."""
    return StartupConfig(
        startup_smoke_mode=parse_env_flag(os.getenv(STARTUP_SMOKE_ENV), default=False),
        license_verification_enabled=parse_env_flag(os.getenv(LICENSE_MODE_ENV), default=True),
    )


def initialize_logging() -> logging.Logger:
    """Initialize application logging and return the entrypoint logger."""
    ensure_application_logging()
    return logging.getLogger(__name__)


def log_and_exit(exception: Exception) -> None:
    """Handles logging exceptions using CustomLogger."""
    from modules.custom_logger import CustomLogger

    CustomLogger(exception, reraise=False)


def run_startup_smoke_mode(logger: logging.Logger) -> int:
    """Run startup smoke mode and return process exit code."""
    from PyQt6.QtWidgets import QApplication
    from modules.license_key_manager import LicenseKeyManager

    logger.info("Startup smoke mode enabled (%s): beginning non-interactive init", STARTUP_SMOKE_ENV)
    app = QApplication(sys.argv)
    _ = LicenseKeyManager.generate_hardware_id()
    app.processEvents()
    logger.info("Startup smoke mode completed successfully; exiting without showing UI")
    return 0


def launch_ui(config: StartupConfig) -> int:
    """Launch UI after optional license checks and return process exit code."""
    from PyQt6.QtWidgets import QApplication
    from modules.license_key_manager import LicenseKeyManager
    from modules.main_window import MainWindow

    app = QApplication(sys.argv)
    hardware_id = LicenseKeyManager.generate_hardware_id()
    license_result = validate_license_bootstrap(config.license_verification_enabled)

    if not license_result.is_valid:
        show_invalid_license_message(
            "Invalid or no license key found",
            "To request license key send the hardware id to the author",
            hardware_id,
        )
        return 1

    main_window = MainWindow(VersionDate.VERSION_LABEL, license_result.days_until_expiration)
    main_window.show()
    return app.exec()


def bootstrap_application() -> int:
    """Entrypoint orchestration for startup configuration, logging, and UI launch."""
    logger = initialize_logging()
    config = load_startup_config()

    if config.startup_smoke_mode:
        return run_startup_smoke_mode(logger)

    return launch_ui(config)


def run_application() -> int:
    """Run bootstrap flow with top-level exception logging."""
    try:
        return bootstrap_application()
    except Exception as exc:
        log_and_exit(exc)
        return 1


if __name__ == "__main__":
    sys.exit(run_application())
