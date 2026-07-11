import json
import os
import stat
import tempfile
import unittest
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import sys

from metroliza.exporting.google_drive_export import (
    GOOGLE_DRIVE_REPORTS_FOLDER_NAME,
    GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES,
    GOOGLE_DRIVE_RESUMABLE_THRESHOLD_BYTES,
    GOOGLE_DRIVE_RESUMABLE_UPLOAD_URL,
    GOOGLE_DRIVE_SCOPE,
    GOOGLE_DRIVE_UPLOAD_URL,
    GOOGLE_OAUTH_SCOPES,
    GoogleDriveAuthError,
    GoogleDriveCanceledError,
    GoogleDriveQuotaError,
    GoogleDriveResponseError,
    GoogleDriveTimeoutError,
    GoogleDriveTransientError,
    TokenStore,
    _build_upload_request_body,
    _resolve_credentials_path,
    _load_token_payload,
    _migrate_legacy_token_if_present,
    _refresh_access_token,
    _urlopen_google_https,
    map_google_http_error,
    map_google_network_error,
    parse_drive_conversion_response,
    parse_spreadsheet_tab_titles,
    upload_and_convert_workbook,
)


class _FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def read(self):
        if isinstance(self._payload, bytes):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGoogleDriveExport(unittest.TestCase):
    def test_resolve_credentials_path_prefers_existing_relative_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            credentials = cwd / "credentials.json"
            credentials.write_text("{}", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                resolved = _resolve_credentials_path("credentials.json")
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(credentials, resolved)

    def test_resolve_credentials_path_uses_executable_directory_when_cwd_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            executable_dir = base / "bundle"
            executable_dir.mkdir(parents=True, exist_ok=True)
            executable_credentials = executable_dir / "credentials.json"
            executable_credentials.write_text("{}", encoding="utf-8")
            fake_executable = executable_dir / "metroliza.exe"

            with patch.object(sys, "executable", str(fake_executable)):
                resolved = _resolve_credentials_path("credentials.json")

            self.assertEqual(executable_credentials, resolved)

    def test_upload_url_requests_only_drive_v3_supported_fields(self):
        self.assertNotIn("alternateLink", GOOGLE_DRIVE_UPLOAD_URL)
        self.assertIn("webViewLink", GOOGLE_DRIVE_UPLOAD_URL)
        self.assertIn("webContentLink", GOOGLE_DRIVE_UPLOAD_URL)

    def test_parse_drive_conversion_response_success(self):
        payload = {"id": "abc123", "webViewLink": "https://docs.google.com/spreadsheets/d/abc123/edit"}

        result = parse_drive_conversion_response(payload)

        self.assertEqual("abc123", result.file_id)
        self.assertEqual("https://docs.google.com/spreadsheets/d/abc123/edit", result.web_url)

    def test_parse_drive_conversion_response_missing_fields(self):
        with self.assertRaises(GoogleDriveResponseError):
            parse_drive_conversion_response({"name": "missing fields"})

    def test_parse_drive_conversion_response_accepts_alternate_link_fallback(self):
        payload = {"id": "alt987", "alternateLink": "https://docs.google.com/spreadsheets/d/alt987/edit"}

        result = parse_drive_conversion_response(payload)

        self.assertEqual("alt987", result.file_id)
        self.assertEqual("https://docs.google.com/spreadsheets/d/alt987/edit", result.web_url)

    def test_parse_spreadsheet_tab_titles_extracts_sheet_titles(self):
        payload = {
            "sheets": [
                {"properties": {"title": "MEASUREMENTS"}},
                {"properties": {"title": "REF_A"}},
            ]
        }

        self.assertEqual(("MEASUREMENTS", "REF_A"), parse_spreadsheet_tab_titles(payload))

    def test_map_google_http_error_auth(self):
        payload = json.dumps(
            {
                "error": {
                    "message": "Request had invalid authentication credentials.",
                    "errors": [{"reason": "authError"}],
                }
            }
        )

        error = map_google_http_error(401, payload)

        self.assertIsInstance(error, GoogleDriveAuthError)

    def test_map_google_http_error_quota(self):
        payload = json.dumps(
            {
                "error": {
                    "message": "Rate Limit Exceeded",
                    "errors": [{"reason": "userRateLimitExceeded"}],
                }
            }
        )

        error = map_google_http_error(403, payload)

        self.assertIsInstance(error, GoogleDriveQuotaError)

    def test_map_google_http_error_transient(self):
        payload = json.dumps(
            {
                "error": {
                    "message": "Backend Error",
                    "errors": [{"reason": "backendError"}],
                }
            }
        )

        error = map_google_http_error(503, payload)

        self.assertIsInstance(error, GoogleDriveTransientError)

    def test_map_google_http_error_edge_cases_for_401_403_429_and_5xx(self):
        unauthorized = map_google_http_error(401, json.dumps({"error": {"message": "Denied"}}))
        forbidden_auth = map_google_http_error(
            403,
            json.dumps({"error": {"message": "Forbidden", "errors": [{"reason": "insufficientPermissions"}]}}),
        )
        rate_limited = map_google_http_error(429, "not-json")
        server_error = map_google_http_error(500, json.dumps({"error": {"message": "Server exploded"}}))

        self.assertIsInstance(unauthorized, GoogleDriveResponseError)
        self.assertIn("Google API error", str(unauthorized))
        self.assertIsInstance(forbidden_auth, GoogleDriveAuthError)
        self.assertIsInstance(rate_limited, GoogleDriveQuotaError)
        self.assertIsInstance(server_error, GoogleDriveTransientError)

    def test_network_error_maps_to_transient(self):
        url_error = urllib.error.URLError("temporary network failure")

        transient = map_google_network_error("Google Drive upload failed", url_error)

        self.assertIsInstance(transient, GoogleDriveTransientError)
        self.assertIn("Google Drive upload failed", str(transient))

    def test_google_https_transport_rejects_unsafe_urls_before_urlopen(self):
        unsafe_urls = (
            "http://www.googleapis.com/drive/v3/files",
            "file:///tmp/fake-google-response.json",
            "https://example.com/drive/v3/files",
        )

        with patch(
            "metroliza.exporting.google_drive_export.urllib.request.urlopen"
        ) as urlopen_mock:
            for unsafe_url in unsafe_urls:
                with self.subTest(url=unsafe_url), self.assertRaises(GoogleDriveResponseError):
                    _urlopen_google_https(
                        urllib.request.Request(unsafe_url),
                        timeout=30,
                    )

        urlopen_mock.assert_not_called()

    def test_google_https_transport_opens_approved_google_api_url(self):
        request = urllib.request.Request("https://www.googleapis.com/drive/v3/files")
        response = _FakeResponse({"files": []})

        with patch(
            "metroliza.exporting.google_drive_export.urllib.request.urlopen",
            return_value=response,
        ) as urlopen_mock:
            opened = _urlopen_google_https(request, timeout=30)

        self.assertIs(response, opened)
        urlopen_mock.assert_called_once_with(request, timeout=30)

    def test_build_upload_request_body_contains_metadata_and_file(self):
        body = _build_upload_request_body(
            boundary="abc",
            metadata={"name": "out", "mimeType": "application/vnd.google-apps.spreadsheet"},
            file_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_bytes=b"xlsx-bytes",
        )

        text = body.decode("utf-8", errors="replace")
        self.assertIn("--abc", text)
        self.assertIn('"name": "out"', text)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", text)
        self.assertIn("xlsx-bytes", text)


    def test_upload_and_convert_workbook_success_mapping_and_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            captured = {"upload_data": None, "folder_lookup": 0, "validation": 0}

            def fake_urlopen(request, timeout=0):
                if request.method == "GET" and "sheets.googleapis.com/v4/spreadsheets/sheet123" in request.full_url:
                    captured["validation"] += 1
                    return _FakeResponse(
                        {
                            "sheets": [
                                {"properties": {"title": "MEASUREMENTS"}},
                                {"properties": {"title": "REF_A"}},
                            ]
                        }
                    )
                if request.method == "GET" and "www.googleapis.com/drive/v3/files" in request.full_url:
                    captured["folder_lookup"] += 1
                    return _FakeResponse({"files": [{"id": "folder-123", "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME}]})
                if request.method == "POST" and "upload/drive/v3/files" in request.full_url:
                    captured["upload_data"] = request.data
                    return _FakeResponse(
                        {
                            "id": "sheet123",
                            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123/edit",
                        }
                    )
                raise AssertionError(f"Unexpected request: {request.method} {request.full_url}")

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ):
                result = upload_and_convert_workbook(
                    str(excel_path),
                    expected_sheet_names=["MEASUREMENTS", "REF_A"],
                    max_retries=1,
                )

            self.assertEqual("sheet123", result.file_id)
            self.assertEqual(str(excel_path), result.local_xlsx_path)
            self.assertEqual(("MEASUREMENTS", "REF_A"), result.converted_tab_titles)
            self.assertEqual("", result.fallback_message)
            self.assertIn(b"application/vnd.google-apps.spreadsheet", captured["upload_data"])
            self.assertIn(b"\"parents\": [\"folder-123\"]", captured["upload_data"])
            self.assertEqual(1, captured["folder_lookup"])
            self.assertEqual(1, captured["validation"])

    def test_upload_and_convert_workbook_warns_when_converted_tabs_do_not_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")
            deleted_file_ids = []

            def fake_urlopen(request, timeout=0):
                if request.method == "DELETE":
                    deleted_file_ids.append(request.full_url.rsplit("/", 1)[-1])
                    return _FakeResponse({}, status=204)
                if request.method == "GET" and "sheets.googleapis.com/v4/spreadsheets/sheet123" in request.full_url:
                    return _FakeResponse(
                        {
                            "sheets": [
                                {"properties": {"title": "MEASUREMENTS"}},
                                {"properties": {"title": "Renamed"}},
                            ]
                        }
                    )
                if request.method == "GET" and "www.googleapis.com/drive/v3/files" in request.full_url:
                    return _FakeResponse({"files": [{"id": "folder-123", "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME}]})
                if request.method == "POST" and "upload/drive/v3/files" in request.full_url:
                    return _FakeResponse(
                        {
                            "id": "sheet123",
                            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123/edit",
                        }
                    )
                raise AssertionError(f"Unexpected request: {request.method} {request.full_url}")

            statuses = []
            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ):
                result = upload_and_convert_workbook(
                    str(excel_path),
                    expected_sheet_names=["MEASUREMENTS", "REF_A"],
                    max_retries=1,
                    status_callback=statuses.append,
                )

            self.assertEqual(("MEASUREMENTS", "Renamed"), result.converted_tab_titles)
            self.assertIn("Google Sheets conversion is missing expected workbook tabs.", result.warnings)
            self.assertEqual("MEASUREMENTS, REF_A", result.warning_details[0]["expected"])
            self.assertEqual("MEASUREMENTS, Renamed", result.warning_details[0]["actual"])
            self.assertIn("Use local .xlsx fallback", result.fallback_message)
            self.assertEqual(["uploading", "converting", "validating"], statuses)
            self.assertEqual([], deleted_file_ids)

    def test_upload_and_convert_workbook_retries_retryable_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            attempts = {"count": 0}

            def fake_urlopen(request, timeout=0):
                if request.method == "GET":
                    return _FakeResponse({"files": [{"id": "folder-123", "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME}]})
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise urllib.error.URLError("temporary down")
                return _FakeResponse(
                    {
                        "id": "sheet456",
                        "webViewLink": "https://docs.google.com/spreadsheets/d/sheet456/edit",
                    }
                )

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("metroliza.exporting.google_drive_export.time.sleep") as sleep_mock:
                result = upload_and_convert_workbook(str(excel_path), max_retries=2, retry_delay_seconds=0)

            self.assertEqual("sheet456", result.file_id)
            self.assertEqual(attempts["count"], 2)
            sleep_mock.assert_called_once()

    def test_upload_and_convert_workbook_retries_with_deterministic_backoff_on_http_and_network_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            attempts = {"count": 0}

            def _http_error(status_code: int, payload: dict):
                return urllib.error.HTTPError(
                    GOOGLE_DRIVE_UPLOAD_URL,
                    status_code,
                    "error",
                    hdrs=None,
                    fp=BytesIO(json.dumps(payload).encode("utf-8")),
                )

            def fake_urlopen(request, timeout=0):
                if request.method == "GET":
                    return _FakeResponse({"files": [{"id": "folder-123", "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME}]})
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise _http_error(503, {"error": {"message": "Backend Error", "errors": [{"reason": "backendError"}]}})
                if attempts["count"] == 2:
                    raise urllib.error.URLError("temporary network failure")
                return _FakeResponse(
                    {
                        "id": "sheet456",
                        "webViewLink": "https://docs.google.com/spreadsheets/d/sheet456/edit",
                    }
                )

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("metroliza.exporting.google_drive_export.time.sleep") as sleep_mock:
                result = upload_and_convert_workbook(str(excel_path), max_retries=3, retry_delay_seconds=0.25)

            self.assertEqual("sheet456", result.file_id)
            self.assertEqual(attempts["count"], 3)
            self.assertEqual(sleep_mock.call_count, 2)
            sleep_mock.assert_any_call(0.25)


    def test_upload_routes_below_threshold_to_multipart_and_threshold_to_resumable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            small_path = base / "small.xlsx"
            threshold_path = base / "threshold.xlsx"
            with small_path.open("wb") as handle:
                handle.truncate(GOOGLE_DRIVE_RESUMABLE_THRESHOLD_BYTES - 1)
            with threshold_path.open("wb") as handle:
                handle.truncate(GOOGLE_DRIVE_RESUMABLE_THRESHOLD_BYTES)

            session_url = (
                "https://www.googleapis.com/upload/drive/v3/files?upload_id=threshold-session"
            )
            requests = []

            def fake_urlopen(request, timeout=0):
                requests.append((request.method, request.full_url))
                if request.full_url == GOOGLE_DRIVE_UPLOAD_URL:
                    return _FakeResponse(
                        {
                            "id": "small-sheet",
                            "webViewLink": "https://docs.google.com/spreadsheets/d/small-sheet/edit",
                        }
                    )
                if request.full_url == GOOGLE_DRIVE_RESUMABLE_UPLOAD_URL:
                    return _FakeResponse({}, headers={"Location": session_url})
                if request.method == "PUT" and request.full_url == session_url:
                    return _FakeResponse(
                        {
                            "id": "threshold-sheet",
                            "webViewLink": (
                                "https://docs.google.com/spreadsheets/d/threshold-sheet/edit"
                            ),
                        }
                    )
                raise AssertionError(f"Unexpected request: {request.method} {request.full_url}")

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ):
                small_result = upload_and_convert_workbook(str(small_path), max_retries=1)
                threshold_result = upload_and_convert_workbook(
                    str(threshold_path),
                    max_retries=1,
                )

            self.assertEqual("small-sheet", small_result.file_id)
            self.assertEqual("threshold-sheet", threshold_result.file_id)
            self.assertIn(("POST", GOOGLE_DRIVE_UPLOAD_URL), requests)
            self.assertIn(("POST", GOOGLE_DRIVE_RESUMABLE_UPLOAD_URL), requests)
            self.assertIn(("PUT", session_url), requests)
            self.assertFalse(any(method == "DELETE" for method, _url in requests))

    def test_resumable_upload_rejects_untrusted_location_before_chunk_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            with excel_path.open("wb") as handle:
                handle.truncate(GOOGLE_DRIVE_RESUMABLE_THRESHOLD_BYTES)
            requested_urls = []

            def fake_urlopen(request, timeout=0):
                requested_urls.append(request.full_url)
                return _FakeResponse(
                    {},
                    headers={"Location": "https://example.com/upload/session-id"},
                )

            with patch(
                "metroliza.exporting.google_drive_export._ensure_access_token",
                return_value="token",
            ), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ):
                with self.assertRaisesRegex(GoogleDriveResponseError, "invalid session URL"):
                    upload_and_convert_workbook(str(excel_path), max_retries=1)

            self.assertEqual([GOOGLE_DRIVE_RESUMABLE_UPLOAD_URL], requested_urls)

    def test_resumable_upload_uses_fixed_chunk_offsets_and_retries_current_chunk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "large.xlsx"
            total_bytes = (2 * GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES) + 3
            with excel_path.open("wb") as handle:
                handle.truncate(total_bytes)

            session_url = (
                "https://www.googleapis.com/upload/drive/v3/files?upload_id=chunk-session"
            )
            first_end = GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES - 1
            second_end = (2 * GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES) - 1
            first_range = f"bytes 0-{first_end}/{total_bytes}"
            second_range = (
                f"bytes {GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES}-{second_end}/{total_bytes}"
            )
            final_range = f"bytes {second_end + 1}-{total_bytes - 1}/{total_bytes}"
            chunk_requests = []
            session_headers = {}

            def fake_urlopen(request, timeout=0):
                request_headers = {
                    key.lower(): value for key, value in request.header_items()
                }
                if request.full_url == GOOGLE_DRIVE_RESUMABLE_UPLOAD_URL:
                    session_headers.update(request_headers)
                    return _FakeResponse({}, headers={"Location": session_url})
                if request.method != "PUT" or request.full_url != session_url:
                    raise AssertionError(
                        f"Unexpected request: {request.method} {request.full_url}"
                    )

                content_range = request_headers["content-range"]
                chunk_requests.append((content_range, len(request.data or b"")))
                if content_range == second_range and sum(
                    seen_range == second_range for seen_range, _size in chunk_requests
                ) == 1:
                    raise urllib.error.URLError("connection reset after first chunk")
                if content_range == first_range:
                    raise urllib.error.HTTPError(
                        session_url,
                        308,
                        "Resume Incomplete",
                        {"Range": f"bytes=0-{first_end}"},
                        BytesIO(),
                    )
                if content_range == second_range:
                    return _FakeResponse(
                        {},
                        status=308,
                        headers={"Range": f"bytes=0-{second_end}"},
                    )
                if content_range == final_range:
                    return _FakeResponse(
                        {
                            "id": "large-sheet",
                            "webViewLink": (
                                "https://docs.google.com/spreadsheets/d/large-sheet/edit"
                            ),
                        }
                    )
                raise AssertionError(f"Unexpected chunk range: {content_range}")

            statuses = []
            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ), patch("metroliza.exporting.google_drive_export.time.sleep") as sleep_mock:
                result = upload_and_convert_workbook(
                    str(excel_path),
                    max_retries=2,
                    retry_delay_seconds=0.25,
                    status_callback=statuses.append,
                )

            self.assertEqual("large-sheet", result.file_id)
            self.assertEqual(
                [
                    (first_range, GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES),
                    (second_range, GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES),
                    (second_range, GOOGLE_DRIVE_RESUMABLE_CHUNK_BYTES),
                    (final_range, 3),
                ],
                chunk_requests,
            )
            self.assertEqual(str(total_bytes), session_headers["x-upload-content-length"])
            self.assertIn("spreadsheetml.sheet", session_headers["x-upload-content-type"])
            sleep_mock.assert_called_once_with(0.25)
            self.assertEqual("uploading", statuses[0])
            self.assertTrue(any(status.startswith("uploading retry 2/2") for status in statuses))

    def test_cancellation_after_upload_deletes_created_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")
            canceled = {"value": False}
            deleted_urls = []

            def fake_urlopen(request, timeout=0):
                if request.method == "DELETE":
                    deleted_urls.append(request.full_url)
                    return _FakeResponse({}, status=204)
                canceled["value"] = True
                return _FakeResponse(
                    {
                        "id": "cancel-orphan",
                        "webViewLink": (
                            "https://docs.google.com/spreadsheets/d/cancel-orphan/edit"
                        ),
                    }
                )

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ):
                with self.assertRaises(GoogleDriveCanceledError):
                    upload_and_convert_workbook(
                        str(excel_path),
                        max_retries=1,
                        should_cancel=lambda: canceled["value"],
                    )

            self.assertEqual(
                ["https://www.googleapis.com/drive/v3/files/cancel-orphan"],
                deleted_urls,
            )

    def test_timeout_after_upload_deletes_created_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")
            clock = {"now": 0.0}
            deleted_urls = []

            def fake_urlopen(request, timeout=0):
                if request.method == "DELETE":
                    deleted_urls.append(request.full_url)
                    return _FakeResponse({}, status=204)
                clock["now"] = 2.0
                return _FakeResponse(
                    {
                        "id": "timeout-orphan",
                        "webViewLink": (
                            "https://docs.google.com/spreadsheets/d/timeout-orphan/edit"
                        ),
                    }
                )

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ), patch(
                "metroliza.exporting.google_drive_export.time.monotonic",
                side_effect=lambda: clock["now"],
            ):
                with self.assertRaises(GoogleDriveTimeoutError):
                    upload_and_convert_workbook(
                        str(excel_path),
                        max_retries=1,
                        overall_timeout_seconds=1.0,
                    )

            self.assertEqual(
                ["https://www.googleapis.com/drive/v3/files/timeout-orphan"],
                deleted_urls,
            )

    def test_fatal_validation_failure_deletes_created_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")
            deleted_urls = []
            validation_error = GoogleDriveResponseError("fatal validation failure")

            def fake_urlopen(request, timeout=0):
                if request.method == "DELETE":
                    deleted_urls.append(request.full_url)
                    return _FakeResponse({}, status=204)
                return _FakeResponse(
                    {
                        "id": "validation-orphan",
                        "webViewLink": (
                            "https://docs.google.com/spreadsheets/d/validation-orphan/edit"
                        ),
                    }
                )

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export._fetch_converted_tab_titles",
                side_effect=validation_error,
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ):
                with self.assertRaises(GoogleDriveResponseError) as caught:
                    upload_and_convert_workbook(
                        str(excel_path),
                        expected_sheet_names=["MEASUREMENTS"],
                        max_retries=1,
                    )

            self.assertIs(validation_error, caught.exception)
            self.assertEqual(
                ["https://www.googleapis.com/drive/v3/files/validation-orphan"],
                deleted_urls,
            )

    def test_cleanup_failure_does_not_mask_original_post_create_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")
            validation_error = GoogleDriveResponseError("keep this validation error")

            def fake_urlopen(request, timeout=0):
                if request.method == "DELETE":
                    raise RuntimeError("cleanup also failed")
                return _FakeResponse(
                    {
                        "id": "cleanup-failure-orphan",
                        "webViewLink": (
                            "https://docs.google.com/spreadsheets/d/cleanup-failure-orphan/edit"
                        ),
                    }
                )

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder",
                return_value="folder-123",
            ), patch(
                "metroliza.exporting.google_drive_export._fetch_converted_tab_titles",
                side_effect=validation_error,
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                side_effect=fake_urlopen,
            ), patch(
                "metroliza.exporting.google_drive_export.logger.warning",
                side_effect=RuntimeError("cleanup logging failed too"),
            ):
                with self.assertRaises(GoogleDriveResponseError) as caught:
                    upload_and_convert_workbook(
                        str(excel_path),
                        expected_sheet_names=["MEASUREMENTS"],
                        max_retries=1,
                    )

            self.assertIs(validation_error, caught.exception)


    def test_upload_and_convert_workbook_creates_reports_folder_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            calls = {"create_folder": 0, "upload": 0}

            def fake_urlopen(request, timeout=0):
                if request.method == "GET":
                    return _FakeResponse({"files": []})
                if request.method == "POST" and request.full_url.endswith("?fields=id"):
                    calls["create_folder"] += 1
                    return _FakeResponse({"id": "new-folder-789"})
                calls["upload"] += 1
                return _FakeResponse({"id": "sheet123", "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123/edit"})

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ):
                result = upload_and_convert_workbook(str(excel_path), max_retries=1)

            self.assertEqual("sheet123", result.file_id)
            self.assertEqual(1, calls["create_folder"])
            self.assertEqual(1, calls["upload"])

    def test_parse_drive_conversion_response_accepts_web_content_link_fallback(self):
        payload = {"id": "abc123", "webContentLink": "https://drive.google.com/file/d/abc123/view"}

        result = parse_drive_conversion_response(payload)

        self.assertEqual("abc123", result.file_id)
        self.assertEqual("https://drive.google.com/file/d/abc123/view", result.web_url)

    def test_upload_and_convert_workbook_can_cancel_during_retry_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            attempts = {"count": 0}
            cancel_state = {"calls": 0}

            def should_cancel():
                cancel_state["calls"] += 1
                return cancel_state["calls"] > 6

            def fake_urlopen(request, timeout=0):
                if request.method == "GET":
                    return _FakeResponse({"files": [{"id": "folder-123", "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME}]})
                attempts["count"] += 1
                raise urllib.error.URLError("temporary network failure")

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("metroliza.exporting.google_drive_export.time.sleep"):
                with self.assertRaises(GoogleDriveCanceledError):
                    upload_and_convert_workbook(
                        str(excel_path),
                        max_retries=3,
                        retry_delay_seconds=0,
                        should_cancel=should_cancel,
                    )

            self.assertGreaterEqual(attempts["count"], 1)
            self.assertLess(attempts["count"], 3)

    def test_upload_and_convert_workbook_raises_timeout_with_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            attempts = {"count": 0}

            def fake_urlopen(request, timeout=0):
                if request.method == "GET":
                    return _FakeResponse({"files": [{"id": "folder-123", "name": GOOGLE_DRIVE_REPORTS_FOLDER_NAME}]})
                attempts["count"] += 1
                raise urllib.error.URLError("temporary network failure")

            monotonic_values = iter([0, 0, 0, 0, 0, 3, 4, 5, 6, 7])

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("metroliza.exporting.google_drive_export.time.sleep"), patch(
                "metroliza.exporting.google_drive_export.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ):
                with self.assertRaises(GoogleDriveTimeoutError):
                    upload_and_convert_workbook(
                        str(excel_path),
                        max_retries=3,
                        retry_delay_seconds=0,
                        stage_timeout_seconds={"upload": 1.0},
                    )

            self.assertLessEqual(attempts["count"], 1)

    def test_upload_and_convert_workbook_does_not_time_out_folder_before_folder_stage_starts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            monotonic_values = iter([0, 0, 5, 10, 10.01, 10.01, 10.01, 10.01, 10.01])

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder", return_value="folder-123"
            ), patch(
                "metroliza.exporting.google_drive_export.urllib.request.urlopen",
                return_value=_FakeResponse({"id": "abc123", "webViewLink": "https://drive.google.com/file/d/abc123/view"}),
            ), patch(
                "metroliza.exporting.google_drive_export.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ):
                result = upload_and_convert_workbook(
                    str(excel_path),
                    max_retries=1,
                    stage_timeout_seconds={"folder": 0.05},
                )

            self.assertEqual("abc123", result.file_id)


    def test_upload_and_convert_workbook_prioritizes_cancellation_over_post_auth_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            monotonic_values = iter([0, 0, 0.1, 2.5])

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder", return_value="folder-123"
            ) as ensure_folder, patch(
                "metroliza.exporting.google_drive_export.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ):
                with self.assertRaises(GoogleDriveCanceledError):
                    upload_and_convert_workbook(
                        str(excel_path),
                        max_retries=1,
                        should_cancel=lambda: True,
                        stage_timeout_seconds={"auth": 1.0},
                    )

            ensure_folder.assert_not_called()
    def test_upload_and_convert_workbook_raises_auth_stage_timeout_after_slow_token_ensure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            monotonic_values = iter([0, 0, 0.1, 2.5])

            with patch("metroliza.exporting.google_drive_export._ensure_access_token", return_value="token"), patch(
                "metroliza.exporting.google_drive_export._ensure_reports_folder", return_value="folder-123"
            ) as ensure_folder, patch(
                "metroliza.exporting.google_drive_export.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ):
                with self.assertRaises(GoogleDriveTimeoutError) as exc:
                    upload_and_convert_workbook(
                        str(excel_path),
                        max_retries=1,
                        stage_timeout_seconds={"auth": 1.0},
                    )

            self.assertIn("during auth", str(exc.exception))
            ensure_folder.assert_not_called()


    def test_oauth_scopes_include_drive_only(self):
        self.assertEqual((GOOGLE_DRIVE_SCOPE,), GOOGLE_OAUTH_SCOPES)

    def test_load_token_payload_missing_file_raises_auth_error_with_stable_guidance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "token.json"

            with self.assertRaises(GoogleDriveAuthError) as exc:
                _load_token_payload(token_path)

        self.assertIn("Missing token.json", str(exc.exception))

    @unittest.skipUnless(os.name == "posix", "POSIX permission contract")
    def test_token_store_writes_atomically_with_private_permissions_and_drops_client_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "private" / "token.json"
            TokenStore(token_path).save(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "expires_at": 123,
                }
            )

            payload = json.loads(token_path.read_text(encoding="utf-8"))

            self.assertEqual("access", payload["access_token"])
            self.assertEqual("refresh", payload["refresh_token"])
            self.assertNotIn("client_id", payload)
            self.assertNotIn("client_secret", payload)
            self.assertEqual(0o600, stat.S_IMODE(token_path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(token_path.parent.stat().st_mode))

    def test_token_store_failed_replace_preserves_previous_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "token.json"
            store = TokenStore(token_path)
            store.save({"access_token": "old", "expires_at": 123})

            with patch("metroliza.exporting.google_drive_export.os.replace", side_effect=OSError("boom")):
                with self.assertRaisesRegex(OSError, "boom"):
                    store.save({"access_token": "new", "expires_at": 456})

            self.assertEqual("old", json.loads(token_path.read_text())["access_token"])
            self.assertEqual([], list(token_path.parent.glob(".*.tmp")))

    def test_token_store_rejects_symlink_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "target.json"
            target_path.write_text("{}", encoding="utf-8")
            token_path = Path(tmpdir) / "token.json"
            try:
                token_path.symlink_to(target_path)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")

            with self.assertRaisesRegex(GoogleDriveAuthError, "symlink"):
                TokenStore(token_path).load()

    def test_legacy_token_migration_removes_source_only_after_private_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = Path(tmpdir) / "working"
            working_dir.mkdir()
            private_path = Path(tmpdir) / "private" / "token.json"
            legacy_path = working_dir / "token.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "access_token": "legacy",
                        "refresh_token": "refresh",
                        "client_secret": "remove-me",
                        "expires_at": 123,
                    }
                ),
                encoding="utf-8",
            )

            previous_cwd = Path.cwd()
            os.chdir(working_dir)
            try:
                _migrate_legacy_token_if_present(TokenStore(private_path))
            finally:
                os.chdir(previous_cwd)

            self.assertFalse(legacy_path.exists())
            self.assertEqual("legacy", json.loads(private_path.read_text())["access_token"])
            self.assertNotIn("client_secret", private_path.read_text())


    def test_refresh_access_token_sets_drive_scope_when_missing(self):
        token_payload = {"refresh_token": "refresh-token"}
        credentials = {
            "client_id": "id",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        with patch("metroliza.exporting.google_drive_export.urllib.request.urlopen", return_value=_FakeResponse({"access_token": "new-token", "expires_in": 3600})):
            refreshed = _refresh_access_token(token_payload, credentials)

        self.assertEqual(GOOGLE_DRIVE_SCOPE, refreshed["scope"])

    def test_interactive_oauth_authorization_defaults_to_drive_only_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "client-id",
                            "client_secret": "client-secret",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                ),
                encoding="utf-8",
            )

            class _FakeCredentials:
                token = "access-token"
                refresh_token = "refresh-token"
                token_uri = "https://oauth2.googleapis.com/token"
                client_id = "client-id"
                client_secret = "client-secret"
                scopes = None
                scope = None
                expiry = None

            class _FakeInstalledAppFlow:
                @classmethod
                def from_client_secrets_file(cls, _path, scopes=None):
                    _ = scopes
                    return cls()

                def run_local_server(self, **_kwargs):
                    return _FakeCredentials()

            with patch.dict(
                "sys.modules",
                {"google_auth_oauthlib.flow": type("M", (), {"InstalledAppFlow": _FakeInstalledAppFlow})()},
            ):
                from metroliza.exporting.google_drive_export import _interactive_oauth_authorization

                payload = _interactive_oauth_authorization(credentials_path, token_path)

            self.assertEqual([GOOGLE_DRIVE_SCOPE], payload["scopes"])
            self.assertEqual(GOOGLE_DRIVE_SCOPE, payload["scope"])
            self.assertNotIn("client_id", payload)
            self.assertNotIn("client_secret", payload)
            persisted = json.loads(token_path.read_text(encoding="utf-8"))
            self.assertNotIn("client_id", persisted)
            self.assertNotIn("client_secret", persisted)

    def test_refresh_access_token_without_refresh_token_requires_reauthentication(self):
        with self.assertRaises(GoogleDriveAuthError) as exc:
            _refresh_access_token(
                {"access_token": "expired", "expires_at": 0},
                {"client_id": "id", "client_secret": "secret", "token_uri": "https://oauth2.googleapis.com/token"},
            )

        self.assertIn("Re-authenticate", str(exc.exception))

    def test_refresh_access_token_rejects_non_google_token_uri(self):
        with self.assertRaises(GoogleDriveAuthError) as exc:
            _refresh_access_token(
                {"refresh_token": "refresh-token"},
                {"client_id": "id", "client_secret": "secret", "token_uri": "http://example.com/token"},
            )

        self.assertIn("Google HTTPS OAuth token endpoint", str(exc.exception))

    def test_ensure_access_token_rejects_malformed_credentials_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(json.dumps({"installed": ["bad"]}), encoding="utf-8")

            from metroliza.exporting.google_drive_export import _ensure_access_token

            with self.assertRaises(GoogleDriveAuthError) as exc:
                _ensure_access_token(credentials_path, token_path)

        self.assertIn("must include an 'installed' or 'web' OAuth client section", str(exc.exception))

    def test_ensure_access_token_rejects_invalid_token_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "client-id",
                            "client_secret": "client-secret",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                ),
                encoding="utf-8",
            )
            token_path.write_text("{not valid json", encoding="utf-8")

            from metroliza.exporting.google_drive_export import _ensure_access_token

            with self.assertRaises(GoogleDriveAuthError) as exc:
                _ensure_access_token(credentials_path, token_path)

        self.assertIn("Invalid JSON content", str(exc.exception))

    def test_interactive_oauth_authorization_maps_cancellation_to_auth_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "client-id",
                            "client_secret": "client-secret",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                ),
                encoding="utf-8",
            )

            class _FakeInstalledAppFlow:
                @classmethod
                def from_client_secrets_file(cls, _path, scopes=None):
                    _ = scopes
                    return cls()

                def run_local_server(self, **_kwargs):
                    raise RuntimeError("authorization canceled")

            with patch.dict(
                "sys.modules",
                {"google_auth_oauthlib.flow": type("M", (), {"InstalledAppFlow": _FakeInstalledAppFlow})()},
            ):
                from metroliza.exporting.google_drive_export import _interactive_oauth_authorization

                with self.assertRaises(GoogleDriveAuthError) as exc:
                    _interactive_oauth_authorization(credentials_path, token_path)

            self.assertIn("canceled or timed out", str(exc.exception).lower())
    def test_ensure_access_token_bootstraps_interactive_oauth_when_token_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "client-id",
                            "client_secret": "client-secret",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("metroliza.exporting.google_drive_export._interactive_oauth_authorization") as oauth_mock, patch(
                "metroliza.exporting.google_drive_export._refresh_access_token"
            ) as refresh_mock:
                oauth_mock.return_value = {
                    "access_token": "interactive-token",
                    "refresh_token": "refresh-token",
                    "expires_at": 9999999999,
                }

                from metroliza.exporting.google_drive_export import _ensure_access_token

                token = _ensure_access_token(credentials_path, token_path)

            self.assertEqual("interactive-token", token)
            oauth_mock.assert_called_once_with(credentials_path, token_path)
            refresh_mock.assert_not_called()

    def test_ensure_access_token_reauthorizes_when_token_is_expired_without_refresh_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "client-id",
                            "client_secret": "client-secret",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                ),
                encoding="utf-8",
            )
            token_path.write_text(json.dumps({"access_token": "old", "expires_at": 0}), encoding="utf-8")

            with patch("metroliza.exporting.google_drive_export._interactive_oauth_authorization") as oauth_mock, patch(
                "metroliza.exporting.google_drive_export._refresh_access_token"
            ) as refresh_mock:
                oauth_mock.return_value = {
                    "access_token": "reauthed-token",
                    "refresh_token": "new-refresh-token",
                    "expires_at": 9999999999,
                }

                from metroliza.exporting.google_drive_export import _ensure_access_token

                token = _ensure_access_token(credentials_path, token_path)

            self.assertEqual("reauthed-token", token)
            oauth_mock.assert_called_once_with(credentials_path, token_path)
            refresh_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
