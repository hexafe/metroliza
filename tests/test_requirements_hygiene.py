import pathlib
import unittest


class RequirementsHygieneTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
