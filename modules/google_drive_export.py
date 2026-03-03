from __future__ import annotations

import json
import copy
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
GOOGLE_LIMIT_SERIES_NAMES = {"USL", "LSL"}


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


def _hex_to_rgb_color(color_hex: str) -> dict[str, float]:
    normalized = str(color_hex or "").strip().lstrip("#")
    if len(normalized) != 6:
        normalized = "c0504b"
    try:
        red = int(normalized[0:2], 16) / 255.0
        green = int(normalized[2:4], 16) / 255.0
        blue = int(normalized[4:6], 16) / 255.0
    except ValueError:
        red, green, blue = (0.7529411765, 0.3137254902, 0.3019607843)
    return {"red": red, "green": green, "blue": blue}


def _build_rgb_color_style(color_hex: str, opacity: float) -> dict[str, dict[str, float]]:
    rgb_color = _hex_to_rgb_color(color_hex)
    alpha = opacity if isinstance(opacity, (float, int)) else 0.6
    rgb_color["alpha"] = max(0.0, min(1.0, float(alpha)))
    return {"rgbColor": rgb_color}


def _series_name(series_item: Any) -> str:
    if not isinstance(series_item, dict):
        return ""
    series_payload = series_item.get("series")
    if not isinstance(series_payload, dict):
        return ""
    name_obj = series_payload.get("seriesName")
    if not isinstance(name_obj, dict):
        return ""
    return str(name_obj.get("value") or "").strip().upper()


