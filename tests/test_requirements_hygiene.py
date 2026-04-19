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
            'hexafe-groupstats[pandas] @ git+https://github.com/hexafe/hexafe-groupstats.git@10788c87b31da7856b269f9ebe0740efa4b1fff1'
        ])

    def test_runtime_requirements_do_not_rely_on_local_hexafe_groupstats_path(self):
        runtime_text = pathlib.Path('requirements.txt').read_text(encoding='utf-8')

        self.assertNotIn('git+ssh://git@github.com/hexafe/hexafe-groupstats.git', runtime_text)
        self.assertNotIn('../hexafe-groupstats', runtime_text)
        self.assertNotRegex(runtime_text, re.compile(r'(^|\s)-e\s+.+hexafe-groupstats', re.MULTILINE))


if __name__ == '__main__':
    unittest.main()
