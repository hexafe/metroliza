"""Typed application workspace state shared by modeless UI surfaces."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from PyQt6.QtCore import QObject, pyqtSignal


PathInput: TypeAlias = str | os.PathLike[str] | None
_UNSET = object()


class WorkspaceField(str, Enum):
    """Fields whose changes may affect an open modeless window."""

    SOURCE_DIRECTORY = "source_directory"
    DATABASE_FILE = "database_file"


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """Immutable, monotonically versioned application workspace state."""

    version: int = 0
    source_directory: str | None = None
    database_file: str | None = None

    def changed_fields(self, previous: WorkspaceSnapshot) -> frozenset[WorkspaceField]:
        changed: set[WorkspaceField] = set()
        if self.source_directory != previous.source_directory:
            changed.add(WorkspaceField.SOURCE_DIRECTORY)
        if self.database_file != previous.database_file:
            changed.add(WorkspaceField.DATABASE_FILE)
        return frozenset(changed)


class WorkspaceContext(QObject):
    """Own workspace state and emit one coherent snapshot per real change."""

    snapshot_changed = pyqtSignal(object, object)
    source_directory_changed = pyqtSignal(object, int)
    database_file_changed = pyqtSignal(object, int)

    def __init__(
        self,
        *,
        source_directory: PathInput = None,
        database_file: PathInput = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._snapshot = WorkspaceSnapshot(
            version=0,
            source_directory=_normalize_optional_path(source_directory),
            database_file=_normalize_optional_path(database_file),
        )

    @property
    def snapshot(self) -> WorkspaceSnapshot:
        return self._snapshot

    def update(
        self,
        *,
        source_directory: PathInput | object = _UNSET,
        database_file: PathInput | object = _UNSET,
    ) -> WorkspaceSnapshot:
        """Apply multiple workspace changes under one version increment."""

        previous = self._snapshot
        next_source = (
            previous.source_directory
            if source_directory is _UNSET
            else _normalize_optional_path(source_directory)
        )
        next_database = (
            previous.database_file
            if database_file is _UNSET
            else _normalize_optional_path(database_file)
        )
        if (
            next_source == previous.source_directory
            and next_database == previous.database_file
        ):
            return previous

        current = WorkspaceSnapshot(
            version=previous.version + 1,
            source_directory=next_source,
            database_file=next_database,
        )
        self._snapshot = current
        self.snapshot_changed.emit(current, previous)
        if current.source_directory != previous.source_directory:
            self.source_directory_changed.emit(current.source_directory, current.version)
        if current.database_file != previous.database_file:
            self.database_file_changed.emit(current.database_file, current.version)
        return current

    def set_source_directory(self, source_directory: PathInput) -> WorkspaceSnapshot:
        return self.update(source_directory=source_directory)

    def set_database_file(self, database_file: PathInput) -> WorkspaceSnapshot:
        return self.update(database_file=database_file)

    def clear(self) -> WorkspaceSnapshot:
        return self.update(source_directory=None, database_file=None)


def _normalize_optional_path(value: PathInput | object) -> str | None:
    if value is None:
        return None
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str):
        raise TypeError("Workspace paths must be strings, path-like values, or None.")
    return value if value.strip() else None


__all__ = ["PathInput", "WorkspaceContext", "WorkspaceField", "WorkspaceSnapshot"]