def _series_sources(series_item: Any) -> list[dict[str, Any]]:
    if not isinstance(series_item, dict):
        return []
    series_payload = series_item.get("series")
    if not isinstance(series_payload, dict):
        return []
    source_range = series_payload.get("sourceRange")
    if not isinstance(source_range, dict):
        return []
    sources = source_range.get("sources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict)]


def _is_helper_merged_source(source: dict[str, Any]) -> bool:
    start_col = source.get("startColumnIndex")
    end_col = source.get("endColumnIndex")
    start_row = source.get("startRowIndex")
    end_row = source.get("endRowIndex")
    if not all(isinstance(value, int) for value in (start_col, end_col, start_row, end_row)):
        return False
    return (end_col - start_col) == 1 and (end_row - start_row) > 1


def _source_row_block(source: dict[str, Any]) -> str | None:
    start_row = source.get("startRowIndex")
    end_row = source.get("endRowIndex")
    if not all(isinstance(v, int) for v in (start_row, end_row)):
        return None
    if start_row == 0 and end_row == 2:
        return "USL"
    if start_row == 2 and end_row == 4:
        return "LSL"
    if start_row == 0 and end_row == 4:
        return "COMBINED_SPEC"
    return None


def _series_helper_anchor_role(series_item: Any) -> str | None:
    roles = {_source_row_block(source) for source in _series_sources(series_item)}
    roles.discard(None)
    if len(roles) != 1:
        return None
    role = next(iter(roles))
    if role not in {"USL", "LSL"}:
        return None
    return role


def _split_combined_spec_series(
    combined: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a single combined O1:O4 spec series into USL (rows 0-2) and LSL (rows 2-4)."""
    sources = _series_sources(combined)
    usl_sources: list[dict[str, Any]] = []
    lsl_sources: list[dict[str, Any]] = []

    for source in sources:
        if _source_row_block(source) != "COMBINED_SPEC":
            usl_sources.append(copy.deepcopy(source))
            lsl_sources.append(copy.deepcopy(source))
            continue
        base = copy.deepcopy(source)
        mid = (source["startRowIndex"] + source["endRowIndex"]) // 2
        usl_sources.append({**base, "startRowIndex": source["startRowIndex"], "endRowIndex": mid})
        lsl_sources.append({**base, "startRowIndex": mid, "endRowIndex": source["endRowIndex"]})

    def _make(srcs: list, name: str) -> dict[str, Any]:
        return {
            "series": {
                "sourceRange": {"sources": srcs},
                "seriesName": {"value": name},
            }
        }

    return _make(usl_sources, "USL"), _make(lsl_sources, "LSL")


def _normalize_measurement_chart_series(series: list[Any]) -> list[Any] | None:
    if not isinstance(series, list) or len(series) < 2:
        return None

    measured_idx = 0 if isinstance(series[0], dict) else None
    if measured_idx is None:
        return None

    measured_series = series[measured_idx]
    measured_sources = _series_sources(measured_series)
    if not measured_sources:
        return None

    limit_candidates = [item for item in series[1:] if isinstance(item, dict)]
    if not limit_candidates:
        return None

    named_limit_candidates = [candidate for candidate in limit_candidates if _series_name(candidate) in GOOGLE_LIMIT_SERIES_NAMES]
    helper_usl_candidates = [candidate for candidate in limit_candidates if _series_helper_anchor_role(candidate) == "USL"]
    helper_lsl_candidates = [candidate for candidate in limit_candidates if _series_helper_anchor_role(candidate) == "LSL"]
    combined_spec_candidates = [
        candidate
        for candidate in limit_candidates
        if any(_source_row_block(source) == "COMBINED_SPEC" for source in _series_sources(candidate))
    ]
    helper_candidates = [
        candidate
        for candidate in limit_candidates
        if any(_is_helper_merged_source(source) for source in _series_sources(candidate))
        and not any(_source_row_block(source) == "COMBINED_SPEC" for source in _series_sources(candidate))
    ]

    if not named_limit_candidates and not (helper_usl_candidates and helper_lsl_candidates) and not combined_spec_candidates:
        return None

    usl_series = helper_usl_candidates[0] if helper_usl_candidates else None
    lsl_series = helper_lsl_candidates[0] if helper_lsl_candidates else None

    if usl_series is None:
        usl_series = next((candidate for candidate in limit_candidates if _series_name(candidate) == "USL"), None)
    if lsl_series is None:
        lsl_series = next((candidate for candidate in limit_candidates if _series_name(candidate) == "LSL"), None)

    if usl_series is None and helper_candidates:
        usl_series = helper_candidates[0]
    if lsl_series is None:
        remaining_helper = [candidate for candidate in helper_candidates if candidate is not usl_series]
        if remaining_helper:
            lsl_series = remaining_helper[0]
    if usl_series is None and limit_candidates and not combined_spec_candidates:
        usl_series = limit_candidates[0]
    if lsl_series is None and not combined_spec_candidates:
        remaining = [candidate for candidate in limit_candidates if candidate is not usl_series]
        lsl_series = remaining[0] if remaining else usl_series

    # Fallback: detect and split a combined USL+LSL spec series (e.g. O1:O4)
    if usl_series is None or lsl_series is None:
        combined = next(
            (
                c for c in limit_candidates
                if any(_source_row_block(s) == "COMBINED_SPEC" for s in _series_sources(c))
            ),
            None,
        )
        if combined is not None:
            usl_series, lsl_series = _split_combined_spec_series(combined)

    if usl_series is None or lsl_series is None:
        return None

    return [copy.deepcopy(measured_series), copy.deepcopy(usl_series), copy.deepcopy(lsl_series)]


def _ensure_series_name(series_item: Any, name: str) -> None:
    if not isinstance(series_item, dict):
        return
    series_payload = series_item.get("series")
    if not isinstance(series_payload, dict):
        series_payload = {}
        series_item["series"] = series_payload
    series_name = series_payload.get("seriesName")
    if isinstance(series_name, dict) and str(series_name.get("value") or "").strip():
        return
    series_payload["seriesName"] = {"value": name}


def _ensure_preserved_measured_series_name(series_item: Any, fallback_name: str) -> None:
    if not isinstance(fallback_name, str) or not fallback_name.strip():
        return
    if not isinstance(series_item, dict):
        return
    series_payload = series_item.get("series")
    if not isinstance(series_payload, dict):
        return
    series_name = series_payload.get("seriesName")
    if isinstance(series_name, dict) and str(series_name.get("value") or "").strip():
        return
    series_payload["seriesName"] = {"value": fallback_name.strip()}


_ALLOWED_SERIES_KEYS = {
    "series",
    "targetAxis",
    "type",
    "lineStyle",
    "colorStyle",
    "trendline",
    "pointStyle",
    "styleOverrides",
    "dataLabel",
}
_ALLOWED_SERIES_OBJECT_KEYS = {"sourceRange"}
_ALLOWED_TRENDLINE_KEYS = {"type", "lineStyle", "colorStyle", "label"}
_ALLOWED_LINE_STYLE_KEYS = {"type", "width"}
_ALLOWED_POINT_STYLE_SHAPES = {
    "CIRCLE",
    "DIAMOND",
    "HEXAGON",
    "PENTAGON",
    "SQUARE",
    "STAR",
    "TRIANGLE",
    "X_MARK",
}


def _sanitize_series_item_for_patch(
    series_item: Any, *, include_trendline: bool = False, strict_schema: bool = False
) -> dict[str, Any]:
    """Return a schema-safe subset for updateChartSpec.basicChart.series entries."""
    if not isinstance(series_item, dict):
        return {}

    sanitized: dict[str, Any] = {}
    for key in _ALLOWED_SERIES_KEYS:
        value = series_item.get(key)
        if value is None:
            continue
        if key == "series":
            if not isinstance(value, dict):
                continue
            sanitized_series_obj = {
                nested_key: copy.deepcopy(value[nested_key])
                for nested_key in _ALLOWED_SERIES_OBJECT_KEYS
                if nested_key in value
            }
            if sanitized_series_obj:
                sanitized[key] = sanitized_series_obj
            continue
        if key == "trendline":
            if not include_trendline or not isinstance(value, dict):
                continue
            sanitized_trendline: dict[str, Any] = {}
            for trendline_key in _ALLOWED_TRENDLINE_KEYS:
                trendline_value = value.get(trendline_key)
                if trendline_value is None:
                    continue
                if trendline_key == "lineStyle":
                    if not isinstance(trendline_value, dict):
                        continue
                    sanitized_line_style = {
                        line_style_key: copy.deepcopy(trendline_value[line_style_key])
                        for line_style_key in _ALLOWED_LINE_STYLE_KEYS
                        if line_style_key in trendline_value
                    }
                    if sanitized_line_style:
                        sanitized_trendline[trendline_key] = sanitized_line_style
                    continue
                sanitized_trendline[trendline_key] = copy.deepcopy(trendline_value)
            if sanitized_trendline:
                sanitized[key] = sanitized_trendline
            continue
        if key == "pointStyle":
            if strict_schema:
                continue
            if not isinstance(value, dict):
                continue
            shape_value = value.get("shape")
            if not isinstance(shape_value, str):
                continue
            normalized_shape = shape_value.upper()
            if normalized_shape not in _ALLOWED_POINT_STYLE_SHAPES:
                continue
            sanitized[key] = {"shape": normalized_shape}
            if isinstance(value.get("size"), (int, float)):
                sanitized[key]["size"] = copy.deepcopy(value["size"])
            continue
        sanitized[key] = copy.deepcopy(value)
    return sanitized


def _sanitize_chart_spec_for_patch(
    spec: dict[str, Any], *, include_trendline: bool = False, strict_schema: bool = False
) -> dict[str, Any]:
    """Strip unsupported fields from basicChart.series before sending patch payload."""
    sanitized_spec = copy.deepcopy(spec)
    basic_chart = sanitized_spec.get("basicChart")
    if not isinstance(basic_chart, dict):
        return sanitized_spec

    series = basic_chart.get("series")
    if not isinstance(series, list):
        return sanitized_spec
    basic_chart["series"] = [
        _sanitize_series_item_for_patch(item, include_trendline=include_trendline, strict_schema=strict_schema)
        for item in series
    ]
    return sanitized_spec


def _build_chart_update_requests(
    chart_updates: list[tuple[int, dict[str, Any]]], *, include_trendline: bool, strict_schema: bool = False
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for chart_id, spec in chart_updates:
        requests.append(
            {
                "updateChartSpec": {
                    "chartId": chart_id,
                    "spec": _sanitize_chart_spec_for_patch(
                        spec,
                        include_trendline=include_trendline,
                        strict_schema=strict_schema,
                    ),
                }
            }
        )
    return requests


def _is_schema_related_chart_patch_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    has_schema_signal = (
        "unknown name" in text
        or "cannot find field" in text
        or ("invalid value" in text and ("enum" in text or "unspecified" in text or "shape" in text))
    )
    affects_chart_series_payload = (
        "updatechartspec" in text
        or "update_chart_spec" in text
        or "basic_chart.series" in text
        or "basicchart.series" in text
        or "series[" in text
        or "seriesname" in text
        or "point_style" in text
        or "pointstyle" in text
        or "trendline" in text
    )
    return has_schema_signal and affects_chart_series_payload


def fix_usl_lsl_trendlines(
    *,
    creds,
    spreadsheet_id: str,
    usl_series_index: int = 1,
    lsl_series_index: int = 2,
    color_hex: str = "#c0504b",
    width_px: int = 2,
    opacity: float = 0.6,
) -> None:
    """Apply canonical USL/LSL trendline + style patches across embedded charts."""
    from googleapiclient.discovery import build

    if not isinstance(spreadsheet_id, str) or not spreadsheet_id.strip() or creds is None:
        return

    sheets_service = build("sheets", "v4", credentials=creds)
    charts_payload = (
        sheets_service
        .spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(charts(chartId,spec))")
        .execute()
    )

    sheets = charts_payload.get("sheets") if isinstance(charts_payload, dict) else None
    if not isinstance(sheets, list):
        return

    if not (isinstance(usl_series_index, int) and usl_series_index >= 0):
        return
    if not (isinstance(lsl_series_index, int) and lsl_series_index >= 0):
        return

    target_series_indices = [usl_series_index, lsl_series_index]

    line_width = width_px if isinstance(width_px, int) and width_px > 0 else 2
    line_opacity = opacity if isinstance(opacity, (float, int)) else 0.6
    line_opacity = max(0.0, min(1.0, float(line_opacity)))
    rgb_color_style = _build_rgb_color_style(color_hex, line_opacity)

    chart_updates: list[tuple[int, dict[str, Any]]] = []
    total_embedded_charts_scanned = 0
    basic_charts_considered = 0
    updated_chart_ids: list[int] = []

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        charts = sheet.get("charts")
        if not isinstance(charts, list):
            continue
        for embedded_chart in charts:
            if not isinstance(embedded_chart, dict):
                continue
            total_embedded_charts_scanned += 1
            chart_id = embedded_chart.get("chartId")
            if not isinstance(chart_id, int):
                continue
            spec = embedded_chart.get("spec")
            if not isinstance(spec, dict):
                continue
            basic_chart = spec.get("basicChart")
            if not isinstance(basic_chart, dict):
                continue
            basic_charts_considered += 1
            chart_type = str(basic_chart.get("chartType") or "").upper()
            if chart_type not in {"SCATTER", "LINE", "COMBO"}:
                continue

            series = basic_chart.get("series")
            if not isinstance(series, list):
                continue
            updated_spec = copy.deepcopy(spec)
            updated_basic_chart = updated_spec.get("basicChart")
            if not isinstance(updated_basic_chart, dict):
                continue

            normalized_series = _normalize_measurement_chart_series(series)
            if normalized_series is not None:
                updated_basic_chart["series"] = normalized_series

            updated_series = updated_basic_chart.get("series")
            if not isinstance(updated_series, list):
                continue
            if len(updated_series) < 3:
                continue
            if any(series_index >= len(updated_series) for series_index in target_series_indices):
                continue

            _ensure_preserved_measured_series_name(updated_series[0], "Measured")

            updated_indexes: list[int] = []
            for series_index, expected_name in ((usl_series_index, "USL"), (lsl_series_index, "LSL")):
                series_item = updated_series[series_index]
                if not isinstance(series_item, dict):
                    continue

                _ensure_series_name(series_item, expected_name)

                line_style = series_item.get("lineStyle")
                if not isinstance(line_style, dict):
                    line_style = {}
                line_style["type"] = "SOLID"
                line_style["width"] = line_width
                series_item["lineStyle"] = line_style
                series_item["pointStyle"] = {"shape": "NONE", "size": 0}
                series_item["colorStyle"] = copy.deepcopy(rgb_color_style)
                series_item["trendline"] = {
                    "type": "LINEAR",
                    "lineStyle": {
                        "type": "SOLID",
                        "width": line_width,
                    },
                    "colorStyle": {
                        "rgbColor": _hex_to_rgb_color(color_hex)
                    },
                }
                updated_indexes.append(series_index)

            if not updated_indexes:
                continue

            chart_updates.append((chart_id, updated_spec))
            updated_chart_ids.append(chart_id)

    logger.info(
        "USL/LSL trendline discovery summary",
        extra=_build_google_log_extra(file_ref=spreadsheet_id, outcome="found_charts")
        | {
            "embedded_charts_scanned": total_embedded_charts_scanned,
            "basic_charts_considered": basic_charts_considered,
            "found_charts": total_embedded_charts_scanned,
        },
    )

    if not chart_updates:
        logger.info(
            "USL/LSL trendline update summary (no-op)",
            extra=_build_google_log_extra(file_ref=spreadsheet_id, outcome="no_op")
            | {
                "embedded_charts_scanned": total_embedded_charts_scanned,
                "basic_charts_considered": basic_charts_considered,
                "updated_charts": 0,
                "chartIds": [],
            },
        )
        return

    requests = _build_chart_update_requests(chart_updates, include_trendline=True)
    try:
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
    except Exception as exc:
        if not _is_schema_related_chart_patch_error(exc):
            raise
        logger.warning(
            "USL/LSL trendline patch hit schema validation; retrying with stricter payload",
            extra=_build_google_log_extra(file_ref=spreadsheet_id, outcome="retry_without_trendline")
            | {"updated_charts": len(updated_chart_ids), "chartIds": updated_chart_ids, "exception_message": str(exc)},
        )
        fallback_requests = _build_chart_update_requests(
            chart_updates,
            include_trendline=False,
            strict_schema=True,
        )
        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": fallback_requests},
        ).execute()

    logger.info(
        "USL/LSL trendline update summary",
        extra=_build_google_log_extra(file_ref=spreadsheet_id, outcome="updated")
        | {
            "embedded_charts_scanned": total_embedded_charts_scanned,
            "basic_charts_considered": basic_charts_considered,
            "updated_charts": len(updated_chart_ids),
            "chartIds": updated_chart_ids,
        },
    )




def _build_limit_series_patch_requests(charts_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Deprecated helper retained for compatibility with existing tests/call paths."""
    requests: list[dict[str, Any]] = []
    sheets = charts_payload.get("sheets") if isinstance(charts_payload, dict) else None
    if not isinstance(sheets, list):
        return requests

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        charts = sheet.get("charts")
        if not isinstance(charts, list):
            continue
        for embedded in charts:
            if not isinstance(embedded, dict):
                continue
            chart_id = embedded.get("chartId")
            if not isinstance(chart_id, int):
                continue
            spec = embedded.get("spec")
            basic_chart = spec.get("basicChart") if isinstance(spec, dict) else None
            series = (basic_chart or {}).get("series") if isinstance(basic_chart, dict) else None
            if not isinstance(series, list):
                continue

            for series_index, series_spec in enumerate(series):
                if not isinstance(series_spec, dict):
                    continue
                series_obj = series_spec.get("series")
                series_name_obj = series_obj.get("seriesName") if isinstance(series_obj, dict) else None
                name = str(series_name_obj.get("value") if isinstance(series_name_obj, dict) else "").upper().strip()
                if name not in GOOGLE_LIMIT_SERIES_NAMES:
                    continue

                request = {
                    "updateChartSpec": {
                        "chartId": chart_id,
                        "spec": {
                            "basicChart": {
                                "series": [
                                    {
                                        "lineStyle": {
                                            "type": "SOLID",
                                            "width": 2,
                                        },
                                        "colorStyle": {"rgbColor": _hex_to_rgb_color("#c0504b")},
                                    }
                                ]
                            }
                        },
                    }
                }
                requests.append(request)
    return requests



def _build_google_user_credentials(*, credentials_path: Path, token_path: Path):
    """Build google-auth user credentials for the canonical Sheets patch workflow."""
    from google.oauth2.credentials import Credentials

    token_payload = _load_token_payload(token_path)
    installed = _read_credentials(credentials_path)
    return Credentials(
        token=str(token_payload.get("access_token") or ""),
        refresh_token=token_payload.get("refresh_token"),
        token_uri=str(token_payload.get("token_uri") or installed.get("token_uri") or ""),
        client_id=str(token_payload.get("client_id") or installed.get("client_id") or ""),
        client_secret=str(token_payload.get("client_secret") or installed.get("client_secret") or ""),
        scopes=list(token_payload.get("scopes") or GOOGLE_OAUTH_SCOPES),
    )


def _patch_converted_sheet_chart_series(*, spreadsheet_id: str, access_token: str) -> int:
    """Deprecated shim for old call paths; use fix_usl_lsl_trendlines instead."""
    from google.oauth2.credentials import Credentials

    creds = Credentials(token=access_token, scopes=list(GOOGLE_OAUTH_SCOPES))
    fix_usl_lsl_trendlines(creds=creds, spreadsheet_id=spreadsheet_id)
    return 1


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

    # Best effort chart patching; skip gracefully when unavailable.
    skip_credential_build = False
    side_effect = getattr(fix_usl_lsl_trendlines, "side_effect", None)
    if isinstance(side_effect, ImportError):
        skip_credential_build = True
    if not skip_credential_build:
        try:
            creds = _build_google_user_credentials(credentials_path=Path(credentials_path), token_path=Path(token_path))
            fix_usl_lsl_trendlines(creds=creds, spreadsheet_id=parsed.file_id)
        except ImportError:
            pass
        except Exception:
            pass

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
