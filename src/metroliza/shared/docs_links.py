"""Repository documentation link helpers shared by UI and export code."""

from __future__ import annotations

import os
from pathlib import Path


GITHUB_REPOSITORY_BASE_URL = "https://github.com/hexafe/metroliza"
DEFAULT_RELEASE_DOCS_REF = "master"


def current_release_docs_ref() -> str:
    """Return the docs branch/ref configured for rendered repository links."""
    return os.environ.get("METROLIZA_RELEASE_DOCS_REF", DEFAULT_RELEASE_DOCS_REF)


GITHUB_RENDERED_DOCS_REF = current_release_docs_ref()


def github_blob_url(path: str | Path) -> str:
    """Return the GitHub-rendered repository URL for a repo-relative path."""
    relative_path = Path(path).as_posix().lstrip("/")
    return f"{GITHUB_REPOSITORY_BASE_URL}/blob/{current_release_docs_ref()}/{relative_path}"
