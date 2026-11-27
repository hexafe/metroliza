"""Named Reports filter drafts stored separately by expression mode."""

from dataclasses import asdict
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from PyQt6.QtCore import QIODevice, QLockFile, QSaveFile, QSettings

from metroliza.reports.report_query_service import build_measurement_filter_query
from metroliza.reports.report_typed_filter import REPORT_TYPED_FILTER_FIELDS
from metroliza.shared.filter_state import decode_filter_state
from metroliza.shared.local_app_paths import local_metroliza_directory
from metroliza.shared.typed_filter import FilterValidationError, dump_typed_filter, load_typed_filter, parse_typed_filter


_MAX_PRESET_LENGTH = 131072
_MAX_EXPRESSION_UNITS = 32767
_TYPED_PRESET_VERSION = 2
_TYPED_FILE_VERSION = 1
_MAX_TYPED_FILE_BYTES = 4 * 1024 * 1024
_MAX_TYPED_PRESETS = 256
_EXPERIMENTAL_GROUP = b"[report_filters_typed_v1]"


def _decode_filter(values):
    state = decode_filter_state(values)
    build_measurement_filter_query(**asdict(state))
    return state


def _unique_json_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON field.")
    return result


def _reject_json_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}.")


def _decode_typed_json(text):
    return json.loads(text, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)


def _typed_expression_document(state):
    expression = parse_typed_filter(state.expression_text, REPORT_TYPED_FILTER_FIELDS)
    if expression is None:
        raise ValueError("Enter a typed report filter expression.")
    return dump_typed_filter(expression)


def typed_preset_expression_fits(text, maximum=_MAX_EXPRESSION_UNITS):
    """Check the UTF-16 limit used by the single-line editor."""
    return len(text.encode("utf-16-le")) <= 2 * min(maximum, _MAX_EXPRESSION_UNITS)


def _decode_typed_state(values):
    state = decode_filter_state(values)
    if not typed_preset_expression_fits(state.expression_text):
        raise ValueError("The saved typed expression is too long for the filter editor.")
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


def _definition_sha256(payload):
    definition = {key: value for key, value in payload.items() if key != "definition_sha256"}
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(canonical.encode("ascii")).hexdigest()


def _typed_preset_state(payload):
    version = payload.get("version")
    if type(version) is int and version == 1:
        raise ValueError("Experimental typed preset has no integrity check. Recreate it as a new draft.")
    if type(version) is not int or version != _TYPED_PRESET_VERSION:
        raise ValueError("Unsupported typed report preset version.")
    if payload.keys() != {"version", "name", "filter", "typed_expression", "definition_sha256"}:
        raise ValueError("Invalid typed report preset fields.")
    if payload["definition_sha256"] != _definition_sha256(payload):
        raise ValueError("The saved typed filter failed its integrity check. The original preset was kept.")
    return _decode_typed_state(payload["filter"])


def _decode_typed_preset(payload):
    state = _typed_preset_state(payload)
    expression = load_typed_filter(payload["typed_expression"], REPORT_TYPED_FILTER_FIELDS)
    if expression is None or dump_typed_filter(expression) != _typed_expression_document(state):
        raise ValueError("Saved typed conditions and expression text disagree. The original preset was kept.")
    return state


