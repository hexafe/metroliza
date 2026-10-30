"""Check that in-app Help and export links use a complete, immutable docs ref.

The pinned ref lives in ``src/metroliza/shared/docs_links.py``. The linked paths
are derived from the code, not from a copied list: every value of
``MANUAL_RELATIVE_PATHS`` in ``src/metroliza/ui/help_menu.py`` plus every literal
``github_blob_url("...")`` argument under ``src/``. Discovery fails closed: a
helper call with a computed argument, or a hard-coded ``github.com/.../blob/<ref>/``
link whose ref is not a full SHA, is reported unless listed in
``HARD_CODED_LINK_EXCEPTIONS``. The check fails when the ref is a branch, tag or
short SHA, when the commit is not available locally (run it in a full-history
checkout), or when a linked file is missing or not a plausible manual there.

``--online`` additionally fetches each rendered GitHub page and the raw file at
the pinned commit and compares the raw bytes with the local git blob. It needs
network access and is meant for release preparation, not for every CI run.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_LINKS_PATH = Path("src/metroliza/shared/docs_links.py")
HELP_MENU_PATH = Path("src/metroliza/ui/help_menu.py")
SOURCE_ROOT = Path("src")
FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = "hexafe/metroliza"
HELPER_NAME = "github_blob_url"
# The helper's own definitions forward a variable path; they are not consumers.
HELPER_MODULES = {DOCS_LINKS_PATH.as_posix(), HELP_MENU_PATH.as_posix()}
HARD_CODED_BLOB = re.compile(r"github\.com/hexafe/metroliza/blob/([^/{}\s\"']+)/")
# Developer-only links outside the release Help set, each with its follow-up Issue.
HARD_CODED_LINK_EXCEPTIONS = {
    "src/metroliza/parsing/llm_plugin_factory/scaffold.py": "https://github.com/hexafe/metroliza/issues/1187",
}


@dataclass(frozen=True)
class LinkedPath:
    path: str
    origin: str


def _module_tree(repo_root: Path, relative: Path) -> ast.Module:
    return ast.parse((repo_root / relative).read_text(encoding="utf-8"), filename=str(relative))


def pinned_docs_ref(repo_root: Path) -> str:
    """Return the literal ``DEFAULT_RELEASE_DOCS_REF`` without importing the package."""
    for node in _module_tree(repo_root, DOCS_LINKS_PATH).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_RELEASE_DOCS_REF" for target in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
            raise ValueError("DEFAULT_RELEASE_DOCS_REF must be a string literal")
    raise ValueError(f"DEFAULT_RELEASE_DOCS_REF not found in {DOCS_LINKS_PATH}")


def _helper_aliases(tree: ast.Module) -> set[str]:
    names = {HELPER_NAME}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("docs_links"):
            names.update(alias.asname or alias.name for alias in node.names if alias.name == HELPER_NAME)
    return names


def discovery_problems(repo_root: Path) -> list[str]:
    """Return link sources the path discovery cannot verify."""
    problems = []
    for source in sorted((repo_root / SOURCE_ROOT).rglob("*.py")):
        relative = source.relative_to(repo_root).as_posix()
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=relative)
        aliases = _helper_aliases(tree)
        if relative not in HELPER_MODULES:
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in aliases and not (
                    node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                ):
                    problems.append(f"{relative}:{node.lineno} calls {name} with a computed path")
        if relative in HARD_CODED_LINK_EXCEPTIONS:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for ref in HARD_CODED_BLOB.findall(line):
                if not FULL_COMMIT_SHA.fullmatch(ref):
                    problems.append(f"{relative}:{line_number} hard-codes the moving docs ref {ref!r}")
    return problems


def linked_paths(repo_root: Path) -> tuple[LinkedPath, ...]:
    """Return every repository path the release links to, with where it comes from."""
    found: dict[str, LinkedPath] = {}
    manual_paths = None
    for node in _module_tree(repo_root, HELP_MENU_PATH).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MANUAL_RELATIVE_PATHS" for target in node.targets
        ):
            manual_paths = ast.literal_eval(node.value)
    if not isinstance(manual_paths, dict) or not manual_paths:
        raise ValueError(f"MANUAL_RELATIVE_PATHS literal not found in {HELP_MENU_PATH}")
    for key, value in manual_paths.items():
        found.setdefault(value, LinkedPath(value, f"help:{key}"))

    for source in sorted((repo_root / SOURCE_ROOT).rglob("*.py")):
        relative = source.relative_to(repo_root)
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(relative))
        aliases = _helper_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in aliases or not node.args:
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                path = argument.value.lstrip("/")
                found.setdefault(path, LinkedPath(path, f"{relative.as_posix()}:{node.lineno}"))
    return tuple(sorted(found.values(), key=lambda item: item.path))


def _git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True, check=False)


def _blob_problem(path: str, content: bytes) -> str | None:
    if not content.strip():
        return "is empty"
    if path.endswith(".md"):
        lines = content.decode("utf-8", errors="replace").lstrip("\ufeff").lstrip().splitlines()
        if not lines:
            return "is empty"
        if not lines[0].startswith("# "):
            return "does not start with a Markdown title"
    elif path.endswith(".pdf") and not content.startswith(b"%PDF-"):
        return "is not a PDF"
    return None


def check_release_docs_ref(repo_root: Path, *, ref: str | None = None) -> tuple[list[str], dict[str, bytes]]:
    """Return problems plus the blobs that were read, keyed by path."""
    ref = pinned_docs_ref(repo_root) if ref is None else ref
    if not FULL_COMMIT_SHA.fullmatch(ref):
        return [f"docs ref {ref!r} is not a full commit SHA; branches, tags and short SHAs can move"], {}
    kind = _git(repo_root, "cat-file", "-t", ref)
    if kind.returncode != 0 or kind.stdout.strip() != b"commit":
        return [f"docs ref {ref} is not a commit available in this checkout (use full history)"], {}

    problems = discovery_problems(repo_root)
    blobs: dict[str, bytes] = {}
    for item in linked_paths(repo_root):
        shown = _git(repo_root, "show", f"{ref}:{item.path}")
        if shown.returncode != 0:
            problems.append(f"{item.path} ({item.origin}) is missing at {ref}")
            continue
        problem = _blob_problem(item.path, shown.stdout)
        if problem:
            problems.append(f"{item.path} ({item.origin}) {problem} at {ref}")
        blobs[item.path] = shown.stdout
    return problems, blobs


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "metroliza-release-docs-check"})
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - fixed https GitHub URLs
        return response.read()


def check_online(ref: str, blobs: dict[str, bytes]) -> list[str]:
    """Return problems found on the published rendered pages and raw files."""
    problems: list[str] = []
    for path, local in sorted(blobs.items()):
        page = f"https://github.com/{REPOSITORY}/blob/{ref}/{path}"
        raw = f"https://raw.githubusercontent.com/{REPOSITORY}/{ref}/{path}"
        try:
            _fetch(page)
            remote = _fetch(raw)
        except (urllib.error.URLError, TimeoutError) as exc:
            problems.append(f"{path}: {exc}")
            continue
        if remote != local:
            problems.append(f"{path}: published raw content differs from the local blob")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--ref", help="Check this ref instead of DEFAULT_RELEASE_DOCS_REF.")
    parser.add_argument("--online", action="store_true", help="Also verify the published GitHub pages.")
    args = parser.parse_args(argv)

    ref = args.ref or pinned_docs_ref(args.repo_root)
    problems, blobs = check_release_docs_ref(args.repo_root, ref=ref)
    if not problems and args.online:
        problems = check_online(ref, blobs)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    mode = "local and published" if args.online else "local"
    print(f"Release docs ref {ref}: {len(blobs)} linked files verified ({mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
