import json
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from modules.google_drive_export import (
    GOOGLE_DRIVE_REPORTS_FOLDER_NAME,
    GOOGLE_DRIVE_SCOPE,
    GOOGLE_DRIVE_UPLOAD_URL,
    GOOGLE_OAUTH_SCOPES,
    GoogleDriveAuthError,
    GoogleDriveQuotaError,
    GoogleDriveResponseError,
    GoogleDriveTransientError,
    _build_upload_request_body,
    _load_token_payload,
    _refresh_access_token,
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

            captured = {"upload_data": None, "folder_lookup": 0}

            def fake_urlopen(request, timeout=0):
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
            self.assertEqual((), result.converted_tab_titles)
            self.assertIn(str(excel_path), result.fallback_message)
            self.assertIn(b"application/vnd.google-apps.spreadsheet", captured["upload_data"])
            self.assertIn(b"\"parents\": [\"folder-123\"]", captured["upload_data"])
            self.assertEqual(1, captured["folder_lookup"])

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

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("modules.google_drive_export.time.sleep") as sleep_mock:
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

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
            ), patch("modules.google_drive_export.time.sleep") as sleep_mock:
                result = upload_and_convert_workbook(str(excel_path), max_retries=3, retry_delay_seconds=0.25)

            self.assertEqual("sheet456", result.file_id)
            self.assertEqual(attempts["count"], 3)
            self.assertEqual(sleep_mock.call_count, 2)
            sleep_mock.assert_any_call(0.25)


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

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export.urllib.request.urlopen", side_effect=fake_urlopen
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


    def test_oauth_scopes_include_drive_only(self):
        self.assertEqual((GOOGLE_DRIVE_SCOPE,), GOOGLE_OAUTH_SCOPES)

    def test_load_token_payload_missing_file_raises_auth_error_with_stable_guidance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "token.json"

            with self.assertRaises(GoogleDriveAuthError) as exc:
                _load_token_payload(token_path)

        self.assertIn("Missing token.json", str(exc.exception))


    def test_refresh_access_token_sets_drive_scope_when_missing(self):
        token_payload = {"refresh_token": "refresh-token"}
        credentials = {
            "client_id": "id",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }

        with patch("modules.google_drive_export.urllib.request.urlopen", return_value=_FakeResponse({"access_token": "new-token", "expires_in": 3600})):
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
                from modules.google_drive_export import _interactive_oauth_authorization

                payload = _interactive_oauth_authorization(credentials_path, token_path)

            self.assertEqual([GOOGLE_DRIVE_SCOPE], payload["scopes"])
            self.assertEqual(GOOGLE_DRIVE_SCOPE, payload["scope"])

    def test_refresh_access_token_without_refresh_token_requires_reauthentication(self):
        with self.assertRaises(GoogleDriveAuthError) as exc:
            _refresh_access_token(
                {"access_token": "expired", "expires_at": 0},
                {"client_id": "id", "client_secret": "secret", "token_uri": "https://oauth2.googleapis.com/token"},
            )

        self.assertIn("Re-authenticate", str(exc.exception))

    def test_ensure_access_token_rejects_malformed_credentials_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            credentials_path = Path(tmpdir) / "credentials.json"
            token_path = Path(tmpdir) / "token.json"
            credentials_path.write_text(json.dumps({"installed": ["bad"]}), encoding="utf-8")

            from modules.google_drive_export import _ensure_access_token

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

            from modules.google_drive_export import _ensure_access_token

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
                from modules.google_drive_export import _interactive_oauth_authorization

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

            with patch("modules.google_drive_export._interactive_oauth_authorization") as oauth_mock, patch(
                "modules.google_drive_export._refresh_access_token"
            ) as refresh_mock:
                oauth_mock.return_value = {
                    "access_token": "interactive-token",
                    "refresh_token": "refresh-token",
                    "expires_at": 9999999999,
                }

                from modules.google_drive_export import _ensure_access_token

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

            with patch("modules.google_drive_export._interactive_oauth_authorization") as oauth_mock, patch(
                "modules.google_drive_export._refresh_access_token"
            ) as refresh_mock:
                oauth_mock.return_value = {
                    "access_token": "reauthed-token",
                    "refresh_token": "new-refresh-token",
                    "expires_at": 9999999999,
                }

                from modules.google_drive_export import _ensure_access_token

                token = _ensure_access_token(credentials_path, token_path)

            self.assertEqual("reauthed-token", token)
            oauth_mock.assert_called_once_with(credentials_path, token_path)
            refresh_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
