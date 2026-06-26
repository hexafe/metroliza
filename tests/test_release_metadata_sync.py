import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import sync_release_metadata


class ReleaseMetadataSyncTests(unittest.TestCase):
    def test_load_metadata_has_required_fields(self):
        metadata = sync_release_metadata.load_metadata()

        self.assertRegex(metadata.release_version, r"^\d{4}\.\d{2}(?:rc\d+)?$")
        self.assertRegex(metadata.build, r"^\d{6}$")
        self.assertEqual(metadata.version_label, f"{metadata.release_version}({metadata.build})")
        self.assertEqual(metadata.public_version_label, "2026.06 RC2 (build 260626)")
        self.assertTrue(metadata.highlight)

    def test_in_app_current_release_notes_show_current_version_only(self):
        import VersionDate
        from metroliza.app import version

        self.assertIs(VersionDate.release_notes, version.release_notes)
        current_section = VersionDate.release_notes.split("<br><b>Archive:</b><br>", 1)[0]

        self.assertIn(f"Current version {VersionDate.PUBLIC_VERSION_LABEL}", current_section)
        for technical_term in (
            "loading animation",
            "PyInstaller",
            "Nuitka",
            "RapidOCR",
            "ONNX",
            "OpenCV",
            "NumPy",
            "Bandit",
            "pip-audit",
            "benchmark",
            "test coverage",
            "regression",
            "adapter",
            "schema",
        ):
            self.assertNotIn(technical_term, current_section)

        current_bullets = [
            line.strip()
            for line in current_section.splitlines()
            if line.strip().startswith("- ")
        ]
        self.assertEqual(
            current_bullets,
            [
                "- CSV Summary and Excel inputs now use one consistent local row store, keeping large files responsive while avoiding extra data copies<br>",
                "- CSV Summary filters, grouping, and dashboard preparation can stream selected rows in smaller batches, reducing memory pressure on large tables<br>",
                "- Grouped metric summaries now calculate directly from stored rows, so large CSV Summary analysis spends less time preparing intermediate tables<br>",
                "- Export and industrial analytics paths now share lighter table helpers, improving stability when optional spreadsheet packages are unavailable<br>",
                "- Parser and report data paths now use clearer reusable row-query contracts for filtering, counting, and streaming report-backed results<br>",
                "- Magic filter expressions now accept field names and AND, OR, IN, and NOT IN wording in any letter case, including shorthand ranges<br>",
                "- Industrial Data now opens cached rows in CSV Summary from indexed local metadata, so filter lists and simple grouping previews respond faster on large production caches<br>",
                "- Industrial Data workbook export can now include raw cached data directly without first loading the full cache into the interactive table<br>",
                "- Industrial export filters now apply consistently to cached and live exports, including additional production-field filters entered in the filter dialog<br>",
                "- Industrial cache updates now refresh same-session filter lists more reliably, even when rows and production field values change within the same second<br>",
                "- Industrial Data now clears abandoned temporary tabular views before preparing a new cache handoff, keeping long sessions lighter<br>",
                "- Large SQL fetches now report saved rows clearly when rows were already streamed before a later read or save warning occurs<br>",
                "- Realtime monitoring now reloads only newly inserted sample rows for anomaly review, keeping polling cycles quicker as monitoring history grows<br>",
                "- Realtime diagnostics now keep source status messages more specific when a polling or dashboard refresh step fails<br>",
                "- Realtime Industrial Monitoring now has a separate foundation for append-only samples, signal definitions, stream offsets, explainable anomaly events, replay, and dashboard review<br>",
                "- Deterministic anomaly detectors now cover specification limits, warning limits, IQR fences, MAD robust z-score, rolling z-score, and stale-source checks with operator-readable explanations<br>",
                "- Realtime polling now uses generated bounded queries, cursor offsets, chunk limits, safe diagnostics, and offset advancement only after local persistence succeeds<br>",
                "- Industrial Data fetches can now save rows into the local cache while large guided or SQL reads are still running, with clearer progress for saving rows, refreshing links, and updating summaries<br>",
                "- Industrial Data can now run the same guided filters or SQL query across checked production sources, then report one batch result for all successful and failed sources<br>",
                "- Industrial source setup now accepts copied CSV headers or an approved all-columns marker when a reviewed table or view is allowed to expose simple columns<br>",
                "- SQL query work now has a larger editor with a preview table for reviewed production queries before fetching rows<br>",
                "- Realtime Industrial Monitoring now opens an operator dialog with checked-source selection, polling interval and timeout settings, row limits, status, diagnostics, and dashboard output controls<br>",
                "- Realtime source selection now keeps disabled production sources out of polling and separates saving one source from intentionally applying settings to all checked sources<br>",
                "- Realtime Industrial Monitoring can now import the shared production source YAML file, reload source changes, and open the shared source editor from the monitor<br>",
                "- Realtime dashboard snapshots now refresh in the background after polling, and Open Dashboard queues safely when a refresh is already running<br>",
                "- Interactive HTML dashboards can now find points by TraceCode, record key, series, axis value, or point details, then save browser-local point marks without changing source data<br>",
                "- Realtime dashboard review can open without selecting a Metroliza report database first; the app uses a temporary session SQLite store unless a persistent database is selected<br>",
                "- Synthetic realtime fixtures and replay validation are available for pre-live testing without a production database<br>",
                "- Optional advanced anomaly tooling stays separate from normal app startup, so standard users do not need extra ML packages<br>",
                "- Industrial diagnostics now redact nested credentials, URI passwords, token-like fields, and raw SQL text from operator-facing status and persisted diagnostics<br>",
                "- CMM parser probing now uses marker-based confidence so generic PDFs no longer look like perfect CMM report matches<br>",
                "- CMM report import now rechecks encoded PDF page text before rejecting valid reports whose markers are hidden in compressed PDF bytes<br>",
                "- Parser plugin handoff packages now have stronger tests that require local API contract content and small step-by-step prompts for LLM-assisted plugin work<br>",
                "- Realtime rollout docs now include operator concepts, production safety checks, synthetic replay evidence, source lag review, and rollback steps<br>",
                "- The About dialog now stays focused on the duck animation, version, author, and GitHub project link<br>",
            ],
        )
        changelog_bullets = [
            line.strip()
            for line in sync_release_metadata.CHANGELOG_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("- ")
        ]
        self.assertLess(len(current_bullets), len(changelog_bullets))

    def test_sync_readme_updates_public_labels(self):
        metadata = sync_release_metadata.load_metadata()
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_readme = pathlib.Path(tmp_dir) / "README.md"
            temp_readme.write_text(
                "Current release highlight (`2000.01rc1(000000)`): stale\n"
                "### Changelog highlights (release `2000.01rc1(000000)`)\n",
                encoding="utf-8",
            )

            with mock.patch.object(sync_release_metadata, "README_PATH", temp_readme):
                result = sync_release_metadata.sync_readme(metadata, apply=True)

            self.assertTrue(result.changed)
            updated = temp_readme.read_text(encoding="utf-8")
            self.assertIn(f"Current release highlight (`{metadata.public_version_label}`):", updated)
            self.assertIn(f"### Changelog highlights (release `{metadata.public_version_label}`)", updated)
            self.assertIn("RC2", updated)
            self.assertNotIn("2000.01rc1", updated)

    def test_sync_changelog_writes_current_header(self):
        metadata = sync_release_metadata.load_metadata()
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_changelog = pathlib.Path(tmp_dir) / "CHANGELOG.md"
            temp_changelog.write_text(
                "# Changelog\n\n## 2000.01rc1(000000) — current version\n",
                encoding="utf-8",
            )

            with mock.patch.object(sync_release_metadata, "CHANGELOG_PATH", temp_changelog):
                result = sync_release_metadata.sync_changelog(metadata, apply=True)

            self.assertTrue(result.changed)
            self.assertIn(
                f"## {metadata.public_version_label} — current version",
                temp_changelog.read_text(encoding="utf-8"),
            )

    def test_sync_changelog_leaves_only_one_visible_current_label(self):
        metadata = sync_release_metadata.load_metadata()
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_changelog = pathlib.Path(tmp_dir) / "CHANGELOG.md"
            temp_changelog.write_text(
                "# Changelog\n\n"
                "## 2000.01rc2(000000) — current version\n"
                "- Old rc entry\n"
                "## 1999.12(991231)\n"
                "- Prior release\n",
                encoding="utf-8",
            )

            with mock.patch.object(sync_release_metadata, "CHANGELOG_PATH", temp_changelog):
                result = sync_release_metadata.sync_changelog(metadata, apply=True)

            self.assertTrue(result.changed)
            updated = temp_changelog.read_text(encoding="utf-8")
            self.assertEqual(updated.count("current version"), 1)
            self.assertIn(metadata.public_version_label, updated)


if __name__ == "__main__":
    unittest.main()
