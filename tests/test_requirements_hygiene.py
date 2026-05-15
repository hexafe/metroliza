import pathlib
import re
import unittest


class RequirementsHygieneTests(unittest.TestCase):
    def _runtime_requirements(self) -> list[str]:
        lines = pathlib.Path('requirements.txt').read_text(encoding='utf-8').splitlines()
        entries: list[str] = []
        for line in lines:
            normalized = line.split('#', 1)[0].strip()
            if not normalized:
                continue
            entries.append(normalized)
        return entries

    def test_requirements_files_use_utf8_and_lf(self):
        for path in [
            pathlib.Path('requirements.txt'),
            pathlib.Path('requirements-dev.txt'),
            pathlib.Path('requirements-build.txt'),
            pathlib.Path('requirements-ocr.txt'),
        ]:
            content = path.read_text(encoding='utf-8')
            self.assertNotIn('\r\n', content, f'{path} must use LF newlines')

    def test_split_requirements_file_roles(self):
        runtime = pathlib.Path('requirements.txt').read_text(encoding='utf-8')
        dev = pathlib.Path('requirements-dev.txt').read_text(encoding='utf-8')
        build = pathlib.Path('requirements-build.txt').read_text(encoding='utf-8')

        self.assertIn('PyQt6', runtime)
        self.assertNotIn('pyinstaller', runtime.lower())
        self.assertIn('-r requirements.txt', dev)
        self.assertIn('pytest', dev.lower())
        self.assertIn('-r requirements.txt', build)
        self.assertIn('pyinstaller', build.lower())
        self.assertIn('rapidocr', pathlib.Path('requirements-ocr.txt').read_text(encoding='utf-8').lower())
        self.assertIn('onnxruntime', pathlib.Path('requirements-ocr.txt').read_text(encoding='utf-8').lower())
        self.assertIn('openvino', pathlib.Path('requirements-ocr.txt').read_text(encoding='utf-8').lower())
        self.assertIn('opencv-python', pathlib.Path('requirements-ocr.txt').read_text(encoding='utf-8').lower())

    def test_runtime_requirements_do_not_include_google_api_python_client(self):
        runtime_entries = self._runtime_requirements()
        self.assertFalse(
            any(entry.lower().startswith('google-api-python-client') for entry in runtime_entries),
            'google-api-python-client should not be in requirements.txt without runtime imports',
        )

    def test_runtime_requirements_pin_hexafe_groupstats_to_public_git_source(self):
        runtime_entries = self._runtime_requirements()
        matches = [entry for entry in runtime_entries if entry.lower().startswith('hexafe-groupstats[pandas] @ ')]

        self.assertEqual(matches, [
            'hexafe-groupstats[pandas] @ git+https://github.com/hexafe/hexafe-groupstats.git@92327125499f801fcc42f1d1e970c4e55dcd4b3a'
        ])

    def test_runtime_requirements_pin_hexafe_plotstats_to_public_git_source(self):
        runtime_entries = self._runtime_requirements()
        matches = [
            entry
            for entry in runtime_entries
            if entry.lower().startswith('hexafe-plotstats[pandas] @ ')
        ]

        self.assertEqual(matches, [
            'hexafe-plotstats[pandas] @ git+https://github.com/hexafe/hexafe-plotstats.git@168edf1e7ef0838fb9e8f75eca1036d8779e019e'
        ])

    def test_runtime_requirements_pin_oznak_to_public_git_source(self):
        runtime_entries = self._runtime_requirements()
        matches = [entry for entry in runtime_entries if entry.lower().startswith('oznak @ ')]

        self.assertEqual(matches, [
            'oznak @ git+https://github.com/hexafe/oznak.git@36bd0c91f2afe94baae33d43b0c77b7c78faa478'
        ])

    def test_runtime_requirements_do_not_rely_on_local_hexafe_groupstats_path(self):
        runtime_text = pathlib.Path('requirements.txt').read_text(encoding='utf-8')

        self.assertNotIn('git+ssh://git@github.com/hexafe/hexafe-groupstats.git', runtime_text)
        self.assertNotIn('../hexafe-groupstats', runtime_text)
        self.assertNotRegex(runtime_text, re.compile(r'(^|\s)-e\s+.+hexafe-groupstats', re.MULTILINE))

    def test_runtime_requirements_do_not_rely_on_local_hexafe_plotstats_path(self):
        runtime_text = pathlib.Path('requirements.txt').read_text(encoding='utf-8')

        self.assertNotIn('git+ssh://git@github.com/hexafe/hexafe-plotstats.git', runtime_text)
        self.assertNotIn('../hexafe-plotstats', runtime_text)
        self.assertNotRegex(runtime_text, re.compile(r'(^|\s)-e\s+.+hexafe-plotstats', re.MULTILINE))

    def test_runtime_requirements_do_not_rely_on_local_oznak_path(self):
        runtime_text = pathlib.Path('requirements.txt').read_text(encoding='utf-8')

        self.assertNotIn('git+ssh://git@github.com/hexafe/oznak.git', runtime_text)
        self.assertNotIn('../oznak', runtime_text)
        self.assertNotRegex(runtime_text, re.compile(r'(^|\s)-e\s+.+oznak', re.MULTILINE))

    def test_oznak_integration_plan_matches_runtime_pin_status(self):
        runtime_text = pathlib.Path('requirements.txt').read_text(encoding='utf-8').lower()
        roadmap_text = pathlib.Path(
            'docs/roadmaps/OZNAK_METROLIZA_INTEGRATION_AUDIT_PLAN.md'
        ).read_text(encoding='utf-8')

        if 'oznak @ ' not in runtime_text:
            self.skipTest('Oznak is not pinned in runtime requirements')

        self.assertIn('Metroliza now pins Oznak from Git in `requirements.txt`', roadmap_text)
        self.assertNotIn('Metroliza does not pin Oznak yet', roadmap_text)


if __name__ == '__main__':
    unittest.main()
