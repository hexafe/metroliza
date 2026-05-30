"""Metroliza application package."""

__all__ = [
    "LICENSE_MODE_ENV",
    "PDF_PARSER_SMOKE_EXPECTED_TEXT_ENV",
    "PDF_PARSER_SMOKE_FIXTURE_ENV",
    "STARTUP_SMOKE_ENV",
    "VERSION_DATE",
    "StartupConfig",
    "bootstrap_application",
    "get_or_create_qapplication",
    "initialize_logging",
    "launch_ui",
    "load_startup_config",
    "log_and_exit",
    "parse_env_flag",
    "run_application",
    "run_pdf_parser_smoke_mode",
    "run_startup_smoke_mode",
    "validate_license_bootstrap",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from metroliza.app import bootstrap

    value = getattr(bootstrap, name)
    globals()[name] = value
    return value
