from __future__ import annotations

import json
import logging
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modules.log_context import build_google_conversion_log_extra, get_operation_logger

GOOGLE_DRIVE_UPLOAD_URL = (
    "https://www.googleapis.com/upload/drive/v3/files"
    "?uploadType=multipart&fields=id,webViewLink,webContentLink"
)
GOOGLE_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_OAUTH_SCOPES = (GOOGLE_DRIVE_SCOPE,)
GOOGLE_DRIVE_REPORTS_FOLDER_NAME = "metroliza_reports"
logger = get_operation_logger(logging.getLogger(__name__), "google_conversion")


class GoogleDriveExportError(RuntimeError):
    """Base exception for Google Drive export failures."""


class GoogleDriveAuthError(GoogleDriveExportError):
    """Authentication or authorization failure."""


class GoogleDriveQuotaError(GoogleDriveExportError):
    """API quota/rate-limit failure."""


class GoogleDriveTransientError(GoogleDriveExportError):
    """Retryable transient/network/server failure."""


class GoogleDriveResponseError(GoogleDriveExportError):
    """Unexpected response payload shape or non-retryable API failure."""


def _build_google_log_extra(*, file_ref="", error=None, outcome="") -> dict[str, str]:
    return build_google_conversion_log_extra(
        file_ref=file_ref,
        error_class=type(error).__name__ if error is not None else "",
        outcome=outcome,
    )


@dataclass(frozen=True)
class GoogleDriveConversionResult:
    file_id: str
    web_url: str
    local_xlsx_path: str
    fallback_message: str
    warnings: tuple[str, ...] = ()
    warning_details: tuple[dict[str, str], ...] = ()
    converted_tab_titles: tuple[str, ...] = ()


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GoogleDriveAuthError(f"Required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoogleDriveAuthError(f"Invalid JSON content in {path}: {exc}") from exc


def _read_credentials(credentials_path: Path) -> dict[str, Any]:
    payload = _read_json_file(credentials_path)
    installed = payload.get("installed") or payload.get("web")
    if not isinstance(installed, dict):
        raise GoogleDriveAuthError("credentials.json must include an 'installed' or 'web' OAuth client section.")

    for key in ("client_id", "client_secret", "token_uri"):
        if not installed.get(key):
            raise GoogleDriveAuthError(f"credentials.json missing required field: {key}")
    return installed


def _interactive_oauth_authorization(credentials_path: Path, token_path: Path) -> dict[str, Any]:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes=list(GOOGLE_OAUTH_SCOPES))
    try:
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            authorization_prompt_message="Please complete Google authorization in your browser.\n{url}\n",
            success_message="Google authorization completed. You can close this browser tab.",
            timeout_seconds=120,
        )
    except TypeError:
        # Older google-auth-oauthlib versions may not support timeout_seconds.
        credentials = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            open_browser=True,
            authorization_prompt_message="Please complete Google authorization in your browser.\n{url}\n",
            success_message="Google authorization completed. You can close this browser tab.",
        )
    except Exception as exc:
        raise GoogleDriveAuthError(
            "Google OAuth authorization was canceled or timed out. "
            "Please try again to enable Google Sheets export."
        ) from exc

    expires_at = time.time() + 3600
    if getattr(credentials, "expiry", None) is not None:
        expires_at = credentials.expiry.timestamp()

    token_payload: dict[str, Any] = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes or [GOOGLE_DRIVE_SCOPE]),
        "scope": credentials.scope or GOOGLE_DRIVE_SCOPE,
        "token_type": "Bearer",
        "expires_at": expires_at,
    }
    _save_token_payload(token_path, token_payload)
    return token_payload


def _load_token_payload(token_path: Path) -> dict[str, Any]:
    if not token_path.exists():
        raise GoogleDriveAuthError(
            "Missing token.json for Google Drive export. Please complete OAuth authorization first."
        )
    return _read_json_file(token_path)


def _token_is_valid(token_payload: dict[str, Any]) -> bool:
    access_token = token_payload.get("access_token")
    expires_at = token_payload.get("expires_at")
    if not access_token or not expires_at:
        return False
    return float(expires_at) > (time.time() + 60)


