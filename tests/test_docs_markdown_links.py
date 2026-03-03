from __future__ import annotations

import re
from pathlib import Path


MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IGNORED_PREFIXES = ("http://", "https://", "mailto:", "#")


def iter_markdown_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.md"))


def iter_local_link_targets(markdown_text: str) -> list[str]:
    targets: list[str] = []
    for raw_target in MARKDOWN_LINK_PATTERN.findall(markdown_text):
        target = raw_target.strip()
        if target.startswith(IGNORED_PREFIXES):
            continue
        targets.append(target.split("#", 1)[0])
    return targets


def test_docs_markdown_local_links_resolve() -> None:
    docs_root = Path("docs")
    failures: list[str] = []

    for markdown_file in iter_markdown_files(docs_root):
        content = markdown_file.read_text(encoding="utf-8")
        for target in iter_local_link_targets(content):
            if not target:
                continue
            resolved = (markdown_file.parent / target).resolve()
            if not resolved.exists():
                failures.append(f"{markdown_file}: {target}")

    assert not failures, "Broken markdown local links:\n" + "\n".join(failures)
