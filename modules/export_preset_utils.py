import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


EXPORT_PRESET_FAST_DIAGNOSTICS = "fast_diagnostics"
EXPORT_PRESET_FULL_REPORT = "full_report"
EXPORT_PRESET_DEFAULT = EXPORT_PRESET_FAST_DIAGNOSTICS

_EXPORT_PRESET_DEFINITIONS = {
    EXPORT_PRESET_FAST_DIAGNOSTICS: {
        'label': 'Main plots',
        'description': 'Exports core charts for fast day-to-day review.',
        'intended_use': 'Use when you need the standard report quickly.',
        'options': {
            'export_type': 'line',
            'sorting_parameter': 'date',
            'violin_plot_min_samplesize': 8,
            'summary_plot_scale': 0,
            'hide_ok_results': False,
            'generate_summary_sheet': False,
        },
    },
    EXPORT_PRESET_FULL_REPORT: {
        'label': 'Extended plots',
        'description': 'Includes the core charts plus extended summary outputs.',
        'intended_use': 'Use for deeper analysis and handoff-ready reporting.',
        'options': {
            'export_type': 'line',
            'sorting_parameter': 'date',
            'violin_plot_min_samplesize': 6,
            'summary_plot_scale': 0,
            'hide_ok_results': False,
            'generate_summary_sheet': True,
        },
    },
}


def get_export_preset_ids():
    return list(_EXPORT_PRESET_DEFINITIONS.keys())


def get_export_preset_label(preset_id):
    return _EXPORT_PRESET_DEFINITIONS[resolve_export_preset_id(preset_id)]['label']


def get_export_preset_labels():
    return [get_export_preset_label(preset_id) for preset_id in get_export_preset_ids()]


def get_export_preset_id_for_label(label):
    for preset_id, payload in _EXPORT_PRESET_DEFINITIONS.items():
        if payload.get('label') == label:
            return preset_id
    return EXPORT_PRESET_DEFAULT


def get_export_preset_description(preset_id):
    return _EXPORT_PRESET_DEFINITIONS[resolve_export_preset_id(preset_id)].get('description', '')


def get_export_preset_intended_use(preset_id):
    return _EXPORT_PRESET_DEFINITIONS[resolve_export_preset_id(preset_id)].get('intended_use', '')


def resolve_export_preset_id(preset_id):
    normalized = str(preset_id or '').strip().lower()
    return normalized if normalized in _EXPORT_PRESET_DEFINITIONS else EXPORT_PRESET_DEFAULT


def build_export_options_for_preset(preset_id):
    normalized = resolve_export_preset_id(preset_id)
    return dict(_EXPORT_PRESET_DEFINITIONS[normalized]['options'])


def load_export_dialog_config(config_path):
    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        with path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "Failed to load export dialog config from %s (%s): %s",
            path,
            exc.__class__.__name__,
            exc,
        )
        return {}

    return payload if isinstance(payload, dict) else {}


def migrate_export_dialog_config(config_payload):
    if not isinstance(config_payload, dict):
        return {'selected_preset': EXPORT_PRESET_DEFAULT}, True

    selected_preset = resolve_export_preset_id(config_payload.get('selected_preset'))
    migrated = {
        'selected_preset': selected_preset,
    }

    return migrated, migrated != config_payload


def save_export_dialog_config(config_path, config_payload):
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        json.dump(config_payload, handle, indent=2, sort_keys=True)
