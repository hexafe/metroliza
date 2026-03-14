"""Pure summary-sheet composition helpers for exporter rendering flows."""


def classify_capability_status(cp, cpk):
    """Classify capability readiness into scan-friendly quality tiers."""

    def _as_float(value):
        if isinstance(value, str):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    cp_value = _as_float(cp)
    cpk_value = _as_float(cpk)
    if cp_value is None or cpk_value is None:
        return {
            'label': 'Cp/Cpk N/A',
            'palette_key': 'quality_unknown',
        }

    if cpk_value >= 1.67 and cp_value >= 1.67:
        return {
            'label': 'Cp/Cpk capable',
            'palette_key': 'quality_capable',
        }

    if cpk_value > 1.33 and cp_value > 1.33:
        return {
            'label': 'Cp/Cpk good',
            'palette_key': 'quality_good',
        }

    if cpk_value >= 1.0 and cp_value >= 1.0:
        return {
            'label': 'Cp/Cpk marginal',
            'palette_key': 'quality_marginal',
        }

    return {
        'label': 'Cp/Cpk risk',
        'palette_key': 'quality_risk',
    }


def classify_capability_value(value, *, label_prefix='Capability'):
    """Classify a single Cp/Cpk value for independent row highlighting."""

    def _as_float(raw):
        if isinstance(raw, str):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    numeric = _as_float(value)
    if numeric is None:
        return {'label': f'{label_prefix} N/A', 'palette_key': 'quality_unknown'}
    if numeric >= 1.67:
        return {'label': f'{label_prefix} capable', 'palette_key': 'quality_capable'}
    if numeric > 1.33:
        return {'label': f'{label_prefix} good', 'palette_key': 'quality_good'}
    if numeric >= 1.0:
        return {'label': f'{label_prefix} marginal', 'palette_key': 'quality_marginal'}
    return {'label': f'{label_prefix} risk', 'palette_key': 'quality_risk'}


def classify_nok_severity(nok_pct):
    """Classify NOK ratio severity for chart title cueing."""
    ratio = 0.0
    try:
        ratio = float(nok_pct)
    except (TypeError, ValueError):
        ratio = 0.0

    if ratio <= 0.003:
        return {
            'label': 'NOK 0%',
            'palette_key': 'quality_capable',
        }

    if ratio <= 0.05:
        return {
            'label': f'NOK {ratio * 100:.1f}% watch',
            'palette_key': 'quality_marginal',
        }

    return {
        'label': f'NOK {ratio * 100:.1f}% high',
        'palette_key': 'quality_risk',
    }


def classify_normality_status(normality_status):
    """Map normality status to dedicated pastel normality palettes."""
    if normality_status == 'normal':
        return {'label': 'Normality normal', 'palette_key': 'normality_normal'}
    if normality_status == 'not_normal':
        return {'label': 'Normality not normal', 'palette_key': 'normality_not_normal'}
    if normality_status == 'not_applicable':
        return {'label': 'Normality not applicable', 'palette_key': 'normality_unknown'}
    return {'label': 'Normality unknown', 'palette_key': 'normality_unknown'}


def build_summary_panel_subtitle(summary_stats):
    """Return compact panel subtitle text showing sample size and NOK share."""
    return f"n={int(summary_stats['sample_size'])} • NOK={summary_stats['nok_pct'] * 100:.1f}%"


def build_summary_table_composition(summary_stats, histogram_table_payload):
    """Build a pure summary-table composition contract from stable summary stats."""

    capability_rows = histogram_table_payload['capability_rows']
    cpk_row_label = capability_rows['Cpk']['label']

    capability_badge = classify_capability_status(summary_stats['cp'], summary_stats['cpk'])
    capability_row_badges = {
        'Cp': classify_capability_value(
            capability_rows['Cp']['classification_value'],
            label_prefix=capability_rows['Cp']['label'],
        ),
        cpk_row_label: classify_capability_value(
            capability_rows['Cpk']['classification_value'],
            label_prefix=cpk_row_label,
        ),
    }

    histogram_row_badges = {
        **capability_row_badges,
        'Normality': classify_normality_status(summary_stats.get('normality_status')),
        'NOK %': classify_nok_severity(summary_stats.get('nok_pct')),
    }

    return {
        'capability_badge': capability_badge,
        'capability_row_badges': capability_row_badges,
        'histogram_row_badges': histogram_row_badges,
        'panel_subtitle': build_summary_panel_subtitle(summary_stats),
    }