class ReportFilterPresets:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else local_metroliza_directory() / "filters" / "reports.ini"

    @property
    def typed_path(self):
        return self.path.with_suffix(".typed.json")

    def _settings(self):
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        settings.sync()
        settings.beginGroup("report_filters_v1")
        return settings

    @staticmethod
    def _key(name):
        return sha256(name.casefold().encode("utf-8")).hexdigest()

    def contains_name(self, name, *, typed=False):
        """Check the storage key even for entries that cannot be read."""
        return self.typed_record(name) is not None if typed else self._settings().contains(self._key(name))

    def typed_record(self, name):
        """Read the existing record, including unreadable presets, before asking to replace it."""
        return self._read_typed_records().get(self._key(name))

    def _read_typed_records(self):
        try:
            with self.typed_path.open("rb") as source:
                raw = source.read(_MAX_TYPED_FILE_BYTES + 1)
        except FileNotFoundError:
            return {}
        except OSError as error:
            raise OSError("Could not read the typed preset file. Check its access and try again.") from error
        if len(raw) > _MAX_TYPED_FILE_BYTES:
            raise ValueError("The typed preset file is too large. It was kept unchanged.")
        try:
            payload = _decode_typed_json(raw.decode("utf-8"))
        except (ValueError, RecursionError) as error:
            raise ValueError("The typed preset file could not be read. It was kept unchanged.") from error
        self._validate_typed_file(payload)
        return payload["presets"]

    @staticmethod
    def _validate_typed_file(payload):
        if not isinstance(payload, dict) or payload.keys() != {"version", "presets"}:
            raise ValueError("Invalid typed preset file format. It was kept unchanged.")
        version = payload["version"]
        if type(version) is not int or version != _TYPED_FILE_VERSION:
            raise ValueError("Unsupported typed preset file version. It was kept unchanged.")
        records = payload["presets"]
        if not isinstance(records, dict) or len(records) > _MAX_TYPED_PRESETS:
            raise ValueError("Invalid typed preset collection. It was kept unchanged.")
        if any(len(key) != 64 or any(char not in "0123456789abcdef" for char in key) or not isinstance(record, str)
               for key, record in records.items()):
            raise ValueError("Invalid typed preset record. The file was kept unchanged.")

    def load(self):
        settings = self._settings()
        return self._load_entries(settings.childKeys(), lambda key: settings.value(key, "", type=str), typed=False)

    def load_typed(self):
        records = self._read_typed_records()
        presets, unavailable = self._load_entries(records, records.__getitem__, typed=True)
        note = self._experimental_ini_note()
        if note:
            unavailable.append(("Experimental typed INI presets", note))
        return presets, unavailable

    def _experimental_ini_note(self):
        # Inspect old storage without creating a QSettings writer or importing entries.
        try:
            with self.path.open("rb") as source:
                raw = source.read(_MAX_TYPED_FILE_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError:
            return "Could not check the old Reports INI for experimental typed presets."
        if _EXPERIMENTAL_GROUP in raw.splitlines():
            return "Experimental typed presets were kept in the old Reports INI. Recreate them as new typed drafts."
        if len(raw) > _MAX_TYPED_FILE_BYTES:
            return "The old Reports INI is too large to check for experimental typed presets."
        return None

    def load_typed_repair_draft(self, name):
        """Read original draft text when a current field or operator needs replacement."""
        key = self._key(name)
        record = self._read_typed_records().get(key)
        if record is None:
            return None
        state = None
        try:
            _, payload = self._read_entry(record, key, typed=True)
            state = _typed_preset_state(payload)
            _decode_typed_preset(payload)
        except FilterValidationError as error:
            if error.code in {"missing_field", "incompatible_type", "unsupported_operator"}:
                return state
        except (KeyError, TypeError, ValueError, RecursionError):
            pass
        return None

    def _read_entry(self, raw, key, *, typed):
        if len(raw) > _MAX_PRESET_LENGTH:
            raise ValueError("Saved report filter is too large.")
        payload = _decode_typed_json(raw) if typed else json.loads(raw)
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 80 or self._key(name) != key:
            raise ValueError("Invalid report filter name.")
        return name, payload

    def _load_entries(self, keys, read_record, *, typed):
        presets = []
        unavailable = []
        for key in keys:
            name = None
            try:
                name, payload = self._read_entry(read_record(key), key, typed=typed)
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
        raw = self._encode({"name": name, "filter": values})
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        settings = self._settings()
        settings.setValue(self._key(name), raw)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            raise OSError("Could not save the report filter.")

    def save_typed(self, name, state, *, expected_record=None):
        if not isinstance(name, str) or not 1 <= len(name) <= 80:
            raise ValueError("Use a name between 1 and 80 characters.")
        values = asdict(state)
        self._encode(values)  # Bound input before parsing it.
        validated = _decode_typed_state(values)
        payload = {
            "version": _TYPED_PRESET_VERSION, "name": name, "filter": values,
            "typed_expression": _typed_expression_document(validated),
        }
        payload["definition_sha256"] = _definition_sha256(payload)
        self._write_typed(self._key(name), self._encode(payload), expected_record)

    @staticmethod
    def _encode(payload):
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > _MAX_PRESET_LENGTH:
            raise ValueError("This filter has too many values to save as a preset.")
        return raw

    def _write_typed(self, key, record, expected_record):
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock = QLockFile(f"{self.path}.typed-write.lock")
        if not lock.tryLock(0):
            raise OSError("Another window is saving a typed report filter. Try again.")
        try:
            records = self._read_typed_records()
            if records.get(key) != expected_record:
                if expected_record is None:
                    raise ValueError("A typed preset already uses this name. Confirm replacement first.")
                raise ValueError("The typed preset changed while you were confirming. Review it and save again.")
            records[key] = record
            raw = json.dumps({"version": _TYPED_FILE_VERSION, "presets": records}, ensure_ascii=False).encode("utf-8")
            if len(records) > _MAX_TYPED_PRESETS or len(raw) > _MAX_TYPED_FILE_BYTES:
                raise ValueError("The typed preset file would exceed its size limit. It was kept unchanged.")
            self._publish_typed_file(raw)
        finally:
            lock.unlock()

    def _publish_typed_file(self, raw):
        output = QSaveFile(str(self.typed_path))
        output.setDirectWriteFallback(False)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError("Could not open a temporary file for the typed presets.")
        if output.write(raw) != len(raw):
            output.cancelWriting()
            raise OSError("Could not write the typed presets. The previous file was kept.")
        if not output.commit():
            raise OSError("Could not publish the typed presets. The previous file was kept.")
