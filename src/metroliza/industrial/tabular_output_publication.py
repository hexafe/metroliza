"""Publish a complete CSV Summary dashboard, assets and optional workbook."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory, mkdtemp
from unicodedata import normalize

from metroliza.exporting.output_publication import (
    OutputConsent,
    OutputPublicationCanceled,
    _move_dashboard_assets,
    conflicting_outputs,
    publish_output,
)

_ASSET_OWNER_FILE = ".metroliza-tabular-dashboard"


def _output_entry(path: str) -> Path:
    entry = Path(path).expanduser()
    return entry.parent.resolve() / entry.name


def _aliases(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return first.samefile(second)
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class TabularOutputFiles:
    dashboard: Path
    workbook: Path | None = None

    @classmethod
    def from_paths(cls, dashboard: str, workbook: str) -> TabularOutputFiles:
        return cls(_output_entry(dashboard), _output_entry(workbook) if workbook else None)

    @property
    def paths(self) -> tuple[Path, ...]:
        return (self.dashboard,) if self.workbook is None else (self.dashboard, self.workbook)

    @property
    def assets(self) -> Path:
        from metroliza.charts.export_html_dashboard import resolve_html_dashboard_assets_dir

        return resolve_html_dashboard_assets_dir(self.dashboard)

    def conflicts(self) -> tuple[Path, ...]:
        from metroliza.industrial.industrial_analytics_dashboard import resolve_production_dashboard_assets_dir

        legacy_assets = resolve_production_dashboard_assets_dir(self.dashboard)
        conflicts = conflicting_outputs(self.paths)
        if legacy_assets not in conflicts and os.path.lexists(legacy_assets):
            conflicts += (legacy_assets,)
        return conflicts

    def validate_sources(self, sources: tuple[Path, ...]) -> None:
        if self.workbook is not None and _aliases(self.dashboard, self.workbook):
            raise ValueError("The dashboard and workbook must use different files.")
        if any(_aliases(output, source) for output in self.paths for source in sources):
            raise ValueError("An output matches a source file. Choose a different output path.")

    def replacement_consents(self) -> tuple[OutputConsent, ...] | None:
        consents = []
        for path in self.paths:
            if not os.path.lexists(path):
                continue
            if path.is_symlink() or not path.is_file():
                return None
            consents.append(OutputConsent.for_path(path))
        return tuple(consents)

    def free_copy(self, sources: tuple[Path, ...]) -> TabularOutputFiles:
        from metroliza.charts.export_html_dashboard import _bounded_dashboard_output_component

        number = 2
        while True:
            paths = tuple(path.with_name(_bounded_dashboard_output_component(
                path.stem, suffix=f" ({number}){path.suffix}",
            )) for path in self.paths)
            candidate = TabularOutputFiles(*paths)
            if not candidate.conflicts() and not any(
                _aliases(path, source) for path in paths for source in sources
            ):
                return candidate
            number += 1


@dataclass(frozen=True)
class TabularOutputPublication:
    outputs: TabularOutputFiles
    sources: tuple[Path, ...]
    replace_outputs: tuple[OutputConsent, ...] | None = None
    copy_from: TabularOutputFiles | None = None

    def check(self, outputs: TabularOutputFiles) -> None:
        outputs.validate_sources(self.sources)
        if self.replace_outputs is None:
            if outputs.conflicts():
                raise FileExistsError("An analytics output already exists. Generate again to choose what to save.")
        elif outputs.replacement_consents() != self.replace_outputs:
            raise FileExistsError("An analytics output changed after confirmation. Generate again to review it.")


def publish_tabular_analysis(render, publication: TabularOutputPublication, *, should_cancel):
    """Render in private folders and publish complete files on their destination filesystems."""
    outputs = publication.outputs
    for attempt in range(20):
        try:
            _check_cancelled(should_cancel)
            publication.check(outputs)
            return _render_and_publish(render, publication, outputs, should_cancel)
        except FileExistsError:
            if publication.copy_from is None or attempt == 19:
                raise
            outputs = publication.copy_from.free_copy(publication.sources)


def _render_and_publish(render, publication, outputs, should_cancel):
    with ExitStack() as stack:
        for path in outputs.paths:
            path.parent.mkdir(parents=True, exist_ok=True)
        html_stage = Path(stack.enter_context(TemporaryDirectory(prefix=".mza-", dir=outputs.dashboard.parent)))
        staged_workbook = None
        if outputs.workbook is not None:
            workbook_stage = html_stage
            if outputs.workbook.parent != outputs.dashboard.parent:
                workbook_stage = Path(stack.enter_context(TemporaryDirectory(prefix=".mza-", dir=outputs.workbook.parent)))
            staged_workbook = workbook_stage / "workbook.xlsx"
        result = render(
            output_dashboard_file=str(html_stage / "dashboard.html"),
            output_workbook_file=str(staged_workbook) if staged_workbook is not None else None,
            output_assets_dir=html_stage / outputs.assets.name,
        )
        staged_assets = Path(result.html_dashboard_assets_path)
        (staged_assets / _ASSET_OWNER_FILE).write_text(os.path.normcase(outputs.dashboard.name), encoding="utf-8")
        destination_assets = _publish_staged(result, staged_assets, staged_workbook, publication, outputs, should_cancel)
    return replace(result, html_dashboard_path=str(outputs.dashboard), html_dashboard_assets_path=str(destination_assets),
                   workbook_path=str(outputs.workbook) if outputs.workbook is not None else "")


def _output_lock_order(path: Path):
    from metroliza.charts.export_html_dashboard import _output_lock_path

    lock = _output_lock_path(path)
    # Order the shared locks themselves, including when output spellings differ.
    return lock.name, normalize("NFC", str(lock.parent).casefold()), lock.parent


def _publish_staged(result, staged_assets, staged_workbook, publication, outputs, should_cancel):
    from metroliza.charts.export_html_dashboard import _dashboard_publication_lock

    destination_assets = outputs.dashboard.parent / staged_assets.name
    consents = publication.replace_outputs or ()
    with ExitStack() as stack:
        for path in sorted(outputs.paths, key=_output_lock_order):
            stack.enter_context(_dashboard_publication_lock(path, should_cancel=should_cancel))
        _check_cancelled(should_cancel)
        publication.check(outputs)
        destination_assets.mkdir()
        try:
            for asset in staged_assets.iterdir():
                _move_dashboard_assets(asset, destination_assets / asset.name)
            with _workbook_publication(staged_workbook, outputs.workbook, consents, should_cancel):
                _check_cancelled(should_cancel)
                publish_output(result.html_dashboard_path, outputs.dashboard, consents=consents)
        except BaseException:
            shutil.rmtree(destination_assets, ignore_errors=True)
            raise
        if any(consent.path == outputs.dashboard for consent in consents):
            _retire_owned_assets(outputs, destination_assets, publication.sources)
    return destination_assets


def _check_cancelled(should_cancel):
    if should_cancel():
        raise OutputPublicationCanceled("Analytics generation was canceled.")


def _backup_workbook(target):
    backup = Path(mkdtemp(prefix=".metroliza-previous-", dir=target.parent)) / "workbook.xlsx"
    try:
        try:
            os.link(target, backup)
        except OSError:
            shutil.copy2(target, backup)
    except BaseException:
        shutil.rmtree(backup.parent, ignore_errors=True)
        raise
    return backup


@contextmanager
def _workbook_publication(staged, target, consents, should_cancel):
    if staged is None:
        yield
        return
    previous = _backup_workbook(target) if any(item.path == target for item in consents) else None
    preserve_backup = False
    try:
        _check_cancelled(should_cancel)
        published = OutputConsent(target, OutputConsent.for_path(staged).identity)
        publish_output(staged, target, consents=consents)
        try:
            yield
        except BaseException:
            try:
                _restore_workbook(target, published, previous)
            except OSError as exc:
                if previous is not None:
                    preserve_backup = True
                    raise OSError(f"Could not restore {target}. The previous workbook is in {previous}.") from exc
                raise
            raise
    finally:
        if previous is not None and not preserve_backup:
            shutil.rmtree(previous.parent, ignore_errors=True)


def _restore_workbook(target, published, previous):
    if not os.path.lexists(target):
        if previous is not None:
            publish_output(previous, target)
        return
    if OutputConsent.for_path(target) != published:
        raise FileExistsError(f"The workbook at {target} changed during publication.")
    if previous is None:
        target.unlink()
    else:
        publish_output(previous, target, consents=(published,))


def _retire_owned_assets(outputs, current_assets, sources):
    from metroliza.industrial.industrial_analytics_dashboard import PLOTLY_ASSET_NAME

    for directory in outputs.assets.parent.glob(f"{outputs.assets.name}.generation-*"):
        if directory == current_assets or directory.is_symlink():
            continue
        marker = directory / _ASSET_OWNER_FILE
        try:
            if any(source.resolve().is_relative_to(directory.resolve()) for source in sources):
                continue
            entries = tuple(directory.iterdir())
            if not all(entry.name in {_ASSET_OWNER_FILE, PLOTLY_ASSET_NAME} and
                       not entry.is_symlink() and entry.is_file() for entry in entries):
                continue
            if marker.read_text(encoding="utf-8") == os.path.normcase(outputs.dashboard.name):
                shutil.rmtree(directory)
        except (OSError, RuntimeError, UnicodeError):
            continue
