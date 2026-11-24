"""Keep the vendored Plotly runtime and its companion notice together."""

from pathlib import Path
from shutil import copyfile


PLOTLY_NOTICE_FILENAME = "plotly.min.js.LICENSE.txt"


def copy_plotly_runtime_assets(source: Path, destination: Path) -> str | None:
    """Distribute the complete runtime, or let the caller render snapshots."""
    notice = source.with_name(PLOTLY_NOTICE_FILENAME)
    if not source.is_file() or not notice.is_file():
        return None

    copyfile(notice, destination / notice.name)
    copyfile(source, destination / source.name)
    return f"{destination.name}/{source.name}"
