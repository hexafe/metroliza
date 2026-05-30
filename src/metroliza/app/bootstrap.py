import logging
import os
import sys
from dataclasses import dataclass

from metroliza.app import version as VersionDate

from metroliza.app.license_bootstrap import (
    show_invalid_license_message,
    validate_license_bootstrap,
)
from metroliza.app.startup_profile import record_event, ui_smoke_enabled
from metroliza.shared.logging_utils import ensure_application_logging

VERSION_DATE = VersionDate.VERSION_DATE
STARTUP_SMOKE_ENV = "METROLIZA_STARTUP_SMOKE"
PDF_PARSER_SMOKE_FIXTURE_ENV = "METROLIZA_PDF_PARSER_SMOKE_FIXTURE"
PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV = "METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT"
LICENSE_MODE_ENV = "METROLIZA_LICENSE_VERIFICATION"

record_event("process_entry")


@dataclass(frozen=True)
class StartupConfig:
    startup_smoke_mode: bool
    startup_ui_smoke_mode: bool
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
    record_event("load_startup_config_start")
    config = StartupConfig(
        startup_smoke_mode=parse_env_flag(os.getenv(STARTUP_SMOKE_ENV), default=False),
        startup_ui_smoke_mode=ui_smoke_enabled(),
        pdf_parser_smoke_fixture=os.getenv(PDF_PARSER_SMOKE_FIXTURE_ENV),
        pdf_parser_smoke_expected_text=os.getenv(PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV),
        license_verification_enabled=parse_env_flag(os.getenv(LICENSE_MODE_ENV), default=False),
    )
    record_event(
        "load_startup_config_done",
        startup_smoke_mode=config.startup_smoke_mode,
        startup_ui_smoke_mode=config.startup_ui_smoke_mode,
        pdf_parser_smoke_fixture=bool(config.pdf_parser_smoke_fixture),
        license_verification_enabled=config.license_verification_enabled,
    )
    return config


def initialize_logging() -> logging.Logger:
    """Initialize application logging and return the entrypoint logger."""
    record_event("logging_init_start")
    ensure_application_logging()
    record_event("logging_init_done")
    return logging.getLogger(__name__)


def get_or_create_qapplication():
    """Return the active QApplication, creating it when startup has not done so yet."""
    record_event("qapplication_import_start")
    from PyQt6.QtWidgets import QApplication

    record_event("qapplication_import_done")
    existing_app = QApplication.instance()
    if existing_app is not None:
        record_event("qapplication_reused")
        return existing_app

    record_event("qapplication_create_start")
    app = QApplication(sys.argv)
    record_event("qapplication_create_done")
    return app


def _schedule_startup_ui_smoke_exit(app) -> None:
    """Exit after the first Qt event-loop tick for packaged startup benchmarks."""
    from PyQt6.QtCore import QTimer

    def record_and_quit() -> None:
        record_event("first_event_loop_tick")
        app.quit()

    QTimer.singleShot(0, record_and_quit)


def log_and_exit(exception: Exception) -> None:
    """Handles logging exceptions using CustomLogger."""
    record_event("top_level_exception", error_type=type(exception).__name__)
    from metroliza.shared.custom_logger import CustomLogger

    CustomLogger(exception, reraise=False)


def run_startup_smoke_mode(logger: logging.Logger) -> int:
    """Run startup smoke mode and return process exit code."""
    record_event("startup_smoke_start")
    from metroliza.app.license_key_manager import LicenseKeyManager

    logger.info("Startup smoke mode enabled (%s): beginning non-interactive init", STARTUP_SMOKE_ENV)
    app = get_or_create_qapplication()
    _ = LicenseKeyManager.generate_hardware_id()
    app.processEvents()
    logger.info("Startup smoke mode completed successfully; exiting without showing UI")
    record_event("startup_smoke_done")
    return 0


def run_pdf_parser_smoke_mode(logger: logging.Logger, fixture_path: str, expected_text: str) -> int:
    """Run packaged PDF parser smoke mode and return process exit code."""
    record_event("pdf_parser_smoke_start")
    from metroliza.parsing.pdf_parser_smoke import run_pdf_parser_smoke

    logger.info(
        "Packaged PDF parser smoke enabled (%s): parsing fixture %s",
        PDF_PARSER_SMOKE_FIXTURE_ENV,
        fixture_path,
    )
    run_pdf_parser_smoke(fixture_path, expected_text)
    logger.info("Packaged PDF parser smoke completed successfully")
    record_event("pdf_parser_smoke_done")
    return 0


def launch_ui(config: StartupConfig) -> int:
    """Launch UI after optional license checks and return process exit code."""
    # Some packaged/Windows import paths touch UI modules eagerly, so make sure
    # QApplication exists before importing the main window dependency graph.
    record_event("launch_ui_start")
    app = get_or_create_qapplication()
    record_event("license_manager_import_start")
    from metroliza.app.license_key_manager import LicenseKeyManager

    record_event("license_manager_import_done")
    record_event("main_window_import_start")
    from metroliza.ui.main_window import MainWindow

    record_event("main_window_import_done")

    record_event("license_hardware_id_start")
    hardware_id = LicenseKeyManager.generate_hardware_id()
    record_event("license_hardware_id_done")
    record_event("license_validation_start")
    license_result = validate_license_bootstrap(config.license_verification_enabled)
    record_event("license_validation_done", is_valid=license_result.is_valid)

    if not license_result.is_valid:
        show_invalid_license_message(
            "Invalid or no license key found",
            "To request license key send the hardware id to the author",
            hardware_id,
        )
        record_event("launch_ui_invalid_license")
        return 1

    record_event("main_window_construct_start")
    main_window = MainWindow(VersionDate.VERSION_LABEL, license_result.days_until_expiration)
    record_event("main_window_construct_done")
    main_window.show()
    record_event("main_window_show_called")
    if config.startup_ui_smoke_mode:
        _schedule_startup_ui_smoke_exit(app)
    record_event("event_loop_enter")
    exit_code = app.exec()
    record_event("event_loop_exit", exit_code=exit_code)
    return exit_code


def bootstrap_application() -> int:
    """Entrypoint orchestration for startup configuration, logging, and UI launch."""
    record_event("bootstrap_start")
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
