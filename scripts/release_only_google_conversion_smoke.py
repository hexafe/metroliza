"""Release-only manual/CI-gated smoke check for live Google Drive -> Sheets conversion.

Usage contract:
- Inputs:
  - Required gate: ``METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE=1``.
  - Optional overrides: ``METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH``
    (must end with ``credentials.json``) and ``METROLIZA_GOOGLE_SMOKE_TOKEN_PATH``
    (must end with ``token.json``).
- Expected success signals:
  - Script exits 0 and prints ``Google conversion smoke check passed.``.
  - Conversion metadata validates (non-empty file id + parseable HTTPS sheet URL).
  - Warning policy validates as ``warnings=()``.
- Warning handling:
  - Any non-empty warnings tuple is release-blocking for smoke checks.
  - Keep the converted Google Sheet as convenience output and treat the generated
    ``.xlsx`` as the fidelity-baseline fallback artifact while warning root cause
    is investigated.

This module intentionally lives outside the `tests/` tree because it is
release-only and opt-in; it is not part of regular PR test execution. Invoke
directly when release validation needs a real sandbox roundtrip.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import xlsxwriter

from modules.google_drive_export import GoogleDriveExportError, upload_and_convert_workbook
from tests.test_google_drive_credentials_hygiene import validate_example_credentials_template_hygiene

SMOKE_OPT_IN_ENV = "METROLIZA_RUN_GOOGLE_CONVERSION_SMOKE"
SMOKE_CREDENTIALS_PATH_ENV = "METROLIZA_GOOGLE_SMOKE_CREDENTIALS_PATH"
SMOKE_TOKEN_PATH_ENV = "METROLIZA_GOOGLE_SMOKE_TOKEN_PATH"


class SmokeConfigError(RuntimeError):
    """Raised when smoke-check runtime prerequisites are not configured."""


def _require_opt_in() -> None:
    if os.environ.get(SMOKE_OPT_IN_ENV) != "1":
        raise SmokeConfigError(
            f"Smoke check is disabled by default. Set {SMOKE_OPT_IN_ENV}=1 to run this release-only flow."
        )


def _resolve_secret_file(env_name: str, default_path: str, *, expected_name: str) -> Path:
    path = Path(os.environ.get(env_name, default_path)).expanduser().resolve()
    if path.name != expected_name:
        raise SmokeConfigError(
            f"{env_name} must point to a local-only '{expected_name}' file (got '{path.name}'). "
            f"Use {expected_name} copied from your sandbox OAuth bootstrap."
        )
    if not path.exists():
        raise SmokeConfigError(
            f"Missing required file: {path}. Configure {env_name} (or create {default_path}) with sandbox OAuth data."
        )
    return path


def _create_minimal_workbook(path: Path) -> list[str]:
    expected_sheet_names = ["MEASUREMENTS", "REF_A"]
    workbook = xlsxwriter.Workbook(str(path))

    measurements = workbook.add_worksheet(expected_sheet_names[0])
    measurements.write_row(0, 0, ["MEAS", "VALUE"])
    measurements.write_row(1, 0, ["M1", 12.34])

    reference = workbook.add_worksheet(expected_sheet_names[1])
    reference.write_row(0, 0, ["REF", "TARGET"])
    reference.write_row(1, 0, ["R1", 12.30])

    workbook.close()
    return expected_sheet_names


def _extract_sheet_id(sheet_url: str) -> str | None:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    return match.group(1) if match else None


def run_google_conversion_smoke_check() -> None:
    _require_opt_in()
    validate_example_credentials_template_hygiene()

    credentials_path = _resolve_secret_file(
        SMOKE_CREDENTIALS_PATH_ENV,
        default_path="credentials.json",
        expected_name="credentials.json",
    )
    token_path = _resolve_secret_file(
        SMOKE_TOKEN_PATH_ENV,
        default_path="token.json",
        expected_name="token.json",
    )

    with tempfile.TemporaryDirectory(prefix="metroliza-google-smoke-") as tmpdir:
        export_path = Path(tmpdir) / "metroliza_smoke_export.xlsx"
        _create_minimal_workbook(export_path)

        try:
            result = upload_and_convert_workbook(
                str(export_path),
                credentials_path=str(credentials_path),
                token_path=str(token_path),
                expected_sheet_names=None,
                max_retries=2,
                retry_delay_seconds=1.5,
            )
        except GoogleDriveExportError as exc:
            raise AssertionError(
                "Google conversion smoke check failed during upload/conversion. "
                "Re-validate sandbox OAuth credentials/token and Drive API availability."
            ) from exc

    if not result.file_id.strip():
        raise AssertionError("Conversion result did not return a Google file id.")

    if "https://" not in result.web_url:
        raise AssertionError("Conversion result did not return a valid Google Sheet link.")

    sheet_id_from_url = _extract_sheet_id(result.web_url)
    if not sheet_id_from_url:
        raise AssertionError("Could not parse spreadsheet id from returned link.")

    if sheet_id_from_url != result.file_id:
        raise AssertionError("Returned file id does not match spreadsheet id embedded in web_url.")

    if result.warnings:
        raise AssertionError(f"Post-conversion validation produced warnings: {result.warnings}")



if __name__ == "__main__":
    run_google_conversion_smoke_check()
    print("Google conversion smoke check passed.")