def _refresh_access_token(token_payload: dict[str, Any], credentials: dict[str, Any]) -> dict[str, Any]:
    refresh_token = token_payload.get("refresh_token")
    if not refresh_token:
        raise GoogleDriveAuthError(
            "token.json is missing refresh_token. Re-authenticate to continue Google Drive export."
        )

    refresh_form = urllib.parse.urlencode(
        {
            "client_id": credentials["client_id"],
            "client_secret": credentials["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        credentials["token_uri"],
        data=refresh_form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise map_google_http_error(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise map_google_network_error("OAuth token refresh failed", exc) from exc

    if "access_token" not in payload:
        raise GoogleDriveAuthError("OAuth refresh response did not include access_token.")

    expires_in = int(payload.get("expires_in", 3600))
    token_payload["access_token"] = payload["access_token"]
    token_payload["expires_at"] = time.time() + expires_in
    if payload.get("refresh_token"):
        token_payload["refresh_token"] = payload["refresh_token"]
    token_payload.setdefault("scope", GOOGLE_DRIVE_SCOPE)
    token_payload.setdefault("token_type", payload.get("token_type", "Bearer"))
    return token_payload


def _save_token_payload(token_path: Path, token_payload: dict[str, Any]) -> None:
    token_path.write_text(json.dumps(token_payload, indent=2), encoding="utf-8")


def _ensure_access_token(credentials_path: Path, token_path: Path) -> str:
    credentials = _read_credentials(credentials_path)
    if token_path.exists():
        token_payload = _load_token_payload(token_path)
    else:
        token_payload = _interactive_oauth_authorization(credentials_path, token_path)

    if _token_is_valid(token_payload):
        return str(token_payload["access_token"])

    if not token_payload.get("refresh_token"):
        token_payload = _interactive_oauth_authorization(credentials_path, token_path)
        if _token_is_valid(token_payload):
            return str(token_payload["access_token"])

    refreshed = _refresh_access_token(token_payload, credentials)
    _save_token_payload(token_path, refreshed)
    return str(refreshed["access_token"])


def parse_drive_conversion_response(payload: dict[str, Any]) -> GoogleDriveConversionResult:
    file_id = payload.get("id")
    web_url = payload.get("webViewLink") or payload.get("webContentLink") or payload.get("alternateLink")
    if not file_id or not web_url:
        raise GoogleDriveResponseError("Drive conversion response missing id and/or sheet URL fields.")
    return GoogleDriveConversionResult(
        file_id=file_id,
        web_url=web_url,
        local_xlsx_path="",
        fallback_message="",
    )


def map_google_http_error(status_code: int, payload_text: str) -> GoogleDriveExportError:
    reason = ""
    message = payload_text
    try:
        payload = json.loads(payload_text)
        error_payload = payload.get("error", {})
        message = error_payload.get("message", message)
        errors = error_payload.get("errors", [])
        if errors and isinstance(errors, list):
            first = errors[0]
            if isinstance(first, dict):
                reason = str(first.get("reason", "")).lower()
    except json.JSONDecodeError:
        reason = ""

    lower_message = str(message).lower()
    if status_code in (401, 403) and ("auth" in lower_message or "credential" in lower_message or reason in {"autherror", "insufficientpermissions"}):
        return GoogleDriveAuthError(f"Google auth error ({status_code}): {message}")
    if reason in {"userratelimitexceeded", "ratelimitexceeded", "quotaexceeded"}:
        return GoogleDriveQuotaError(f"Google quota error ({status_code}): {message}")
    if status_code >= 500 or reason in {"backenderror", "internalerror"}:
        return GoogleDriveTransientError(f"Google transient error ({status_code}): {message}")
    if status_code == 429:
        return GoogleDriveQuotaError(f"Google rate limit error ({status_code}): {message}")
    return GoogleDriveResponseError(f"Google API error ({status_code}): {message}")


def map_google_network_error(context: str, exc: urllib.error.URLError) -> GoogleDriveTransientError:
    return GoogleDriveTransientError(f"{context} due to network error: {exc}")


def _build_upload_request_body(*, boundary: str, metadata: dict[str, Any], file_mime_type: str, file_bytes: bytes) -> bytes:
    metadata_part = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
    ).encode("utf-8")
    file_part_header = (
        f"--{boundary}\r\n"
        f"Content-Type: {file_mime_type}\r\n\r\n"
    ).encode("utf-8")
    closing = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return metadata_part + file_part_header + file_bytes + closing


def _request_json(request: urllib.request.Request, *, context: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise map_google_http_error(exc.code, body_text) from exc
    except urllib.error.URLError as exc:
        raise map_google_network_error(context, exc) from exc


def _ensure_reports_folder(access_token: str) -> str:
    folder_query = (
        f"name='{GOOGLE_DRIVE_REPORTS_FOLDER_NAME}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    list_url = (
        f"{GOOGLE_DRIVE_FILES_URL}?"
        f"q={urllib.parse.quote(folder_query)}&"
        "fields=files(id,name)&"
        "pageSize=1&"
        "spaces=drive"
    )
    list_request = urllib.request.Request(
        list_url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    payload = _request_json(list_request, context="Google Drive folder lookup failed")
    files = payload.get("files")
    if isinstance(files, list) and files:
        folder_id = files[0].get("id")
        if folder_id:
            return str(folder_id)

    create_request = urllib.request.Request(
        f"{GOOGLE_DRIVE_FILES_URL}?fields=id",
        data=json.dumps(
            {
                "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME,
                "mimeType": "application/vnd.google-apps.folder",
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    created = _request_json(create_request, context="Google Drive folder creation failed")
    folder_id = created.get("id")
    if not folder_id:
        raise GoogleDriveResponseError("Google Drive folder creation response missing id.")
    return str(folder_id)


def upload_and_convert_workbook(
    excel_path: str,
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    expected_sheet_names: list[str] | None = None,
    max_retries: int = 3,
    retry_delay_seconds: float = 1.0,
    status_callback=None,
) -> GoogleDriveConversionResult:
    excel_file = Path(excel_path)
    if not excel_file.exists():
        raise GoogleDriveResponseError(f"Excel export file not found: {excel_path}")

    access_token = _ensure_access_token(Path(credentials_path), Path(token_path))
    reports_folder_id = _ensure_reports_folder(access_token)

    excel_mime = mimetypes.guess_type(excel_file.name)[0] or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    metadata = {
        "name": excel_file.stem,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [reports_folder_id],
    }

    boundary = f"metroliza-{int(time.time() * 1000)}"
    file_bytes = excel_file.read_bytes()
    body = _build_upload_request_body(
        boundary=boundary,
        metadata=metadata,
        file_mime_type=excel_mime,
        file_bytes=file_bytes,
    )

    request = urllib.request.Request(
        GOOGLE_DRIVE_UPLOAD_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        method="POST",
    )

    payload: dict[str, Any] | None = None
    if callable(status_callback):
        status_callback("uploading")

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            mapped = map_google_http_error(exc.code, body_text)
            if isinstance(mapped, (GoogleDriveTransientError, GoogleDriveQuotaError)) and attempt < max_retries:
                if callable(status_callback):
                    status_callback(f"uploading retry {attempt}/{max_retries - 1}: {mapped}")
                logger.warning(
                    "Google upload retry after HTTP error",
                    extra=_build_google_log_extra(file_ref=str(excel_file), error=mapped, outcome="retry"),
                )
                time.sleep(retry_delay_seconds)
                continue
            logger.error(
                "Google upload failed with HTTP error",
                extra=_build_google_log_extra(file_ref=str(excel_file), error=mapped, outcome="failed"),
            )
            raise mapped from exc
        except urllib.error.URLError as exc:
            mapped = map_google_network_error("Google Drive upload failed", exc)
            if attempt < max_retries:
                if callable(status_callback):
                    status_callback(f"uploading retry {attempt}/{max_retries - 1}: {mapped}")
                logger.warning(
                    "Google upload retry after network error",
                    extra=_build_google_log_extra(file_ref=str(excel_file), error=mapped, outcome="retry"),
                )
                time.sleep(retry_delay_seconds)
                continue
            logger.error(
                "Google upload failed with network error",
                extra=_build_google_log_extra(file_ref=str(excel_file), error=mapped, outcome="failed"),
            )
            raise mapped from exc

    if payload is None:
        exhausted_error = GoogleDriveTransientError("Google Drive upload exhausted retries without response payload.")
        logger.error(
            "Google upload exhausted retries",
            extra=_build_google_log_extra(file_ref=str(excel_file), error=exhausted_error, outcome="failed"),
        )
        raise exhausted_error

    parsed = parse_drive_conversion_response(payload)
    if callable(status_callback):
        status_callback("converting")

    converted_tab_titles: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    warning_details: tuple[dict[str, str], ...] = ()

    if callable(status_callback):
        status_callback("validating")

    fallback_message = ""
    if warnings:
        fallback_message = f"Conversion completed with warnings. Use local .xlsx fallback if needed: {excel_file}"
    else:
        fallback_message = f"Google conversion completed. Local .xlsx fallback available at: {excel_file}"

    result = GoogleDriveConversionResult(
        file_id=parsed.file_id,
        web_url=parsed.web_url,
        local_xlsx_path=str(excel_file),
        fallback_message=fallback_message,
        warnings=warnings,
        warning_details=warning_details,
        converted_tab_titles=converted_tab_titles,
    )
    logger.info(
        "Google Sheets conversion completed",
        extra=_build_google_log_extra(file_ref=result.web_url or result.file_id, outcome="success"),
    )
    return result
