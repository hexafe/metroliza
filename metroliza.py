import logging
import os
import sys
from dataclasses import dataclass

import VersionDate

from modules.license_bootstrap import show_invalid_license_message, validate_license_bootstrap
from modules.logging_utils import ensure_application_logging

VERSION_DATE = VersionDate.VERSION_DATE
STARTUP_SMOKE_ENV = "METROLIZA_STARTUP_SMOKE"
PDF_PARSER_SMOKE_FIXTURE_ENV = "METROLIZA_PDF_PARSER_SMOKE_FIXTURE"
PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV = "METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT"
LICENSE_MODE_ENV = "METROLIZA_LICENSE_VERIFICATION"


@dataclass(frozen=True)
class StartupConfig:
    startup_smoke_mode: bool
    pdf_parser_smoke_fixture: str | None
    pdf_parser_smoke_expected_text: str | None
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
    """Load startup behavior from environment defaults."""
    return StartupConfig(
        startup_smoke_mode=parse_env_flag(os.getenv(STARTUP_SMOKE_ENV), default=False),
        pdf_parser_smoke_fixture=os.getenv(PDF_PARSER_SMOKE_FIXTURE_ENV),
        pdf_parser_smoke_expected_text=os.getenv(PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV),
        license_verification_enabled=parse_env_flag(os.getenv(LICENSE_MODE_ENV), default=False),
    )


def initialize_logging() -> logging.Logger:
    """Initialize application logging and return the entrypoint logger."""
    ensure_application_logging()
    return logging.getLogger(__name__)


def get_or_create_qapplication():
    """Return the active QApplication, creating it when startup has not done so yet."""
    from PyQt6.QtWidgets import QApplication

    existing_app = QApplication.instance()
    if existing_app is not None:
        return existing_app
    return QApplication(sys.argv)


def log_and_exit(exception: Exception) -> None:
    """Handles logging exceptions using CustomLogger."""
    from modules.custom_logger import CustomLogger

    CustomLogger(exception, reraise=False)


def run_startup_smoke_mode(logger: logging.Logger) -> int:
    """Run startup smoke mode and return process exit code."""
    from modules.license_key_manager import LicenseKeyManager

    logger.info("Startup smoke mode enabled (%s): beginning non-interactive init", STARTUP_SMOKE_ENV)
    app = get_or_create_qapplication()
    _ = LicenseKeyManager.generate_hardware_id()
    app.processEvents()
    logger.info("Startup smoke mode completed successfully; exiting without showing UI")
    return 0




def run_pdf_parser_smoke_mode(logger: logging.Logger, fixture_path: str, expected_text: str) -> int:
    """Run packaged PDF parser smoke mode and return process exit code."""
    from modules.pdf_parser_smoke import run_pdf_parser_smoke

    logger.info(
        "Packaged PDF parser smoke enabled (%s): parsing fixture %s",
        PDF_PARSER_SMOKE_FIXTURE_ENV,
        fixture_path,
    )
    run_pdf_parser_smoke(fixture_path, expected_text)
    logger.info("Packaged PDF parser smoke completed successfully")
    return 0

def launch_ui(config: StartupConfig) -> int:
    """Launch UI after optional license checks and return process exit code."""
    # Some packaged/Windows import paths touch UI modules eagerly, so make sure
    # QApplication exists before importing the main window dependency graph.
    app = get_or_create_qapplication()
    from modules.license_key_manager import LicenseKeyManager
    from modules.main_window import MainWindow

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

    if config.pdf_parser_smoke_fixture:
        return run_pdf_parser_smoke_mode(
            logger,
            config.pdf_parser_smoke_fixture,
            config.pdf_parser_smoke_expected_text or "",
        )

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
