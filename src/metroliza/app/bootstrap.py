import logging
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
import re
import uuid

from metroliza.app import version as VersionDate
from metroliza.app.build_provenance import (
    BUILD_PROVENANCE_SCHEMA_VERSION, BuildProvenance, load_build_provenance, runtime_mode,
)
from metroliza.app.license_bootstrap import (
    show_invalid_license_message,
    validate_license_bootstrap,
)
from metroliza.app.startup_splash import (
    close_bootloader_splash,
    create_startup_splash,
    update_bootloader_splash,
)
from metroliza.app.startup_profile import record_event, ui_smoke_enabled
from metroliza.app.ui_entrypoint import MainWindowFactory, load_main_window_factory
from metroliza.shared.diagnostic_events import (
    BuildPackager,
    DiagnosticOperation,
    RuntimeMode,
    RuntimeProvenanceEvent,
    StartupCallsite,
    StartupDiagnosticEvent,
    StartupMode,
    StartupOutcome,
    build_exception_diagnostic_event,
)
from metroliza.shared.logging_utils import ensure_application_logging

VERSION_DATE = VersionDate.VERSION_DATE
STARTUP_SMOKE_ENV = "METROLIZA_STARTUP_SMOKE"
PDF_PARSER_SMOKE_FIXTURE_ENV = "METROLIZA_PDF_PARSER_SMOKE_FIXTURE"
PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV = "METROLIZA_PDF_PARSER_SMOKE_EXPECTED_TEXT"
LICENSE_MODE_ENV = "METROLIZA_LICENSE_VERIFICATION"
PARSER_STRICT_MATCHING_ENV = "PARSER_STRICT_MATCHING"

record_event("process_entry")


@dataclass(slots=True)
class _StartupInvocation:
    invocation_id: uuid.UUID = field(default_factory=lambda: uuid.uuid4())
    startup_id: uuid.UUID = field(default_factory=lambda: uuid.uuid4())
    sequence: int = 0
    mode: StartupMode = StartupMode.UNKNOWN
    callsite: StartupCallsite = StartupCallsite.BOOTSTRAP
    startup_complete: bool = False


_STARTUP_INVOCATION: ContextVar[_StartupInvocation | None] = ContextVar(
    "metroliza_startup_invocation", default=None
)


def _begin_startup_context():
    # Clearing first also isolates a nested invocation when UUID generation fails.
    token = _STARTUP_INVOCATION.set(None)
    try:
        _STARTUP_INVOCATION.set(_StartupInvocation())
    except Exception:
        pass
    return token


def _startup_event(
    callsite: StartupCallsite,
    outcome: StartupOutcome = StartupOutcome.MILESTONE,
    *,
    mode: StartupMode | None = None,
    exit_code: int | None = None,
    exception: Exception | None = None,
) -> None:
    """Best-effort projection at an explicit seam; never log a diagnostic failure."""
    try:
        context = _STARTUP_INVOCATION.get()
        if context is None:
            return
        context.callsite = callsite
        if mode is not None:
            context.mode = mode
        if outcome is StartupOutcome.STARTUP_COMPLETED:
            context.startup_complete = True
        if context.sequence >= 16:
            return
        context.sequence += 1
        shape = None if exception is None else build_exception_diagnostic_event(
            exception, operation=DiagnosticOperation.UNHANDLED_EXCEPTION
        )
        event = StartupDiagnosticEvent(
            context.invocation_id, context.startup_id, context.sequence,
            context.mode, callsite, outcome, exit_code, shape,
        )
        level = logging.ERROR if exception is not None or outcome is StartupOutcome.STARTUP_REJECTED else logging.INFO
        logger = logging.getLogger(__name__)
        if logger.hasHandlers():
            logger.log(level, event)
    except Exception:
        pass


def _startup_failure(exception: Exception) -> None:
    try:
        context = _STARTUP_INVOCATION.get()
        if context is None:
            return
        outcome = StartupOutcome.APPLICATION_FAILED if context.startup_complete else StartupOutcome.STARTUP_FAILED
        _startup_event(context.callsite, outcome, exception=exception)
    except Exception:
        pass


def _selected_startup_mode(config) -> StartupMode:
    if config.startup_smoke_mode:
        return StartupMode.STARTUP_SMOKE
    if config.pdf_parser_smoke_fixture:
        return StartupMode.PDF_SMOKE
    if config.startup_ui_smoke_mode:
        return StartupMode.UI_SMOKE
    return StartupMode.INTERACTIVE


def _configuration_observed(config: "StartupConfig") -> None:
    try:
        _startup_event(StartupCallsite.CONFIG_READY, mode=_selected_startup_mode(config))
    except Exception:
        pass


