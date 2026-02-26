import json
import unittest
import urllib.error

from modules.google_drive_export import (
    GoogleDriveAuthError,
    GoogleDriveQuotaError,
    GoogleDriveResponseError,
    GoogleDriveTransientError,
    map_google_http_error,
    map_google_network_error,
    parse_drive_conversion_response,
)


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


if __name__ == '__main__':
    unittest.main()
