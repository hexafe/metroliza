"""Repository documentation link helpers shared by UI and export code."""

from __future__ import annotations

import os
from pathlib import Path
import re


GITHUB_REPOSITORY_BASE_URL = "https://github.com/hexafe/metroliza"
RELEASE_DOCS_REF_ENV = "METROLIZA_RELEASE_DOCS_REF"

# Approved manual set for the shipped release, pinned to a full commit SHA so a
# double-clicked EXE opens instructions that match its functionality. A branch
# such as ``master`` moves and can lack manuals; scripts/check_release_docs_ref.py
# rejects such refs and checks that this commit holds every linked manual.
DEFAULT_RELEASE_DOCS_REF = "b2510e0aa651e8c96363e5a9c224c841318cc9d0"

_FULL_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


def is_immutable_docs_ref(ref: str) -> bool:
    """Return whether ``ref`` is a full lowercase commit SHA (not a branch, tag or short SHA)."""
    return bool(_FULL_COMMIT_SHA.fullmatch(ref))


def current_release_docs_ref() -> str:
    """Return the docs ref for rendered repository links.

    ``METROLIZA_RELEASE_DOCS_REF`` remains a developer override; unset or blank
    falls back to the pinned release ref.
    """
    return os.environ.get(RELEASE_DOCS_REF_ENV, "").strip() or DEFAULT_RELEASE_DOCS_REF


GITHUB_RENDERED_DOCS_REF = current_release_docs_ref()


def github_blob_url(path: str | Path) -> str:
    """Return the GitHub-rendered repository URL for a repo-relative path."""
    relative_path = Path(path).as_posix().lstrip("/")
    return f"{GITHUB_REPOSITORY_BASE_URL}/blob/{current_release_docs_ref()}/{relative_path}"
