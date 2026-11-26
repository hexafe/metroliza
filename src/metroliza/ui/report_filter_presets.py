"""Named local presets for the typed Reports filter controls."""

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from PyQt6.QtCore import QSettings

from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.shared.filter_state import decode_filter_state
from metroliza.shared.local_app_paths import local_metroliza_directory


def _decode_filter(values):
    state = decode_filter_state(values)
    build_measurement_filter_query(**asdict(state))
    return state


class ReportFilterPresets:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else local_metroliza_directory() / "filters" / "reports.ini"

    def _settings(self):
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        settings.sync()
        settings.beginGroup("report_filters_v1")
        return settings

    @staticmethod
    def _key(name):
        return sha256(name.casefold().encode("utf-8")).hexdigest()

    def load(self):
        presets = []
        unavailable = []
        settings = self._settings()
        for key in settings.childKeys():
            name = None
            try:
                raw = settings.value(key, "", type=str)
                if len(raw) > 131072:
                    raise ValueError("Saved report filter is too large.")
                payload = json.loads(raw)
                candidate = payload["name"]
                if not isinstance(candidate, str) or not 1 <= len(candidate) <= 80 or self._key(candidate) != key:
                    raise ValueError("Invalid report filter name.")
                name = candidate
                presets.append((name, _decode_filter(payload["filter"])))
            except (KeyError, TypeError, ValueError, RecursionError) as error:
                detail = str(error.args[0])[:240] if name and error.args else "The saved entry could not be read."
                unavailable.append((name or "Saved filter", detail))
        return sorted(presets, key=lambda entry: entry[0].casefold()), unavailable

    def save(self, name, state):
        if not 1 <= len(name) <= 80:
            raise ValueError("Use a name between 1 and 80 characters.")
        values = asdict(state)
        _decode_filter(values)
        raw = json.dumps({"name": name, "filter": values}, ensure_ascii=False)
        if len(raw) > 131072:
            raise ValueError("This filter has too many values to save as a preset.")
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        settings = self._settings()
        settings.setValue(self._key(name), raw)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            raise OSError("Could not save the report filter.")
