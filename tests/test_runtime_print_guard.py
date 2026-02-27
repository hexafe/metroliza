import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES_DIR = REPO_ROOT / 'modules'
PRINT_CALL_PATTERN = re.compile(r'\bprint\s*\(')
EXCLUDED_FILES = {
    # Add intentionally interactive scripts here if they are ever added under modules/.
}


class TestRuntimePrintGuard(unittest.TestCase):
    def test_modules_runtime_paths_do_not_use_print_calls(self):
        offenders: list[str] = []

        for path in sorted(MODULES_DIR.glob('*.py')):
            relative_path = path.relative_to(REPO_ROOT).as_posix()
            if relative_path in EXCLUDED_FILES:
                continue

            content = path.read_text(encoding='utf-8')
            if PRINT_CALL_PATTERN.search(content):
                offenders.append(relative_path)

        self.assertEqual(
            offenders,
            [],
            msg='Runtime modules should not call print(); use structured logging instead.',
        )


if __name__ == '__main__':
    unittest.main()
