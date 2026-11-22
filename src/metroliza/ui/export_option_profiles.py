"""Persist protected local export option profiles without source or output bindings."""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

from PyQt6.QtCore import QSettings

from metroliza.exporting.contracts import ExportOptions, validate_export_options
from metroliza.exporting.export_preset_utils import get_export_preset_ids
from metroliza.shared.local_app_paths import local_metroliza_directory


@dataclass(frozen=True)
class ExportOptionProfile:
    name: str
    base_preset: str
    export_type: str
    sorting_parameter: str
    violin_plot_min_samplesize: int
    summary_plot_scale: int
    hide_ok_results: bool
    local_html: bool
    google_sheets: bool
    industrial_context: bool

    @property
    def profile_id(self):
        return "saved:" + sha256(self.name.casefold().encode("utf-8")).hexdigest()

    def chart_options(self):
        return {
            "export_type": self.export_type,
            "sorting_parameter": self.sorting_parameter,
            "violin_plot_min_samplesize": self.violin_plot_min_samplesize,
            "summary_plot_scale": self.summary_plot_scale,
            "hide_ok_results": self.hide_ok_results,
        }

    def validate(self):
        if not isinstance(self.name, str) or not 1 <= len(self.name.strip()) <= 80:
            raise ValueError("Use a name between 1 and 80 characters.")
        if self.base_preset not in get_export_preset_ids():
            raise ValueError("Unknown base export preset.")
        if any(type(value) is not bool for value in (
            self.hide_ok_results, self.local_html, self.google_sheets, self.industrial_context,
        )):
            raise ValueError("Invalid saved output choices.")
        if (type(self.violin_plot_min_samplesize) is not int or self.violin_plot_min_samplesize < 2
                or type(self.summary_plot_scale) is not int or self.summary_plot_scale < 0):
            raise ValueError("Invalid saved chart limits.")
        validate_export_options(ExportOptions(preset=self.base_preset, **self.chart_options()))


class ExportOptionProfiles:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else local_metroliza_directory() / "profiles" / "reports-export.ini"

    def _settings(self):
        settings = QSettings(str(self.path), QSettings.Format.IniFormat)
        settings.sync()
        settings.beginGroup("export_options_v1")
        return settings

    def load(self):
        settings = self._settings()
        profiles = []
        for key in settings.childKeys():
            try:
                raw = settings.value(key, "", type=str)
                if len(raw) > 16384:
                    continue
                profile = ExportOptionProfile(**json.loads(raw))
                profile.validate()
                if profile.profile_id == key:
                    profiles.append(profile)
            except (TypeError, ValueError, RecursionError):
                continue
        return sorted(profiles, key=lambda profile: profile.name.casefold())

    def save(self, profile):
        profile.validate()
        raw = json.dumps(asdict(profile), ensure_ascii=False)
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        settings = self._settings()
        settings.setValue(profile.profile_id, raw)
        settings.sync()
        if settings.status() != QSettings.Status.NoError:
            raise OSError("Could not save the export option profile.")