def _smoke_return(exit_code: int) -> int:
    outcome = StartupOutcome.STARTUP_COMPLETED if type(exit_code) is int and exit_code == 0 else StartupOutcome.STARTUP_REJECTED
    _startup_event(StartupCallsite.SMOKE_RETURN, outcome, exit_code=exit_code)
    return exit_code


def _source_release_fields() -> tuple[int, int, int | None]:
    version = VersionDate.RELEASE_VERSION
    if type(version) is not str or len(version) > 32:
        raise ValueError("invalid source release")
    match = re.fullmatch(r"([0-9]{4})\.([0-9]{2})(?:rc([0-9]{1,3}))?", version)
    if match is None:
        raise ValueError("invalid source release")
    return int(match[1]), int(match[2]), None if match[3] is None else int(match[3])


def _project_build_identity():
    """Read only exact manifest primitives; unknown is preferable to stale identity."""
    mode = runtime_mode()
    if type(mode) is str and mode == "source":
        return RuntimeMode.SOURCE, BuildPackager.SOURCE, "unknown", None
    if type(mode) is not str or mode != "frozen":
        return RuntimeMode.UNKNOWN, BuildPackager.UNKNOWN, "unknown", None
    fallback = (RuntimeMode.FROZEN, BuildPackager.UNKNOWN, "unknown", None)
    provenance = load_build_provenance()
    if type(provenance) is not BuildProvenance:
        return fallback
    return _project_manifest_identity(provenance, fallback)


def _project_manifest_identity(provenance: BuildProvenance, fallback):
    values = object.__getattribute__(provenance, "__dict__")
    if type(values) is not dict:
        return fallback
    schema = dict.get(values, "schema_version")
    if type(schema) is not int or schema != BUILD_PROVENANCE_SCHEMA_VERSION:
        return fallback
    label = dict.get(values, "release_label")
    sha = dict.get(values, "git_sha")
    dirty = dict.get(values, "dirty")
    packager = dict.get(values, "packager")
    if type(label) is not str or label != VersionDate.VERSION_LABEL:
        return fallback
    if type(sha) is not str or len(sha) not in (40, 64):
        return fallback
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) is None or type(dirty) is not bool:
        return fallback
    if type(packager) is not str:
        return fallback
    if packager == "pyinstaller":
        return RuntimeMode.FROZEN, BuildPackager.PYINSTALLER, sha, dirty
    if packager == "nuitka":
        return RuntimeMode.FROZEN, BuildPackager.NUITKA, sha, dirty
    return fallback


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
    update_bootloader_splash("Preparing Metroliza...", phase="logging")
    record_event("logging_init_start")
    ensure_application_logging()
    record_event("logging_init_done")
    logger = logging.getLogger(__name__)
    _startup_event(StartupCallsite.LOGGING_READY)
    log_runtime_provenance(logger)
    return logger


def log_runtime_provenance(logger: logging.Logger) -> None:
    """Emit a closed build projection through the unchanged managed logging route."""
    try:
        context = _STARTUP_INVOCATION.get() or _StartupInvocation()
        if context.sequence >= 16:
            return
        context.sequence += 1
        mode, packager, sha, dirty = _project_build_identity()
        year, month, candidate = _source_release_fields()
        event = RuntimeProvenanceEvent(
            context.invocation_id, context.startup_id, context.sequence,
            mode, packager, sha, dirty,
            release_year=year, release_month=month, release_candidate=candidate,
        )
        logger.info(event)
    except Exception:
        pass


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
    close_bootloader_splash(phase="top_level_exception")
    from metroliza.shared.custom_logger import CustomLogger

    CustomLogger(exception, reraise=False)


def run_startup_smoke_mode(logger: logging.Logger) -> int:
    """Run startup smoke mode and return process exit code."""
    close_bootloader_splash(phase="startup_smoke")
    record_event("startup_smoke_start")
    from metroliza.app.license_key_manager import LicenseKeyManager

    logger.info("Startup smoke mode enabled (%s): beginning non-interactive init", STARTUP_SMOKE_ENV)
    _startup_event(StartupCallsite.QAPPLICATION_REQUEST)
    app = get_or_create_qapplication()
    _startup_event(StartupCallsite.QAPPLICATION_READY)
    _startup_event(StartupCallsite.SMOKE_WORK)
    _ = LicenseKeyManager.generate_hardware_id()
    app.processEvents()
    logger.info("Startup smoke mode completed successfully; exiting without showing UI")
    record_event("startup_smoke_done")
    return 0


def run_pdf_parser_smoke_mode(logger: logging.Logger, fixture_path: str, expected_text: str) -> int:
    """Run packaged PDF parser smoke mode and return process exit code."""
    close_bootloader_splash(phase="pdf_parser_smoke")
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


