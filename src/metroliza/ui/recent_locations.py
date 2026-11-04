"""Private local path history; never part of diagnostics or presentation exports."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path

from PyQt6.QtCore import QSettings


class RecentLocations:
    """Versioned, bounded local paths in a dedicated QSettings namespace."""

    ROOT = "metroliza_recent"
    LIMIT = 8

    def __init__(self, settings: QSettings, *, windows: bool | None = None):
        self.settings = settings
        self.windows = os.name == "nt" if windows is None else windows

    def _key(self, kind):
        if kind not in ("databases", "folders"):
            raise ValueError("Unknown recent location kind")
        return f"{self.ROOT}/v1/{kind}"

    def _validated(self, values):
        if not isinstance(values, list):
            return []
        result, seen = [], set()
        path_module = ntpath if self.windows else os.path
        for value in values:
            if not isinstance(value, str) or "\x00" in value or not path_module.isabs(value):
                continue
            # UNC/device paths and URL-like values are not local locations.
            if value.startswith(("//", "\\\\")) or "://" in value:
                continue
            if self.windows and not ntpath.splitdrive(value)[0]:
                continue
            path = path_module.normpath(value)
            identity = path.casefold() if self.windows else path
            if identity not in seen:
                result.append(value)
                seen.add(identity)
        return result[:self.LIMIT]

    def paths(self, kind):
        key = self._key(kind)
        if self.settings.value(f"{self.ROOT}/_schema_version") not in (1, "1"):
            return []
        return self._validated(self.settings.value(key, []))

    def record(self, kind, path):
        value = os.fspath(path) if isinstance(path, Path) else path
        validated = self._validated([value])
        if validated:
            self._write(kind, self._validated(validated + self.paths(kind)))

    def _write(self, kind, paths):
        self.settings.setValue(f"{self.ROOT}/_schema_version", 1)
        self.settings.setValue(self._key(kind), paths)
        self.settings.sync()

    def remove(self, kind, path):
        self._write(kind, [value for value in self.paths(kind) if value != path])

    def clear(self):
        for kind in ("databases", "folders"):
            self._write(kind, [])
