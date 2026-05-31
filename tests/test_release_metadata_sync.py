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
        self.assertEqual(metadata.public_version_label, "2026.05 RC4 (build 260524)")
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
                "- Parser profiles can now be prepared from Tools > Parser profiles... for new supplier report templates without writing Python code<br>",
                "- Google Sheets export now checks converted workbook tabs and warns when a local Excel fallback should be used<br>",
                "- Canceling long parsing, export, and metadata tasks is more reliable from progress windows<br>",
                "- Dashboard plot visuals can now be customized<br>",
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
            self.assertIn("RC4", updated)
            self.assertNotIn("rc1", updated)

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
