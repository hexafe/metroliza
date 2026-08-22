from __future__ import annotations

import re
from pathlib import Path


MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
IGNORED_PREFIXES = ("http://", "https://", "mailto:", "#")
DOCS_INDEX_PATH = Path("docs/README.md")
PROJECT_DOCS_ROOT = Path("docs/project")
ROADMAPS_ROOT = Path("docs/roadmaps")
RELEASE_CHECKLIST_PATH = Path("docs/release_checks/release_candidate_checklist.md")
RELEASE_GUIDE_PATHS = (
    Path("docs/release_checks/open_testing_runbook.md"),
    Path("docs/release_checks/release_playbook_beginner.md"),
)
RELEASE_CHECKLIST_FRAGMENT_PATTERN = re.compile(
    r"\]\(\./release_candidate_checklist\.md#([^)]+)\)"
)
PROJECT_METADATA_MARKERS = ("Status:", "Owner:", "Last reviewed:")


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


def markdown_heading_anchors(markdown_text: str) -> set[str]:
    anchors: set[str] = set()
    for line in markdown_text.splitlines():
        heading = line.lstrip("#").strip() if line.startswith("#") else ""
        if not heading:
            continue
        anchor = re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
        anchors.add(anchor)
    return anchors


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


def test_docs_index_inventories_every_project_document() -> None:
    docs_index = DOCS_INDEX_PATH.read_text(encoding="utf-8")
    missing = [
        str(path.relative_to("docs"))
        for path in iter_markdown_files(PROJECT_DOCS_ROOT)
        if str(path.relative_to("docs")) not in docs_index
    ]

    assert not missing, "Project docs missing from docs/README.md index:\n" + "\n".join(missing)


def test_project_documents_declare_status_owner_and_review_date() -> None:
    failures: list[str] = []

    for path in iter_markdown_files(PROJECT_DOCS_ROOT):
        content = path.read_text(encoding="utf-8")
        missing_markers = [marker for marker in PROJECT_METADATA_MARKERS if marker not in content]
        if missing_markers:
            failures.append(f"{path}: missing {', '.join(missing_markers)}")

    assert not failures, "Project docs missing maintenance metadata:\n" + "\n".join(failures)


def test_docs_index_inventories_every_roadmap() -> None:
    docs_index = DOCS_INDEX_PATH.read_text(encoding="utf-8")
    missing = [
        str(path.relative_to("docs"))
        for path in sorted(ROADMAPS_ROOT.glob("*.md"))
        if str(path.relative_to("docs")) not in docs_index
    ]

    assert not missing, "Roadmaps missing from docs/README.md inventory:\n" + "\n".join(missing)


def test_release_guides_reference_existing_checklist_sections() -> None:
    checklist_anchors = markdown_heading_anchors(
        RELEASE_CHECKLIST_PATH.read_text(encoding="utf-8")
    )
    missing: list[str] = []

    for guide_path in RELEASE_GUIDE_PATHS:
        guide = guide_path.read_text(encoding="utf-8")
        for fragment in RELEASE_CHECKLIST_FRAGMENT_PATTERN.findall(guide):
            if fragment not in checklist_anchors:
                missing.append(f"{guide_path}: #{fragment}")

    assert not missing, "Release guides reference missing checklist sections:\n" + "\n".join(
        missing
    )