def launch_ui(
    config: StartupConfig,
    *,
    main_window_factory: MainWindowFactory | None = None,
) -> int:
    """Launch UI after optional license checks and return process exit code."""
    # Some packaged/Windows import paths touch UI modules eagerly, so make sure
    # QApplication exists before importing the main window dependency graph.
    record_event("launch_ui_start")
    update_bootloader_splash("Starting Metroliza interface...", phase="qt")
    _startup_event(StartupCallsite.QAPPLICATION_REQUEST)
    app = get_or_create_qapplication()
    _startup_event(StartupCallsite.QAPPLICATION_READY)
    splash = create_startup_splash(app, ui_smoke_mode=config.startup_ui_smoke_mode)
    close_bootloader_splash(phase="qt_splash_ready")
    splash.show_message("Checking license...", phase="license")

    _startup_event(StartupCallsite.LICENSE_CHECK)
    record_event("license_validation_start")
    license_result = validate_license_bootstrap(config.license_verification_enabled)
    record_event("license_validation_done", is_valid=license_result.is_valid)

    if not license_result.is_valid:
        splash.close()
        record_event("license_manager_import_start")
        from metroliza.app.license_key_manager import LicenseKeyManager

        record_event("license_manager_import_done")
        record_event("license_hardware_id_start")
        hardware_id = LicenseKeyManager.generate_hardware_id()
        record_event("license_hardware_id_done")
        show_invalid_license_message(
            "Invalid or no license key found",
            "To request license key send the hardware id to the author",
            hardware_id,
        )
        record_event("launch_ui_invalid_license")
        _startup_event(StartupCallsite.LICENSE_REJECTED, StartupOutcome.STARTUP_REJECTED, exit_code=1)
        return 1

    splash.show_message("Loading main window...", phase="main_window")
    _startup_event(StartupCallsite.MAIN_WINDOW_FACTORY)
    record_event("main_window_import_start")
    if main_window_factory is None:
        main_window_factory = load_main_window_factory()
    record_event("main_window_import_done")

    _startup_event(StartupCallsite.MAIN_WINDOW_CONSTRUCT)
    record_event("main_window_construct_start")
    main_window = main_window_factory(
        VersionDate.VERSION_LABEL,
        license_result.days_until_expiration,
    )
    record_event("main_window_construct_done")
    splash.show_message("Opening dashboard...", phase="show")
    _startup_event(StartupCallsite.MAIN_WINDOW_SHOW_REQUEST)
    main_window.show()
    _startup_event(StartupCallsite.MAIN_WINDOW_SHOW_RETURNED)
    record_event("main_window_show_called")
    if config.startup_ui_smoke_mode:
        splash.finish(main_window)
        _schedule_startup_ui_smoke_exit(app)
    else:
        main_window.schedule_feature_import_warmup(
            delay_ms=0,
            on_finished=lambda: splash.finish(main_window),
            status_callback=lambda message: splash.show_message(message, phase="warmup"),
        )
    record_event("event_loop_enter")
    _startup_event(StartupCallsite.EVENT_LOOP_EXEC_REQUEST, StartupOutcome.STARTUP_COMPLETED)
    exit_code = app.exec()
    record_event("event_loop_exit", exit_code=exit_code)
    return exit_code


def bootstrap_application() -> int:
    """Entrypoint orchestration for startup configuration, logging, and UI launch."""
    record_event("bootstrap_start")
    update_bootloader_splash("Starting Metroliza...", phase="bootstrap")
    _startup_event(StartupCallsite.LOGGING_INITIALIZE)
    logger = initialize_logging()
    _startup_event(StartupCallsite.CONFIG_LOAD)
    config = load_startup_config()
    _configuration_observed(config)

    if config.startup_smoke_mode:
        _startup_event(StartupCallsite.SMOKE_WORK)
        return _smoke_return(run_startup_smoke_mode(logger))

    if config.pdf_parser_smoke_fixture:
        _startup_event(StartupCallsite.SMOKE_WORK)
        return _smoke_return(run_pdf_parser_smoke_mode(
            logger,
            config.pdf_parser_smoke_fixture,
            config.pdf_parser_smoke_expected_text or "",
        ))

    return launch_ui(config)


def run_application() -> int:
    """Run the original bootstrap flow with one optional invocation context."""
    token = None
    try:
        token = _begin_startup_context()
    except Exception:
        pass
    try:
        _startup_event(StartupCallsite.BOOTSTRAP, StartupOutcome.INVOCATION_STARTED)
        try:
            exit_code = bootstrap_application()
        except Exception as exc:
            _startup_failure(exc)
            log_and_exit(exc)
            return 1
        _startup_event(StartupCallsite.APPLICATION_RETURN, StartupOutcome.APPLICATION_RETURNED, exit_code=exit_code)
        return exit_code
    finally:
        if token is not None:
            _STARTUP_INVOCATION.reset(token)


if __name__ == "__main__":
    sys.exit(run_application())
