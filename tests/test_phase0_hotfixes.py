import importlib
import math
import unittest
from types import SimpleNamespace

from modules.excel_sheet_utils import sanitize_sheet_name, unique_sheet_name
from modules.stats_utils import compute_capability_confidence_intervals, safe_process_capability
from modules.report_fingerprint import build_report_fingerprint, build_parser_fingerprint


class TestSheetNameUtilities(unittest.TestCase):
    def test_sanitize_invalid_chars_and_truncate(self):
        raw = "bad[]:*?/\\name" + "x" * 40
        sanitized = sanitize_sheet_name(raw)
        self.assertNotRegex(sanitized, r"[\[\]:\*\?/\\]")
        self.assertLessEqual(len(sanitized), 31)

    def test_unique_sheet_name_is_deterministic(self):
        used = set()
        first = unique_sheet_name("Report", used)
        second = unique_sheet_name("Report", used)
        third = unique_sheet_name("Report", used)
        self.assertEqual(first, "Report")
        self.assertEqual(second, "Report_1")
        self.assertEqual(third, "Report_2")


class TestStatsUtilities(unittest.TestCase):
    def test_safe_process_capability_sigma_zero(self):
        cp, cpk = safe_process_capability(0, 1, 0, 0, 0.2)
        self.assertEqual(cp, "N/A")
        self.assertEqual(cpk, "N/A")

    def test_safe_process_capability_one_sided_gdt_sets_cp_na_and_upper_cpk(self):
        cp, cpk = safe_process_capability(0, 1, 0, 0.2, 0.4)
        self.assertEqual(cp, "N/A")
        self.assertEqual(cpk, 1.0)

    def test_safe_process_capability_one_sided_gdt_tolerates_near_zero_nominal_and_lsl(self):
        cp, cpk = safe_process_capability(1e-13, 1, -1e-13, 0.2, 0.4)
        self.assertEqual(cp, "N/A")
        self.assertEqual(cpk, 1.0)

    def test_safe_process_capability_nan(self):
        cp, cpk = safe_process_capability(0, 1, 0, math.nan, 0.2)
        self.assertEqual(cp, "N/A")
        self.assertEqual(cpk, "N/A")

    def test_compute_capability_confidence_intervals_bilateral(self):
        payload = compute_capability_confidence_intervals(sample_size=30, cp=1.2, cpk=1.1)

        self.assertIsInstance(payload['cp'], dict)
        self.assertIsInstance(payload['cpk'], dict)
        self.assertLess(payload['cp']['lower'], 1.2)
        self.assertGreater(payload['cp']['upper'], 1.2)
        self.assertLess(payload['cpk']['lower'], 1.1)
        self.assertGreater(payload['cpk']['upper'], 1.1)

    def test_compute_capability_confidence_intervals_one_sided(self):
        payload = compute_capability_confidence_intervals(sample_size=30, cp=None, cpk=1.05)

        self.assertIsNone(payload['cp'])
        self.assertIsInstance(payload['cpk'], dict)


class TestParseDedupeFingerprint(unittest.TestCase):
    def test_fingerprint_distinguishes_same_filename_different_directories(self):
        parser_a = SimpleNamespace(
            pdf_reference="REF1",
            pdf_file_path="/tmp/a",
            pdf_file_name="same.pdf",
            pdf_date="2024-01-01",
            pdf_sample_number="001",
        )
        parser_b = SimpleNamespace(
            pdf_reference="REF1",
            pdf_file_path="/tmp/b",
            pdf_file_name="same.pdf",
            pdf_date="2024-01-01",
            pdf_sample_number="001",
        )

        fingerprint_a = build_parser_fingerprint(parser_a)
        fingerprint_b = build_parser_fingerprint(parser_b)

        self.assertNotEqual(fingerprint_a, fingerprint_b)

    def test_db_identity_preferred_when_available(self):
        fingerprint = build_report_fingerprint({"ID": 42, "FILENAME": "x.pdf"})
        self.assertEqual(fingerprint, "id:42")


@unittest.skipIf(importlib.util.find_spec("cryptography") is None, "cryptography dependency not installed")
class TestLicenseHardening(unittest.TestCase):
    def test_invalid_license_payload_returns_invalid_state(self):
        from modules.license_key_manager import LicenseKeyManager

        invalid = "not-base64"
        self.assertFalse(LicenseKeyManager.validate_license_key(invalid, "00:11:22:33:44:55", public_key=None))
        self.assertIsNone(LicenseKeyManager.get_expiration_date_from_license_key(invalid))


if __name__ == "__main__":
    unittest.main()
