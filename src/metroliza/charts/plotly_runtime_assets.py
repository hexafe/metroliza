"""Keep the vendored Plotly runtime and its companion notice together."""

from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory


PLOTLY_NOTICE_FILENAME = "plotly.min.js.LICENSE.txt"


def copy_plotly_runtime_assets(source: Path, destination: Path) -> str | None:
    """Distribute the complete runtime, or let the caller render snapshots."""
    notice = source.with_name(PLOTLY_NOTICE_FILENAME)
    if not source.is_file() or not notice.is_file():
        return None

    with TemporaryDirectory(prefix=".plotly-", dir=destination) as scratch:
        staging = Path(scratch)
        staged_notice, staged_script = staging / notice.name, staging / source.name
        copyfile(notice, staged_notice)
        copyfile(source, staged_script)
        staged_notice.replace(destination / notice.name)
        staged_script.replace(destination / source.name)
    return f"{destination.name}/{source.name}"
