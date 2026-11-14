import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import sync_release_metadata


class ReleaseMetadataSyncTests(unittest.TestCase):
    def test_load_metadata_has_required_fields(self):
        metadata = sync_release_metadata.load_metadata()

        self.assertEqual(metadata.release_version, "0.8.0-dev.3")
        self.assertEqual(metadata.build, "")
        self.assertEqual(metadata.version_label, metadata.release_version)
        self.assertEqual(metadata.public_version_label, metadata.release_version)
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
                '- Create a local-only report from a bounded history of selected, predefined actions and boolean options across application modules; confidential input data and free text are excluded<br>',
                '- Coverage is selective; a report may not reconstruct the incident and does not establish user acceptance<br>',
            ],
        )
        changelog = sync_release_metadata.CHANGELOG_PATH.read_text(encoding="utf-8")
        self.assertIn("## 0.8.0-dev.1 — previous source version", changelog)
        self.assertIn("## 0.8.0-dev.2 — previous source version", changelog)
        dev2_section = changelog.split("## 0.8.0-dev.2 — previous source version", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Generate a local bug report with a bounded activity history and selected options; input data, paths, names and configuration values are excluded.", dev2_section)
        self.assertIn("Match closed report codes to a predefined scenario and check its workflow with synthetic data; this validates a reference workflow, not the user's incident.", dev2_section)
        previous_section = changelog.split("## 0.8.0-dev.1 — previous source version", 1)[1].split("\n## ", 1)[0]
        for original_point in (
            "Adopt development package versions `dev.N`, frozen candidates `rc.N`",
            "Keep earlier `2026.09rc1(261119)` packages, identifiers and receipts as history",
            "Reserve `1.0.0` for both a complete external-LLM parser authoring package",
            "This versioning change does not by itself claim new functionality",
        ):
            self.assertIn(original_point, previous_section)
        self.assertIn("Version 2026.09rc1 (build 261115)", VersionDate.release_notes)
        self.assertNotIn("261115", current_section)
        self.assertIn("Version 2026.09rc1 (build 261114)", VersionDate.release_notes)
        self.assertNotIn("261114", current_section)
        self.assertIn("Version 2026.09rc1 (build 261113)", VersionDate.release_notes)
        self.assertNotIn("261113", current_section)
        self.assertIn("Version 2026.09rc1 (build 261112)", VersionDate.release_notes)
        self.assertNotIn("261112", current_section)
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
            self.assertIn("0.8.0-dev.3", updated)
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
