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
        self.assertEqual(metadata.public_version_label, "2026.09 RC1 (build 261031)")
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
                '- Help opens the manuals that match this version<br>',
                '- The Windows download is one ZIP: extract it and start the EXE; build identity and third-party notices sit next to the EXE<br>',
                '- Exporting to an existing workbook asks whether to save a copy (the default) or replace it; a workbook open in Excel is not overwritten<br>',
                '- Metadata enrichment reports canceled, failed and skipped reports instead of a green 100%<br>',
                '- Opening an existing .sqlite, .sqlite3 or .DB database uses exactly the file you chose<br>',
                '- Copy to checked shows hidden and overwritten values and can be undone<br>',
                '- Filter searches keep selected headers, All and specific values cannot be mixed, and a From date after To is blocked<br>',
                '- Modify Database accepts an unambiguous decimal comma, blocks invalid numbers and saves all changes or none<br>',
                '- Mapping CSV import previews added and replaced names and imports only new ones by default<br>',
                '- CSV Summary applies a search with Enter before assigning rows, keeps groups when nothing changed, and keeps manual limits of metrics you switch off and on again<br>',
                '- Much faster start on Windows: the app unpacks once per version, and later starts open the main window in about a second<br>',
                '- A smaller download: unused OCR acceleration and video components are no longer bundled<br>',
                '- Fast report import is about 2.5 times faster<br>',
                '- After review, report metadata (reference, part name, sample number, date) is read automatically into the import table, where you can correct it or run OCR for selected reports; your corrections are kept<br>',
                '- The dark theme is applied correctly when the app starts<br>',
                '- The splash screen closes as soon as the main window is visible<br>',
                '- A missing or damaged program file is repaired automatically, or the message names the affected file<br>',
                '- Modify Database opens instantly and searches quickly, even with hundreds of thousands of measurements<br>',
                '- Excel exports are about twice as fast and use much less memory; Extended plots export uses several processor cores and CSV Summary export is faster too<br>',
                '- Importing reports on Windows saves them to the database much faster<br>',
                '- Multi-page reports in very large imports (more than 2048 reports at once) are read the same way as other imports, without extra measurement groups at page breaks<br>',
                '- The filter window opens instantly, loads its choices in the background and reuses them while the database is unchanged<br>',
                '- Canceling an export right after it starts stops at once, without loading all measurements first<br>',
                '- Creating an analysis in CSV Summary works after applying groups to Industrial Data, and a renamed default group is kept in the dashboard and workbook<br>',
                '- Industrial Data temporary storage shows how many rows were fetched, and opening CSV Summary for different sources no longer makes the temporary file grow each time<br>',
                '- A refreshed Windows workspace keeps report review, import, analysis, and export in one place<br>',
                '- Choose PDF reports before import and reopen saved measurements without repeating completed work<br>',
                '- Filters and grouping keep numeric results consistent between the table and analysis views<br>',
                '- Excel exports preserve chart titles and series names as literal text<br>',
                '- Reports follow the selected app theme, including after a theme change<br>',
                '- Reports without a reference remain exportable, while group comparisons identify missing references<br>',
                '- The Help menu opens private incident reports for preview and export when a supervised run fails<br>',
                '- Canceling active work protects completed database and workbook output<br>',
            ],
        )
        self.assertIn("Version 2026.06rc2 (build 260711)", VersionDate.release_notes)

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
            self.assertIn("RC1", updated)
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
