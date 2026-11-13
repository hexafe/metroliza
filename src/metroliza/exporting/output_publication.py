"""Operation-scoped consent and atomic, collision-safe output publication."""

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import shutil
import tempfile
import time

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


def retry_output_copy(operation, target, *, copy_from=None, html_only=False, dashboard=False):
    """Retry publication collisions only for the operation's explicit Save a copy choice."""
    target = Path(target)
    for attempt in range(20):
        try:
            return target, operation(target)
        except FileExistsError:
            if copy_from is None or attempt == 19:
                raise
            target = free_copy_path(copy_from, html_only=html_only, dashboard=dashboard)


_RENAME_NOREPLACE = 1
_AT_FDCWD = -100


def _rename_noreplace(temporary, target):
    """Linux ``renameat2(RENAME_NOREPLACE)``: atomic and never replaces; False if unsupported."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError):
        return False
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if renameat2(_AT_FDCWD, os.fsencode(temporary), _AT_FDCWD, os.fsencode(target), _RENAME_NOREPLACE) == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number in {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP}:
        return False
    raise OSError(error_number, os.strerror(error_number), str(target))


def _rename_without_hardlink(temporary, target):
    """Publish complete content atomically where hard links are unavailable (e.g. vfat/exFAT/CIFS).

    The final name never holds partial content. Without kernel no-replace support
    an existence check precedes the atomic rename; only a writer racing inside
    that window could still be replaced (documented limitation).
    """
    if _rename_noreplace(temporary, target):
        return
    if os.path.lexists(target):
        raise FileExistsError(errno.EEXIST, "Output already exists", str(target))
    os.rename(temporary, target)


def _publish_new_output(temporary, target):
    if _WINDOWS:
        os.rename(temporary, target)
        return
    try:
        os.link(temporary, target)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK}:
            raise
        _rename_without_hardlink(temporary, target)
        return
    temporary.unlink()


def publish_output(temporary, target, *, consents=(), replace=None):
    """Publish a complete file, refusing an unapproved collision even after a race.

    Windows rename refuses an existing destination; on POSIX a hard link provides
    atomic no-clobber publication on the same filesystem. Explicit replacement
    retains temp-file + os.replace publication. Filesystems without hard links use
    an atomic no-replace rename (see ``_rename_without_hardlink``); the final name
    never receives partial content.
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
                _publish_new_output(temporary, target)
            except FileExistsError as exc:
                raise FileExistsError(f"Output already exists: {target}. Save a copy or confirm Replace again.") from exc
    except PermissionError as exc:
        guidance = "Close it in Excel or choose Save a copy" if consent is not None or _WINDOWS else "Check folder permissions and filesystem support"
        raise PermissionError(f"Cannot publish {target}. {guidance}; the existing file was kept.") from exc


def _move_dashboard_assets(source, destination):
    """Allow a short AV/indexer handle hold without retrying other I/O failures."""
    for attempt in range(10):
        try:
            os.rename(source, destination)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def write_dashboard_safely(writer, *, consents=(), should_cancel=lambda: False, copy_from=None, **kwargs):
    """Render/publish a dashboard, retrying collisions only for Save a copy."""
    def publish(target):
        render_kwargs = dict(kwargs, output_path=target, assets_dir=target.with_name(f"{target.stem}_assets"))
        if kwargs.get("source_label") == Path(kwargs["output_path"]).name:
            render_kwargs["source_label"] = target.name
        return _write_dashboard_once(
            writer, consents=consents, should_cancel=should_cancel,
            **render_kwargs,
        )

    _target, result = retry_output_copy(publish, kwargs["output_path"], copy_from=copy_from, html_only=True)
    return result


def _write_dashboard_once(writer, *, consents, should_cancel, **kwargs):
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
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".metroliza-export-", dir=target.parent) as scratch:
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
            _move_dashboard_assets(staged_assets, destination_assets)
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
