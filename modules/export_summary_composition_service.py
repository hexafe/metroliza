"""Pure summary-sheet composition helpers for exporter rendering flows."""

from modules.summary_plot_palette import STATUS_ICON_PREFIX_BY_PALETTE


def _with_status_prefix(label, palette_key):
    prefix = STATUS_ICON_PREFIX_BY_PALETTE.get(palette_key)
    if not prefix:
        return label
    return f'{prefix} {label}'


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
            'label': _with_status_prefix('Cp/Cpk N/A', 'quality_unknown'),
            'palette_key': 'quality_unknown',
        }

    if cpk_value >= 1.67 and cp_value >= 1.67:
        return {
            'label': _with_status_prefix('Cp/Cpk capable', 'quality_capable'),
            'palette_key': 'quality_capable',
        }

    if cpk_value > 1.33 and cp_value > 1.33:
        return {
            'label': _with_status_prefix('Cp/Cpk good', 'quality_good'),
            'palette_key': 'quality_good',
        }

    if cpk_value >= 1.0 and cp_value >= 1.0:
        return {
            'label': _with_status_prefix('Cp/Cpk marginal', 'quality_marginal'),
            'palette_key': 'quality_marginal',
        }

    return {
        'label': _with_status_prefix('Cp/Cpk risk', 'quality_risk'),
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
        return {'label': _with_status_prefix(f'{label_prefix} N/A', 'quality_unknown'), 'palette_key': 'quality_unknown'}
    if numeric >= 1.67:
        return {'label': _with_status_prefix(f'{label_prefix} capable', 'quality_capable'), 'palette_key': 'quality_capable'}
    if numeric > 1.33:
        return {'label': _with_status_prefix(f'{label_prefix} good', 'quality_good'), 'palette_key': 'quality_good'}
    if numeric >= 1.0:
        return {'label': _with_status_prefix(f'{label_prefix} marginal', 'quality_marginal'), 'palette_key': 'quality_marginal'}
    return {'label': _with_status_prefix(f'{label_prefix} risk', 'quality_risk'), 'palette_key': 'quality_risk'}


def classify_nok_severity(nok_pct):
    """Classify NOK ratio severity for chart title cueing."""
    ratio = 0.0
    try:
        ratio = float(nok_pct)
    except (TypeError, ValueError):
        ratio = 0.0

    if ratio <= 0.003:
        return {
            'label': _with_status_prefix('NOK 0%', 'quality_capable'),
            'palette_key': 'quality_capable',
        }

    if ratio <= 0.05:
        return {
            'label': _with_status_prefix(f'NOK {ratio * 100:.1f}% watch', 'quality_marginal'),
            'palette_key': 'quality_marginal',
        }

    return {
        'label': _with_status_prefix(f'NOK {ratio * 100:.1f}% high', 'quality_risk'),
        'palette_key': 'quality_risk',
    }




def classify_nok_discrepancy_status(discrepancy_abs, *, threshold_abs=0.02):
    """Classify observed-vs-estimated NOK discrepancy severity."""
    try:
        abs_value = float(discrepancy_abs)
    except (TypeError, ValueError):
        return {'label': _with_status_prefix('NOK discrepancy N/A', 'quality_unknown'), 'palette_key': 'quality_unknown'}

    threshold = float(threshold_abs)
    if abs_value > threshold:
        return {'label': _with_status_prefix(f'NOK discrepancy {abs_value * 100:.2f}pp high', 'quality_risk'), 'palette_key': 'quality_risk'}
    if abs_value > (threshold * 0.5):
        return {'label': _with_status_prefix(f'NOK discrepancy {abs_value * 100:.2f}pp watch', 'quality_marginal'), 'palette_key': 'quality_marginal'}
    return {'label': _with_status_prefix(f'NOK discrepancy {abs_value * 100:.2f}pp low', 'quality_capable'), 'palette_key': 'quality_capable'}

def classify_normality_status(normality_status):
    """Map normality status to dedicated pastel normality palettes."""
    if normality_status == 'normal':
        return {'label': _with_status_prefix('Normality normal', 'normality_normal'), 'palette_key': 'normality_normal'}
    if normality_status == 'not_normal':
        return {'label': _with_status_prefix('Normality not normal', 'normality_not_normal'), 'palette_key': 'normality_not_normal'}
    if normality_status == 'not_applicable':
        return {'label': _with_status_prefix('Normality not applicable', 'normality_unknown'), 'palette_key': 'normality_unknown'}
    return {'label': _with_status_prefix('Normality unknown', 'normality_unknown'), 'palette_key': 'normality_unknown'}


def build_summary_panel_subtitle(summary_stats):
    """Return compact panel subtitle text showing sample size and NOK share."""
    return f"n={int(summary_stats['sample_size'])} • NOK={summary_stats['nok_pct'] * 100:.1f}%"


def build_summary_table_composition(summary_stats, histogram_table_payload):
    """Build a pure summary-table composition contract from stable summary stats."""

    capability_rows = histogram_table_payload['capability_rows']
    cpk_row_label = capability_rows['Cpk']['label']
    cp_row_label = capability_rows['Cp']['label']
    sample_confidence = histogram_table_payload.get('sample_confidence') or {}

    capability_badge = classify_capability_status(summary_stats['cp'], summary_stats['cpk'])
    capability_row_badges = {
        cp_row_label: classify_capability_value(
            capability_rows['Cp']['classification_value'],
            label_prefix=cp_row_label,
        ),
        cpk_row_label: classify_capability_value(
            capability_rows['Cpk']['classification_value'],
            label_prefix=cpk_row_label,
        ),
    }

    summary_metrics = histogram_table_payload.get('summary_metrics') or {}
    histogram_row_badges = {
        **capability_row_badges,
        'Normality': classify_normality_status(summary_stats.get('normality_status')),
        'NOK %': classify_nok_severity(summary_stats.get('nok_pct')),
        'NOK % Δ (abs/rel)': classify_nok_discrepancy_status(
            summary_metrics.get('nok_pct_abs_diff'),
            threshold_abs=summary_metrics.get('nok_pct_discrepancy_threshold', 0.02),
        ),
    }

    if sample_confidence.get('is_low_n'):
        severity = sample_confidence.get('severity')
        sample_badge_palette = 'quality_risk' if severity == 'severe' else 'quality_marginal'
        capability_badge = {
            'label': _with_status_prefix('Capability low confidence', 'quality_unknown'),
            'palette_key': 'quality_unknown',
        }
        histogram_row_badges[cp_row_label] = {
            'label': _with_status_prefix('Low-confidence estimate', sample_badge_palette),
            'palette_key': sample_badge_palette,
        }
        histogram_row_badges[cpk_row_label] = {
            'label': _with_status_prefix('Low-confidence estimate', sample_badge_palette),
            'palette_key': sample_badge_palette,
        }
        histogram_row_badges['Samples'] = {
            'label': _with_status_prefix('Low sample size', sample_badge_palette),
            'palette_key': sample_badge_palette,
        }

    return {
        'capability_badge': capability_badge,
        'capability_row_badges': capability_row_badges,
        'histogram_row_badges': histogram_row_badges,
        'panel_subtitle': build_summary_panel_subtitle(summary_stats),
    }
