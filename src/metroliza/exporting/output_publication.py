"""Operation-scoped consent and atomic, collision-safe output publication."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile

_WINDOWS = os.name == "nt"


class OutputPublicationCanceled(Exception):
    """A completed staged output was cancelled before it could be published."""


def _entry_path(path):
    path = Path(path)
    return path.parent.resolve() / path.name


def _identity(path):
    stat = Path(path).lstat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


@dataclass(frozen=True)
class OutputConsent:
    """The exact directory entry accepted for replacement in one request."""

    path: Path
    identity: tuple[int, int, int, int]

    @classmethod
    def for_path(cls, path):
        return cls(_entry_path(path), _identity(path))


def output_paths(primary, *, html_only=False, dashboard=False):
    """Return the complete set of final file names used by this export."""
    primary = Path(primary)
    if html_only:
        return (primary,)
    html = primary.with_name(f"{primary.stem}_dashboard.html")
    return (primary, html) if dashboard else (primary,)


def conflicting_outputs(paths):
    """Include legacy dashboard assets when choosing a free sibling name."""
    conflicts = []
    for path in paths:
        if os.path.lexists(path):
            conflicts.append(path)
        if path.suffix.lower() == ".html":
            assets = path.with_name(f"{path.stem}_assets")
            if assets.exists():
                conflicts.append(assets)
            conflicts.extend(assets.parent.glob(f"{assets.name}.generation-*"))
    return tuple(conflicts)


def free_copy_path(primary, *, html_only=False, dashboard=False):
    primary = Path(primary)
    number = 2
    candidate = primary
    while conflicting_outputs(output_paths(candidate, html_only=html_only, dashboard=dashboard)):
        candidate = primary.with_name(f"{primary.stem} ({number}){primary.suffix}")
        number += 1
    return candidate


def publish_output(temporary, target, *, consents=(), replace=None):
    """Publish a complete file, refusing an unapproved collision even after a race.

    Windows rename refuses an existing destination; on POSIX a hard link provides
    atomic no-clobber publication on the same filesystem. Explicit replacement
    retains temp-file + os.replace publication. Unsupported filesystems fail safely.
    """
    temporary, target = Path(temporary), Path(target)
    consent = next((item for item in consents if item.path == _entry_path(target)), None)
    try:
        if consent is not None and os.path.lexists(target):
            if _identity(target) != consent.identity:
                raise FileExistsError(f"Output changed after confirmation: {target}. Save a copy or confirm again.")
            (replace or os.replace)(temporary, target)
        else:
            try:
                if _WINDOWS:
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
                    temporary.unlink()
            except FileExistsError as exc:
                raise FileExistsError(f"Output already exists: {target}. Save a copy or confirm Replace again.") from exc
    except PermissionError as exc:
        raise PermissionError(f"Cannot publish {target}. Close it in Excel or choose Save a copy; the existing file was kept.") from exc


def write_dashboard_safely(writer, *, consents=(), should_cancel=lambda: False, **kwargs):
    """Render isolated dashboard generations, then publish HTML under the same policy.

    Generation asset names are unique. Existing HTML/assets are never touched
    during rendering, on cancellation or on a failed publication. Approved
    replacement retires old assets only after HTML commits, under the existing
    dashboard publication lock shared with other dashboard writers.
    """
    from metroliza.charts.export_html_dashboard import (
        _dashboard_publication_lock,
        _remove_obsolete_dashboard_generations,
    )

    target = Path(kwargs["output_path"])
    assets = Path(kwargs["assets_dir"])
    with tempfile.TemporaryDirectory(prefix=f".{target.stem}.tmp-", dir=target.parent) as scratch:
        stage = Path(scratch)
        staged_kwargs = dict(kwargs, output_path=stage / target.name, assets_dir=stage / assets.name)
        result = writer(**staged_kwargs)
        if should_cancel():
            raise OutputPublicationCanceled()
        with _dashboard_publication_lock(target):
            if should_cancel():
                raise OutputPublicationCanceled()
            staged_assets = Path(result["html_dashboard_assets_path"])
            destination_assets = target.parent / staged_assets.name
            os.rename(staged_assets, destination_assets)
            try:
                publish_output(stage / target.name, target, consents=consents)
            except BaseException:
                shutil.rmtree(destination_assets, ignore_errors=True)
                raise
            if any(consent.path == _entry_path(target) for consent in consents):
                _remove_obsolete_dashboard_generations(assets, keep=destination_assets)
        result["html_dashboard_path"] = str(target)
        result["html_dashboard_assets_path"] = str(destination_assets)
        return result
