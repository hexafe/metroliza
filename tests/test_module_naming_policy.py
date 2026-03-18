import re
from pathlib import Path


SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.py$")


def test_modules_directory_filenames_follow_policy():
    module_dir = Path("modules")
    discovered = {path.name for path in module_dir.glob("*.py")}

    unexpected_camelcase = sorted(name for name in discovered if not SNAKE_CASE_PATTERN.match(name))

    assert not unexpected_camelcase, f"Found non-snake-case module filenames: {unexpected_camelcase}"
