"""Named Reports filter drafts stored separately by expression mode."""

from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from PyQt6.QtCore import QSettings

from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.reports.report_typed_filter import REPORT_TYPED_FILTER_FIELDS
from metroliza.shared.filter_state import decode_filter_state
from metroliza.shared.local_app_paths import local_metroliza_directory
from metroliza.shared.typed_filter import dump_typed_filter, load_typed_filter, parse_typed_filter


_MAX_PRESET_LENGTH = 131072
_TYPED_PRESET_VERSION = 1


def _decode_filter(values):
    state = decode_filter_state(values)
    build_measurement_filter_query(**asdict(state))
    return state


def _typed_expression_document(state):
    expression = parse_typed_filter(state.expression_text, REPORT_TYPED_FILTER_FIELDS)
    if expression is None:
        raise ValueError("Enter a typed report filter expression.")
    return dump_typed_filter(expression)


def _decode_typed_state(values):
    state = decode_filter_state(values)
    for field, selection in values.items():
        if field.endswith("_values") and "SELECT ALL" in selection:
            raise ValueError(f"Invalid saved selection for {field}: SELECT ALL.")
    if state.date_from is None and state.date_to is None:
        return state
    if not state.date_from or not state.date_to:
        raise ValueError("Saved date ranges require both From and To.")
    first = date.fromisoformat(state.date_from)
    last = date.fromisoformat(state.date_to)
    if (first.isoformat(), last.isoformat()) != (state.date_from, state.date_to) or first > last:
        raise ValueError("Invalid saved From and To dates.")
    return state


def _decode_typed_preset(payload):
    version = payload.get("version")
    if type(version) is not int or version != _TYPED_PRESET_VERSION:
        raise ValueError("Unsupported typed report preset version.")
    if payload.keys() != {"version", "name", "filter", "typed_expression"}:
        raise ValueError("Invalid typed report preset fields.")
    state = _decode_typed_state(payload["filter"])
    expression = load_typed_filter(payload["typed_expression"], REPORT_TYPED_FILTER_FIELDS)
    if expression is None or dump_typed_filter(expression) != _typed_expression_document(state):
        raise ValueError("Saved typed conditions and expression text disagree. The original preset was kept.")
    return state


class ReportFilterPresets:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else local_metroliza_directory() / "filters" / "reports.ini"

    def _settings(self, *, typed=False):
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        settings.sync()
        settings.beginGroup("report_filters_typed_v1" if typed else "report_filters_v1")
        return settings

    @staticmethod
    def _key(name):
        return sha256(name.casefold().encode("utf-8")).hexdigest()

    def contains_name(self, name, *, typed=False):
        """Check the storage key even for entries that cannot be read."""
        return self._settings(typed=typed).contains(self._key(name))

    def load(self):
        return self._load(typed=False)

    def load_typed(self):
        return self._load(typed=True)

    def _load(self, *, typed):
        presets = []
        unavailable = []
        settings = self._settings(typed=typed)
        for key in settings.childKeys():
            name = None
            try:
                raw = settings.value(key, "", type=str)
                if len(raw) > _MAX_PRESET_LENGTH:
                    raise ValueError("Saved report filter is too large.")
                payload = json.loads(raw)
                candidate = payload["name"]
                if not isinstance(candidate, str) or not 1 <= len(candidate) <= 80 or self._key(candidate) != key:
                    raise ValueError("Invalid report filter name.")
                name = candidate
                state = _decode_typed_preset(payload) if typed else _decode_filter(payload["filter"])
                presets.append((name, state))
            except (KeyError, TypeError, ValueError, RecursionError) as error:
                detail = str(error.args[0])[:240] if name and error.args else "The saved entry could not be read."
                unavailable.append((name or "Saved filter", detail))
        return sorted(presets, key=lambda entry: entry[0].casefold()), unavailable

    def save(self, name, state):
        if not 1 <= len(name) <= 80:
            raise ValueError("Use a name between 1 and 80 characters.")
        values = asdict(state)
        _decode_filter(values)
        self._write(name, {"name": name, "filter": values})

    def save_typed(self, name, state, *, replace=False):
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ValueError("Use a name between 1 and 80 characters.")
        values = asdict(state)
        self._encode(values)  # Bound input before parsing it.
        validated = _decode_typed_state(values)
        payload = {
            "version": _TYPED_PRESET_VERSION, "name": name, "filter": values,
            "typed_expression": _typed_expression_document(validated),
        }
        self._write(name, payload, typed=True, replace=replace)

    @staticmethod
    def _encode(payload):
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > _MAX_PRESET_LENGTH:
            raise ValueError("This filter has too many values to save as a preset.")
        return raw

    def _write(self, name, payload, *, typed=False, replace=False):
        raw = self._encode(payload)
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        settings = self._settings(typed=typed)
        key = self._key(name)
        if typed and not replace and settings.contains(key):
            raise ValueError("A typed preset already uses this name. Confirm replacement first.")
        settings.setValue(key, raw)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            raise OSError("Could not save the report filter.")
