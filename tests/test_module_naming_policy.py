import re
from pathlib import Path


SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.py$")


def test_source_directory_filenames_follow_policy():
    source_dir = Path("src/metroliza")
    discovered = {path.name for path in source_dir.rglob("*.py") if path.name != "__init__.py"}

    unexpected_camelcase = sorted(name for name in discovered if not SNAKE_CASE_PATTERN.match(name))

    assert not unexpected_camelcase, f"Found non-snake-case module filenames: {unexpected_camelcase}"
