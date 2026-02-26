import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from modules.google_drive_export import (
    GOOGLE_DRIVE_UPLOAD_URL,
    GoogleDriveAuthError,
    GoogleDriveQuotaError,
    GoogleDriveResponseError,
    GoogleDriveTransientError,
    _build_upload_request_body,
    map_google_http_error,
    map_google_network_error,
    parse_drive_conversion_response,
    upload_and_convert_workbook,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGoogleDriveExport(unittest.TestCase):
    def test_parse_drive_conversion_response_success(self):
        payload = {"id": "abc123", "webViewLink": "https://docs.google.com/spreadsheets/d/abc123/edit"}

        result = parse_drive_conversion_response(payload)

        self.assertEqual("abc123", result.file_id)
        self.assertEqual("https://docs.google.com/spreadsheets/d/abc123/edit", result.web_url)

    def test_parse_drive_conversion_response_missing_fields(self):
        with self.assertRaises(GoogleDriveResponseError):
            parse_drive_conversion_response({"name": "missing fields"})

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

    def test_network_error_maps_to_transient(self):
        url_error = urllib.error.URLError("temporary network failure")

        transient = map_google_network_error("Google Drive upload failed", url_error)

        self.assertIsInstance(transient, GoogleDriveTransientError)
        self.assertIn("Google Drive upload failed", str(transient))

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

            captured = {"upload_data": None}

            def fake_urlopen(request, timeout=0):
                url = request.full_url
                if url.startswith(GOOGLE_DRIVE_UPLOAD_URL):
                    captured["upload_data"] = request.data
                    return _FakeResponse(
                        {
                            "id": "sheet123",
                            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123/edit",
                        }
                    )

                self.assertIn("sheets.googleapis.com/v4/spreadsheets/sheet123", url)
                return _FakeResponse(
                    {
                        "sheets": [
                            {"properties": {"title": "MEASUREMENTS"}},
                            {"properties": {"title": "REF_A"}},
                        ]
                    }
                )

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ):
                result = upload_and_convert_workbook(
                    str(excel_path),
                    expected_sheet_names=["MEASUREMENTS", "REF_A"],
                    max_retries=1,
                )

            self.assertEqual("sheet123", result.file_id)
            self.assertEqual(str(excel_path), result.local_xlsx_path)
            self.assertEqual((), result.warnings)
            self.assertIn("local .xlsx fallback", result.fallback_message)
            self.assertIn(b"application/vnd.google-apps.spreadsheet", captured["upload_data"])

    def test_upload_and_convert_workbook_retries_retryable_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            attempts = {"count": 0}

            def fake_urlopen(request, timeout=0):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise urllib.error.URLError("temporary down")
                return _FakeResponse(
                    {
                        "id": "sheet456",
                        "webViewLink": "https://docs.google.com/spreadsheets/d/sheet456/edit",
                    }
                )

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("modules.google_drive_export.time.sleep") as sleep_mock:
                result = upload_and_convert_workbook(str(excel_path), max_retries=2, retry_delay_seconds=0)

            self.assertEqual("sheet456", result.file_id)
            self.assertEqual(attempts["count"], 2)
            sleep_mock.assert_called_once()

    def test_upload_and_convert_workbook_warns_and_falls_back_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            def fake_urlopen(request, timeout=0):
                url = request.full_url
                if url.startswith(GOOGLE_DRIVE_UPLOAD_URL):
                    return _FakeResponse(
                        {
                            "id": "sheet789",
                            "webViewLink": "https://docs.google.com/spreadsheets/d/sheet789/edit",
                        }
                    )
                return _FakeResponse({"sheets": [{"properties": {"title": "MEASUREMENTS"}}]})

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ):
                result = upload_and_convert_workbook(
                    str(excel_path),
                    expected_sheet_names=["MEASUREMENTS", "REF_A"],
                    max_retries=1,
                )

            self.assertIn("partial", result.warnings[0].lower())
            self.assertIn("fallback", result.fallback_message.lower())
            self.assertIn("warnings", result.fallback_message.lower())


if __name__ == '__main__':
    unittest.main()
