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
        self.assertTrue(metadata.highlight)

    def test_sync_readme_detects_drift_in_check_mode(self):
        metadata = sync_release_metadata.load_metadata()
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_readme = pathlib.Path(tmp_dir) / "README.md"
            temp_readme.write_text(
                "Current release highlight (`2000.01`, build `000000`): stale\n"
                "### Changelog highlights (release `2000.01`, build `000000`)\n",
                encoding="utf-8",
            )

            with mock.patch.object(sync_release_metadata, "README_PATH", temp_readme):
                result = sync_release_metadata.sync_readme(metadata, apply=False)

            self.assertTrue(result.changed)
            self.assertIn("stale", temp_readme.read_text(encoding="utf-8"))

    def test_sync_changelog_writes_current_header(self):
        metadata = sync_release_metadata.load_metadata()
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_changelog = pathlib.Path(tmp_dir) / "CHANGELOG.md"
            temp_changelog.write_text(
                "# Changelog\n\n## 2000.01 (build 000000) — current version\n",
                encoding="utf-8",
            )

            with mock.patch.object(sync_release_metadata, "CHANGELOG_PATH", temp_changelog):
                result = sync_release_metadata.sync_changelog(metadata, apply=True)

            self.assertTrue(result.changed)
            self.assertIn(
                f"## {metadata.version_label} — current version",
                temp_changelog.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
