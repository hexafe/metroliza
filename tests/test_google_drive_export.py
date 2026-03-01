import json
import sys
import tempfile
import types
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
    GOOGLE_SHEETS_SCOPE,
    GoogleDriveAuthError,
    GoogleDriveQuotaError,
    GoogleDriveResponseError,
    GoogleDriveTransientError,
    _build_limit_series_patch_requests,
    _build_upload_request_body,
    _load_token_payload,
    fix_usl_lsl_trendlines,
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


class _FakeExecute:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeSpreadsheetsService:
    def __init__(self, charts_payload):
        self._charts_payload = charts_payload
        self.batch_update_calls = []

    def get(self, **kwargs):
        return _FakeExecute(self._charts_payload)

    def batchUpdate(self, **kwargs):
        self.batch_update_calls.append(kwargs)
        return _FakeExecute({})


class _FakeSheetsService:
    def __init__(self, charts_payload):
        self._spreadsheets = _FakeSpreadsheetsService(charts_payload)

    def spreadsheets(self):
        return self._spreadsheets




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

            captured = {"upload_data": None, "folder_lookup": 0, "sheet_discovery": 0, "batch_update": 0}

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
                if request.method == "GET" and "sheets.googleapis.com/v4/spreadsheets/" in request.full_url:
                    captured["sheet_discovery"] += 1
                    return _FakeResponse({"sheets": []})
                if request.method == "POST" and request.full_url.endswith(":batchUpdate"):
                    captured["batch_update"] += 1
                    return _FakeResponse({"replies": []})
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
            self.assertEqual((), result.warnings)
            self.assertEqual((), result.converted_tab_titles)
            self.assertEqual("", result.fallback_message)
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


    def test_oauth_scopes_include_drive_and_sheets(self):
        self.assertEqual((GOOGLE_DRIVE_SCOPE, GOOGLE_SHEETS_SCOPE), GOOGLE_OAUTH_SCOPES)

    def test_build_limit_series_patch_requests_targets_usl_and_lsl(self):
        discovery_payload = {
            "sheets": [
                {
                    "properties": {"title": "Main Measurements"},
                    "charts": [
                        {
                            "chartId": 7,
                            "spec": {
                                "basicChart": {
                                    "chartType": "SCATTER",
                                    "series": [
                                        {"series": {"seriesName": {"value": "Measured"}}},
                                        {"series": {"seriesName": {"value": "USL"}}},
                                        {"series": {"seriesName": {"value": "LSL"}}},
                                    ],
                                }
                            },
                        }
                    ],
                }
            ]
        }

        requests = _build_limit_series_patch_requests(discovery_payload)

        self.assertEqual(2, len(requests))
        first = requests[0]["updateChartSpec"]
        self.assertEqual(7, first["chartId"])
        self.assertIn("basicChart.series[1].lineStyle", first["fields"])
        self.assertIn("basicChart.series[1].colorStyle", first["fields"])
        self.assertEqual(2, first["spec"]["basicChart"]["series"][0]["lineStyle"]["width"]["magnitude"])
        self.assertEqual("LINEAR", requests[0]["updateChartSpec"]["spec"]["basicChart"]["series"][0]["trendline"]["type"])

    def test_build_limit_series_patch_requests_includes_ref_sheets(self):
        discovery_payload = {
            "sheets": [
                {
                    "properties": {"title": "REF_123"},
                    "charts": [
                        {
                            "chartId": 9,
                            "spec": {
                                "basicChart": {
                                    "chartType": "LINE",
                                    "series": [
                                        {"series": {"seriesName": {"value": "USL"}}},
                                    ],
                                }
                            },
                        }
                    ],
                }
            ]
        }

        requests = _build_limit_series_patch_requests(discovery_payload)

        self.assertEqual(1, len(requests))
        self.assertEqual(9, requests[0]["updateChartSpec"]["chartId"])

    def test_upload_and_convert_workbook_always_applies_chart_series_patching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            excel_path = Path(tmpdir) / "report.xlsx"
            excel_path.write_bytes(b"excel-content")

            with patch("modules.google_drive_export._ensure_access_token", return_value="token"), patch(
                "modules.google_drive_export._ensure_reports_folder", return_value="folder"
            ), patch("modules.google_drive_export.urllib.request.urlopen", return_value=_FakeResponse({
                "id": "sheet123", "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123/edit"
            })), patch("modules.google_drive_export._patch_converted_sheet_chart_series") as patcher:
                upload_and_convert_workbook(str(excel_path))

            patcher.assert_called_once_with(spreadsheet_id="sheet123", access_token="token")


    def test_fix_usl_lsl_trendlines_updates_target_series_with_full_spec_and_field_masks(self):
        original_spec = {
            "title": "chart title",
            "basicChart": {
                "chartType": "LINE",
                "series": [
                    {"series": {"sourceRange": {"sources": [{"sheetId": 1}]}}},
                    {"series": {"sourceRange": {"sources": [{"sheetId": 2}]}}},
                    {"series": {"sourceRange": {"sources": [{"sheetId": 3}]}}},
                ],
            },
        }
        discovery_payload = {
            "sheets": [
                {
                    "charts": [
                        {"chartId": 17, "spec": original_spec},
                        {"chartId": 18, "spec": {"pieChart": {"legendPosition": "RIGHT_LEGEND"}}},
                    ]
                }
            ]
        }

        fake_service = _FakeSheetsService(discovery_payload)
        fake_discovery = types.SimpleNamespace(build=lambda *_args, **_kwargs: fake_service)

        with patch.dict(sys.modules, {"googleapiclient": types.SimpleNamespace(discovery=fake_discovery), "googleapiclient.discovery": fake_discovery}):
            fix_usl_lsl_trendlines(creds=object(), spreadsheet_id="sheet-id", usl_series_index=1, lsl_series_index=2)

        self.assertEqual(1, len(fake_service._spreadsheets.batch_update_calls))
        batch_body = fake_service._spreadsheets.batch_update_calls[0]["body"]
        self.assertEqual(1, len(batch_body["requests"]))

        update_request = batch_body["requests"][0]["updateChartSpec"]
        self.assertEqual(17, update_request["chartId"])
        self.assertEqual("chart title", update_request["spec"]["title"])
        self.assertEqual(3, len(update_request["spec"]["basicChart"]["series"]))
        self.assertEqual(2, update_request["spec"]["basicChart"]["series"][1]["lineStyle"]["width"]["magnitude"])
        self.assertEqual("LINEAR", update_request["spec"]["basicChart"]["series"][2]["trendline"]["type"])

        fields = set(update_request["fields"].split(","))
        self.assertEqual(12, len(fields))
        self.assertIn("basicChart.series[1].trendline.type", fields)
        self.assertIn("basicChart.series[1].trendline.lineStyle.width", fields)
        self.assertIn("basicChart.series[1].trendline.lineStyle.colorStyle", fields)
        self.assertIn("basicChart.series[1].lineStyle.type", fields)
        self.assertIn("basicChart.series[1].lineStyle.width", fields)
        self.assertIn("basicChart.series[1].colorStyle", fields)
        self.assertIn("basicChart.series[2].trendline.type", fields)
        self.assertIn("basicChart.series[2].trendline.lineStyle.width", fields)
        self.assertIn("basicChart.series[2].trendline.lineStyle.colorStyle", fields)
        self.assertIn("basicChart.series[2].lineStyle.type", fields)
        self.assertIn("basicChart.series[2].lineStyle.width", fields)
        self.assertIn("basicChart.series[2].colorStyle", fields)

    def test_fix_usl_lsl_trendlines_skips_when_target_series_indexes_missing(self):
        discovery_payload = {
            "sheets": [
                {
                    "charts": [
                        {
                            "chartId": 51,
                            "spec": {
                                "basicChart": {
                                    "series": [
                                        {"series": {"seriesName": {"value": "Measured"}}},
                                    ]
                                }
                            },
                        }
                    ]
                }
            ]
        }

        fake_service = _FakeSheetsService(discovery_payload)
        fake_discovery = types.SimpleNamespace(build=lambda *_args, **_kwargs: fake_service)

        with patch.dict(sys.modules, {"googleapiclient": types.SimpleNamespace(discovery=fake_discovery), "googleapiclient.discovery": fake_discovery}):
            fix_usl_lsl_trendlines(creds=object(), spreadsheet_id="sheet-id", usl_series_index=1, lsl_series_index=2)

        self.assertEqual([], fake_service._spreadsheets.batch_update_calls)



class TestGoogleDriveOAuthBootstrap(unittest.TestCase):

    def test_load_token_payload_missing_file_raises_auth_error_with_stable_guidance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "token.json"

            with self.assertRaises(GoogleDriveAuthError) as exc:
                _load_token_payload(token_path)

        self.assertIn("Missing token.json", str(exc.exception))

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
