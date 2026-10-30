from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts import check_release_docs_ref as checker


REPO_ROOT = Path(__file__).resolve().parents[1]

HELP_MENU = '''
MANUAL_RELATIVE_PATHS = {
    "main_window": "docs/user_manual/main_window.md",
    "parsing": "docs/user_manual/parsing.md",
}
'''
WRITER = '''
from metroliza.shared.docs_links import github_blob_url
PDF_URL = github_blob_url("docs/user_manual/group/manual.pdf")
'''


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(root: Path, relative: str, content: str | bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _set_pin(root: Path, ref: str) -> None:
    _write(root, "src/metroliza/shared/docs_links.py", f'DEFAULT_RELEASE_DOCS_REF = "{ref}"\n')


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "work")
    _write(tmp_path, "src/metroliza/ui/help_menu.py", HELP_MENU)
    _write(tmp_path, "src/metroliza/exporting/writer.py", WRITER)
    _write(tmp_path, "docs/user_manual/main_window.md", "# Main window\n\nText.\n")
    _write(tmp_path, "docs/user_manual/parsing.md", "# Parsing\n\nText.\n")
    _write(tmp_path, "docs/user_manual/group/manual.pdf", b"%PDF-1.7\n...")
    _set_pin(tmp_path, "0" * 40)
    return tmp_path


def test_linked_paths_come_from_help_keys_and_export_calls(repo: Path) -> None:
    paths = {item.path: item.origin for item in checker.linked_paths(repo)}

    assert paths == {
        "docs/user_manual/group/manual.pdf": "src/metroliza/exporting/writer.py:3",
        "docs/user_manual/main_window.md": "help:main_window",
        "docs/user_manual/parsing.md": "help:parsing",
    }


def test_complete_pinned_commit_passes(repo: Path) -> None:
    complete = _commit(repo, "manuals")
    _set_pin(repo, complete)

    problems, blobs = checker.check_release_docs_ref(repo)

    assert problems == []
    assert sorted(blobs) == [
        "docs/user_manual/group/manual.pdf",
        "docs/user_manual/main_window.md",
        "docs/user_manual/parsing.md",
    ]
    assert checker.main(["--repo-root", str(repo)]) == 0


@pytest.mark.parametrize("ref", ["master", "develop", "release/2026.09-rc1", "v2026.09", "abc1234"])
def test_moving_or_short_refs_are_rejected_even_when_they_resolve(repo: Path, ref: str) -> None:
    complete = _commit(repo, "manuals")
    _git(repo, "branch", "-f", "master", complete)
    _git(repo, "branch", "-f", "develop", complete)
    _git(repo, "branch", "-f", "release/2026.09-rc1", complete)
    _git(repo, "tag", "v2026.09", complete)
    _set_pin(repo, complete[:7] if ref == "abc1234" else ref)

    problems, _ = checker.check_release_docs_ref(repo)

    assert len(problems) == 1
    assert "not a full commit SHA" in problems[0]
    assert checker.main(["--repo-root", str(repo)]) == 1


def test_commit_missing_a_linked_manual_is_rejected(repo: Path) -> None:
    (repo / "docs/user_manual/parsing.md").unlink()
    incomplete = _commit(repo, "without parsing")
    _write(repo, "docs/user_manual/parsing.md", "# Parsing\n")
    _set_pin(repo, incomplete)

    problems, _ = checker.check_release_docs_ref(repo)

    assert problems == [f"docs/user_manual/parsing.md (help:parsing) is missing at {incomplete}"]


def test_newly_linked_manual_requires_a_new_pin(repo: Path) -> None:
    pinned = _commit(repo, "manuals")
    _write(repo, "src/metroliza/ui/help_menu.py", HELP_MENU.replace(
        '}\n', '    "new": "docs/user_manual/new.md",\n}\n'
    ))
    _write(repo, "docs/user_manual/new.md", "# New\n")
    _commit(repo, "new manual after the pin")
    _set_pin(repo, pinned)

    problems, _ = checker.check_release_docs_ref(repo)

    assert problems == [f"docs/user_manual/new.md (help:new) is missing at {pinned}"]


def test_empty_or_wrong_type_manuals_are_rejected(repo: Path) -> None:
    _write(repo, "docs/user_manual/main_window.md", "\n")
    _write(repo, "docs/user_manual/parsing.md", "Parsing without a title\n")
    _write(repo, "docs/user_manual/group/manual.pdf", b"<html>not found</html>")
    broken = _commit(repo, "broken manuals")
    _set_pin(repo, broken)

    problems, _ = checker.check_release_docs_ref(repo)

    assert problems == [
        f"docs/user_manual/group/manual.pdf (src/metroliza/exporting/writer.py:3) is not a PDF at {broken}",
        f"docs/user_manual/main_window.md (help:main_window) is empty at {broken}",
        f"docs/user_manual/parsing.md (help:parsing) does not start with a Markdown title at {broken}",
    ]


def test_unavailable_commit_is_rejected(repo: Path) -> None:
    _commit(repo, "manuals")
    _set_pin(repo, "1" * 40)

    problems, _ = checker.check_release_docs_ref(repo)

    assert problems == [f"docs ref {'1' * 40} is not a commit available in this checkout (use full history)"]


def test_repository_pin_is_immutable_and_covers_every_linked_manual() -> None:
    ref = checker.pinned_docs_ref(REPO_ROOT)
    assert checker.FULL_COMMIT_SHA.fullmatch(ref), ref
    linked = {item.path for item in checker.linked_paths(REPO_ROOT)}
    assert len([path for path in linked if path.startswith("docs/user_manual/") and path.count("/") == 2]) == 12
    assert "docs/user_manual/group_analysis/user_manual.pdf" in linked

    available = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{ref}^{{commit}}"], capture_output=True, check=False
    )
    if available.returncode != 0:
        pytest.skip("pinned commit is not in this shallow checkout; the static-checks step verifies it")
    problems, _ = checker.check_release_docs_ref(REPO_ROOT)
    assert problems == []
