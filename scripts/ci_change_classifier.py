"""Conservatively select Tier 0 from a complete, local Git diff (no API paging)."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess


# Human-facing prose only. Runtime help, fixtures, source templates and release
# metadata deliberately fall outside these roots, even when their suffix is .md.
PROSE_ROOTS = (
    "docs/project/", "docs/engineering/", "docs/release_checks/",
    "docs/roadmaps/", "docs/quality/", "docs/archive/",
)
PROSE_FILES = {"AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md"}
INPUT_DIRECTORIES = {"assets", "fixtures", "generated", "templates", "prompts", "contracts"}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
RAW_HEADER = re.compile(rb":([0-7]{6}) ([0-7]{6}) [0-9a-f]+ [0-9a-f]+ ([AMD])")


def is_prose(path: str) -> bool:
    """Unknown locations, ambiguous paths and generated/non-Markdown assets run full CI."""
    parts = PurePosixPath(path).parts
    if not parts or path != PurePosixPath(path).as_posix() or ".." in parts:
        return False
    if parts[0] == "/" or "\\" in path or set(parts) & INPUT_DIRECTORIES:
        return False
    if path in PROSE_FILES:
        return True
    if not path.endswith(".md"):
        return False
    return path.startswith(PROSE_ROOTS) or (len(parts) == 2 and parts[0] == "docs")


def docs_only_from_raw(raw: bytes) -> bool:
    """Read --raw -z --no-renames; both sides of renames appear as delete/add.

    Only regular, non-executable files qualify. Deletions retain their old mode;
    symlinks, submodules, type changes and malformed/empty diffs fail closed.
    """
    fields = raw.split(b"\0")
    if fields[-1] != b"" or len(fields) < 3 or len(fields) % 2 != 1:
        return False
    for header, path in zip(fields[:-1:2], fields[1:-1:2]):
        match = RAW_HEADER.fullmatch(header)
        if match is None or set(match.groups()[:2]) - {b"000000", b"100644"}:
            return False
        if not is_prose(os.fsdecode(path)):
            return False
    return True


def event_range(event_name: str, event: dict) -> tuple[str, str, bool] | None:
    """PRs use the merge base; pushes use the entire before..after interval."""
    if event_name == "pull_request":
        pr = event["pull_request"]
        base, head, merge_base = pr["base"]["sha"], pr["head"]["sha"], True
    elif event_name == "push":
        base, head, merge_base = event["before"], event["after"], False
    else:
        return None  # Dispatch always qualifies the full lane, including packaging dependencies.
    if not all(isinstance(sha, str) and SHA_PATTERN.fullmatch(sha) and int(sha, 16)
               for sha in (base, head)):
        return None  # Includes branch creation/deletion; never guess a partial diff.
    return base, head, merge_base


def git_output(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=60,
    ).stdout


def classify_event(event_name: str, event: dict) -> bool:
    """Unavailable history or invalid event data means full CI, never a docs waiver."""
    try:
        interval = event_range(event_name, event)
        if interval is None:
            return False
        base, head, use_merge_base = interval
        if use_merge_base:
            base = git_output("merge-base", base, head).decode("ascii").strip()
        raw = git_output("diff", "--raw", "-z", "--no-renames", "--no-ext-diff",
                         "--no-textconv", base, head, "--")
        return docs_only_from_raw(raw)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return False


def main() -> None:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        docs_only = classify_event(os.environ["GITHUB_EVENT_NAME"], event)
    except (KeyError, ValueError, OSError):
        docs_only = False
    value = str(docs_only).lower()
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"docs_only={value}\n")
    print(f"docs_only={value}; {'focused Tier 0' if docs_only else 'full CI'}")


if __name__ == "__main__":
    main()

# CI validation for #1139 (mixed case); closed without merging.
