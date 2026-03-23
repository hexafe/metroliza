"""Helpers for workbook-level Group Analysis payload construction.

Metric payload rows emitted by :func:`build_group_analysis_payload` include an
optional ``chart_payload`` object intended for worksheet writers that render
embedded chart images.

``chart_payload`` keys:
* ``groups``: ordered list of ``{'group': str, 'values': list[float]}``
  containing finite numeric MEAS values per group.
* ``all_values``: flattened finite numeric values across all groups.
* ``spec_limits``: normalized ``{'lsl': float|None, 'nominal': float|None,
  'usl': float|None}`` limits for chart overlays.

These fields are additive and optional so existing consumers can ignore them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.characteristic_alias_service import resolve_characteristic_alias
from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats
from modules.export_grouping_utils import normalize_group_labels
from modules.distribution_shape_analysis import compute_distribution_difference
from modules.stats_utils import compute_capability_confidence_intervals, safe_process_capability

_SKIP_REASON_MESSAGES = {
    'forced_single_reference_scope_mismatch': (
        'Single-reference group analysis skipped: grouped rows span multiple references.'
    ),
    'forced_multi_reference_scope_mismatch': (
        'Multi-reference group analysis skipped: grouped rows span only one reference.'
    ),
    'insufficient_groups': 'Group Analysis skipped: at least 2 groups are required.',
    'missing_numeric_meas': 'Group Analysis skipped: no numeric MEAS values are available.',
    'no_eligible_metrics': 'Group Analysis skipped: no eligible metrics are available.',
}

_SPEC_STATUSES = ('EXACT_MATCH', 'LIMIT_MISMATCH', 'NOM_MISMATCH', 'INVALID_SPEC')
_SPEC_STATUS_LABELS = {
    'EXACT_MATCH': 'Exact match',
    'LIMIT_MISMATCH': 'Limits differ',
    'NOM_MISMATCH': 'Nominal differs',
    'INVALID_SPEC': 'Spec missing / Invalid spec.',
}

_PLOT_SKIP_REASON_MESSAGES = {
    'standard_only': 'Standard-level plotting is disabled for Light mode.',
    'metric_excluded': 'Metric is excluded from analysis by comparability policy.',
    'insufficient_groups': 'At least 2 groups with numeric data are required.',
    'low_group_samples': 'At least 3 numeric samples per group are required for violin plots.',
    'low_total_samples': 'At least 6 total numeric samples are required for histogram plots.',
    'eligible': 'Eligible',
}

_FLAG_LOW_N = 'LOW N'
_FLAG_IMBALANCED_N = 'IMBALANCED N'
_FLAG_SEVERELY_IMBALANCED_N = 'SEVERELY IMBALANCED N'
_FLAG_SPEC_QUESTION = 'SPEC?'


def _join_flags(flags):
    ordered_unique = []
    for flag in (_FLAG_LOW_N, _FLAG_SEVERELY_IMBALANCED_N, _FLAG_IMBALANCED_N, _FLAG_SPEC_QUESTION):
        if flag in flags and flag not in ordered_unique:
            ordered_unique.append(flag)
    return '; '.join(ordered_unique) if ordered_unique else 'none'


def _build_metric_level_flags(group_counts, *, spec_status):
    flags = []
    positive_counts = [int(count) for count in group_counts if int(count) > 0]
    if len(positive_counts) >= 2:
        ratio = max(positive_counts) / min(positive_counts)
        if ratio >= 3.0:
            flags.append(_FLAG_SEVERELY_IMBALANCED_N)
        elif ratio >= 2.0:
            flags.append(_FLAG_IMBALANCED_N)

    if str(spec_status or '').strip().upper() != 'EXACT_MATCH':
        flags.append(_FLAG_SPEC_QUESTION)
    return flags


def get_spec_status_label(spec_status):
    """Return user-facing spec status label for worksheets."""
    status = str(spec_status or '').strip().upper()
    return _SPEC_STATUS_LABELS.get(status, _SPEC_STATUS_LABELS['INVALID_SPEC'])


def _normalize_spec_status_key(value):
    status = str(value or '').strip().upper()
    return status if status in _SPEC_STATUS_LABELS else 'INVALID_SPEC'


def _status_to_skip_reason(status):
    mapping = {
        'EXACT_MATCH': '',
        'LIMIT_MISMATCH': 'limit_mismatch',
        'NOM_MISMATCH': 'nom_mismatch',
        'INVALID_SPEC': 'invalid_spec',
    }
    return mapping.get(_normalize_spec_status_key(status), 'invalid_spec')


def build_diagnostics_comment(*, include_metric, allow_pairwise, allow_capability, spec_status, pairwise_rows_count=0, skipped_reason=None):
    """Return explanatory diagnostics comment for analyzed or skipped metrics."""
    if skipped_reason:
        reason = str(skipped_reason).strip().lower()
        if reason == 'insufficient_groups':
            return 'Skipped: fewer than 2 groups have numeric data.'
        return f'Skipped: {reason.replace("_", " ")}.'

    status = _normalize_spec_status_key(spec_status)
    if not include_metric:
        return f'Skipped by policy for status: {get_spec_status_label(status)}.'
    if status == 'LIMIT_MISMATCH':
        return 'Analyzed with caution: limits differ across groups; pairwise comparison is allowed, capability metrics are disabled.'
    if status == 'NOM_MISMATCH':
        return 'Descriptive-only: nominal differs across groups; direct pairwise interpretation is disabled.'
    if status == 'INVALID_SPEC':
        return 'Descriptive-only: spec missing/invalid; capability metrics are disabled.'
    if pairwise_rows_count == 0:
        return 'Analyzed: exact match; pairwise enabled but no valid group pairs produced results.'
    if not allow_capability:
        return 'Analyzed with caution: exact match; capability metrics are disabled.'
    return 'Analyzed: exact match; pairwise and capability checks enabled.'


def _plot_skip_reason_message(reason):
    normalized = str(reason or '').strip().lower()
    return _PLOT_SKIP_REASON_MESSAGES.get(normalized, normalized.replace('_', ' '))


def _build_metric_plot_eligibility(*, grouped_values, analysis_level, include_metric):
    """Return conservative plot-eligibility metadata for worksheet layout and diagnostics."""
    normalized_level = str(analysis_level or 'light').strip().lower()
    if normalized_level != 'standard':
        return {
            'violin': {'eligible': False, 'skip_reason': 'standard_only'},
            'histogram': {'eligible': False, 'skip_reason': 'standard_only'},
        }

    if not include_metric:
        return {
            'violin': {'eligible': False, 'skip_reason': 'metric_excluded'},
            'histogram': {'eligible': False, 'skip_reason': 'metric_excluded'},
        }

    finite_counts = [int(np.isfinite(np.asarray(values, dtype=float)).sum()) for values in grouped_values.values()]
    populated_counts = [count for count in finite_counts if count > 0]
    if len(populated_counts) < 2:
        return {
            'violin': {'eligible': False, 'skip_reason': 'insufficient_groups'},
            'histogram': {'eligible': False, 'skip_reason': 'insufficient_groups'},
        }

    violin_skip_reason = '' if all(count >= 3 for count in populated_counts) else 'low_group_samples'
    histogram_skip_reason = '' if sum(populated_counts) >= 6 else 'low_total_samples'

    return {
        'violin': {'eligible': violin_skip_reason == '', 'skip_reason': violin_skip_reason},
        'histogram': {'eligible': histogram_skip_reason == '', 'skip_reason': histogram_skip_reason},
    }


def _round_display_value(value, *, precision=3):
    """Round numeric values for display payloads while preserving nulls."""
    if value is None:
        return None
    parsed = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
    if pd.isna(parsed):
        return None
    return round(float(parsed), precision)


def _round_display_value_adj_p(value):
    """Round adjusted p-values for display payloads."""
    return _round_display_value(value, precision=4)


def _build_metric_chart_payload(*, grouped_values, spec_payload):
    """Build optional chart-render payload from grouped numeric vectors."""
    groups = []
    all_values = []
    for group_name in sorted(grouped_values):
        arr = np.asarray(grouped_values[group_name], dtype=float)
        arr = arr[np.isfinite(arr)]
        group_values = arr.astype(float).tolist()
        groups.append({'group': group_name, 'values': group_values})
        all_values.extend(group_values)

    return {
        'groups': groups,
        'all_values': [float(value) for value in all_values],
        'spec_limits': {
            'lsl': spec_payload.get('lsl'),
            'nominal': spec_payload.get('nominal'),
            'usl': spec_payload.get('usl'),
        },
    }


def resolve_group_analysis_scope(requested_scope, reference_count):
    """Resolve effective Group Analysis scope from user selection and reference count."""
    normalized_scope = str(requested_scope or 'auto').strip().lower()
    if normalized_scope == 'auto':
        return 'single_reference' if int(reference_count or 0) <= 1 else 'multi_reference'
    return normalized_scope


def build_group_analysis_skip_reason(code, **context):
    """Return canonical skip-reason payload for message + diagnostics surfaces."""
    return {
        'code': code,
        'message': _SKIP_REASON_MESSAGES.get(code, 'Group Analysis skipped.'),
        'diagnostics': context,
    }


def normalize_metric_identity(metric_name, reference=None, *, scope='single_reference'):
    """Return a deterministic metric identity for diagnostics and analysis payloads."""
    normalized_metric = str(metric_name or '').strip()
    normalized_reference = str(reference or '').strip()
    normalized_scope = str(scope or 'single_reference').strip().lower()

    if normalized_scope == 'multi_reference':
        return f'{normalized_reference} :: {normalized_metric}' if normalized_reference else normalized_metric
    return normalized_metric


def _build_canonical_metric_series(frame):
    """Build canonical metric identities preferring HEADER-AX over HEADER-only labels."""
    index = getattr(frame, 'index', None)

    header_ax = pd.Series('', index=index, dtype=object)
    if 'HEADER - AX' in frame.columns:
        header_ax = frame['HEADER - AX'].fillna('').astype(str).str.strip()

    header = pd.Series('', index=index, dtype=object)
    if 'HEADER' in frame.columns:
        header = frame['HEADER'].fillna('').astype(str).str.strip()

    axis = pd.Series('', index=index, dtype=object)
    if 'AX' in frame.columns:
        axis = frame['AX'].fillna('').astype(str).str.strip()

    composed = pd.Series('', index=index, dtype=object)
    has_header_and_axis = (header != '') & (axis != '')
    composed.loc[has_header_and_axis] = header.loc[has_header_and_axis] + ' - ' + axis.loc[has_header_and_axis]
    composed.loc[(composed == '') & (header != '')] = header.loc[(composed == '') & (header != '')]

    canonical = header_ax.copy()
    canonical.loc[canonical == ''] = composed.loc[canonical == '']
    return canonical


def _resolve_canonical_metric_aliases(frame, canonical_metric_series, *, alias_db_path=None):
    """Resolve canonical metric identities with reference-aware alias mappings."""
    if alias_db_path is None:
        return canonical_metric_series

    resolved_metric_series = canonical_metric_series.fillna('').astype(str).str.strip().copy()
    reference_series = None
    if 'REFERENCE' in frame.columns:
        reference_series = frame['REFERENCE'].fillna('').astype(str).str.strip()

    for row_index, metric_name in resolved_metric_series.items():
        if not metric_name:
            continue
        reference_value = None
        if reference_series is not None:
            reference_value = reference_series.get(row_index) or None
        resolved_metric_series.at[row_index] = resolve_characteristic_alias(
            metric_name,
            reference_value,
            alias_db_path,
        )

    return resolved_metric_series


def normalize_spec_limits(lsl, nominal, usl, *, precision=3):
    """Normalize spec values to rounded numeric payload fields with explicit nulls."""

    def _to_rounded(value):
        if value is None:
            return None
        parsed = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
        if pd.isna(parsed):
            return None
        return round(float(parsed), precision)

    return {
        'lsl': _to_rounded(lsl),
        'nominal': _to_rounded(nominal),
        'usl': _to_rounded(usl),
    }


def classify_spec_status(spec_payload):
    """Classify normalized spec payload for diagnostics and skip narratives."""
    lsl = spec_payload.get('lsl')
    nominal = spec_payload.get('nominal')
    usl = spec_payload.get('usl')

    if lsl is None or nominal is None or usl is None:
        return 'INVALID_SPEC'
    if lsl > usl:
        return 'INVALID_SPEC'
    if not (lsl <= nominal <= usl):
        return 'INVALID_SPEC'
    return 'EXACT_MATCH'


def classify_metric_spec_status(metric_rows_df, spec_columns):
    """Classify a metric's cross-row spec comparability status."""
    normalized_specs = []
    for _, row in metric_rows_df.iterrows():
        normalized_specs.append(
            normalize_spec_limits(
                row[spec_columns['lsl']] if spec_columns['lsl'] else None,
                row[spec_columns['nominal']] if spec_columns['nominal'] else None,
                row[spec_columns['usl']] if spec_columns['usl'] else None,
            )
        )

    if not normalized_specs:
        return 'INVALID_SPEC', {'lsl': None, 'nominal': None, 'usl': None}

    if any(classify_spec_status(spec) == 'INVALID_SPEC' for spec in normalized_specs):
        return 'INVALID_SPEC', normalized_specs[0]

    unique_nominals = {spec['nominal'] for spec in normalized_specs}
    unique_limits = {(spec['lsl'], spec['usl']) for spec in normalized_specs}
    canonical_spec = normalized_specs[0]

    if len(unique_nominals) > 1:
        return 'NOM_MISMATCH', canonical_spec
    if len(unique_limits) > 1:
        return 'LIMIT_MISMATCH', canonical_spec
    return 'EXACT_MATCH', canonical_spec


def _resolve_analysis_policy(spec_status, analysis_level):
    """Resolve level-aware comparability behavior for a metric."""
    status = _normalize_spec_status_key(spec_status)
    shared_policy = {
        'EXACT_MATCH': {
            'include_metric': True,
            'allow_pairwise': True,
            'allow_capability': True,
        },
        'LIMIT_MISMATCH': {
            'include_metric': True,
            'allow_pairwise': True,
            'allow_capability': False,
        },
        'NOM_MISMATCH': {
            'include_metric': True,
            'allow_pairwise': False,
            'allow_capability': False,
        },
        'INVALID_SPEC': {
            'include_metric': True,
            'allow_pairwise': False,
            'allow_capability': False,
        },
    }
    return dict(shared_policy.get(status, shared_policy['INVALID_SPEC']))


def compute_group_descriptive_stats(grouped_values):
    """Build compact descriptive-stat rows from grouped numeric vectors."""
    rows = []
    for group_name in sorted(grouped_values):
        arr = np.asarray(grouped_values[group_name], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        rows.append(
            {
                'group': group_name,
                'n': int(arr.size),
                'mean': float(np.mean(arr)),
                'std': float(np.std(arr, ddof=1)) if arr.size > 1 else None,
                'min': float(np.min(arr)),
                'max': float(np.max(arr)),
            }
        )
    return rows


def _build_group_flags(row, metric_flags):
    """Return spec-aligned quality flags for a group descriptive row."""
    flags = []
    if int(row.get('n') or 0) < 5:
        flags.append(_FLAG_LOW_N)
    flags.extend(metric_flags)
    return _join_flags(flags)


def build_group_descriptive_rows(grouped_values, *, spec_payload, allow_capability, spec_status='EXACT_MATCH'):
    """Build final per-group rows with expanded statistics and capability columns."""
    base_rows = compute_group_descriptive_stats(grouped_values)
    output = []
    metric_flags = _build_metric_level_flags([row.get('n', 0) for row in base_rows], spec_status=spec_status)
    for row in base_rows:
        values = np.asarray(grouped_values.get(row['group'], []), dtype=float)
        values = values[np.isfinite(values)]
        q1, median, q3 = np.percentile(values, [25, 50, 75]) if values.size else (None, None, None)
        iqr = (float(q3) - float(q1)) if q1 is not None and q3 is not None else None
        capability = (
            compute_capability_payload(values, spec_payload)
            if allow_capability
            else {'cp': None, 'capability': None, 'capability_type': None}
        )

        raw_output_row = {
            'group': row.get('group'),
            'n': row.get('n'),
            'mean': row.get('mean'),
            'std': row.get('std'),
            'median': float(median) if median is not None else None,
            'iqr': iqr,
            'min': row.get('min'),
            'max': row.get('max'),
            'cp': capability.get('cp'),
            'capability': capability.get('capability'),
            'capability_type': capability.get('capability_type'),
        }
        raw_output_row['flags'] = _build_group_flags(raw_output_row, metric_flags)

        output_row = {
            'group': raw_output_row.get('group'),
            'n': raw_output_row.get('n'),
            'mean': _round_display_value(raw_output_row.get('mean')),
            'std': _round_display_value(raw_output_row.get('std')),
            'median': _round_display_value(raw_output_row.get('median')),
            'iqr': _round_display_value(raw_output_row.get('iqr')),
            'min': _round_display_value(raw_output_row.get('min')),
            'max': _round_display_value(raw_output_row.get('max')),
            'cp': _round_display_value(raw_output_row.get('cp')),
            'capability': _round_display_value(raw_output_row.get('capability')),
            'capability_type': raw_output_row.get('capability_type'),
            'flags': raw_output_row.get('flags'),
        }
        output.append(output_row)
    return output




def _safe_numeric(value):
    parsed = pd.to_numeric(pd.Series([value]), errors='coerce').iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _pairwise_practical_magnitude(effect_value):
    numeric_effect = _safe_numeric(effect_value)
    if numeric_effect is None:
        return 'unknown'

    absolute_effect = abs(numeric_effect)
    if absolute_effect < 0.2:
        return 'tiny'
    if absolute_effect < 0.5:
        return 'small'
    if absolute_effect < 0.8:
        return 'moderate'
    return 'large'


def _pairwise_takeaway(*, adjusted_p_value, effect_size, flags='none'):
    adjusted_p = _safe_numeric(adjusted_p_value)
    magnitude = _pairwise_practical_magnitude(effect_size)
    has_small_sample = _FLAG_LOW_N in str(flags or '')

    if adjusted_p is None:
        base = 'Statistical signal is incomplete, so treat this pair as unresolved.'
    elif adjusted_p <= 0.01:
        base = 'These groups differ clearly after correction.'
    elif adjusted_p <= 0.05:
        base = 'These groups show a reliable difference after correction.'
    else:
        base = 'There is not enough corrected evidence to call this a clear difference.'

    magnitude_text = {
        'tiny': 'The practical gap looks tiny.',
        'small': 'The practical gap looks small.',
        'moderate': 'The practical gap looks moderate.',
        'large': 'The practical gap looks large enough to matter.',
        'unknown': 'The practical gap was not reported clearly.',
    }[magnitude]

    if adjusted_p is not None and adjusted_p > 0.05 and magnitude in {'moderate', 'large'}:
        magnitude_text = 'The observed gap may matter, but the corrected evidence is still weak.'
    elif adjusted_p is not None and adjusted_p <= 0.05 and magnitude == 'tiny':
        magnitude_text = 'The result is statistically reliable, but the practical gap looks tiny.'

    if has_small_sample:
        magnitude_text += ' Low sample size means extra caution is needed.'
    return f'{base} {magnitude_text}'


def _pairwise_action(*, adjusted_p_value, effect_size, flags='none'):
    adjusted_p = _safe_numeric(adjusted_p_value)
    magnitude = _pairwise_practical_magnitude(effect_size)
    has_small_sample = _FLAG_LOW_N in str(flags or '')

    if has_small_sample:
        action = 'Verify with more data before changing the process.'
        if adjusted_p is not None and adjusted_p <= 0.05 and magnitude == 'large':
            action += ' This pair is still worth early investigation.'
        return action

    if adjusted_p is not None and adjusted_p <= 0.05 and magnitude == 'large':
        return 'Prioritize investigation; check setup, operator, tooling, or material differences.'
    if adjusted_p is not None and adjusted_p <= 0.05 and magnitude in {'moderate', 'small'}:
        return 'Review process differences, then confirm the gap matters operationally before changing settings.'
    if adjusted_p is not None and adjusted_p <= 0.05:
        return 'Keep monitoring; the signal is real but the practical gap looks small.'
    if magnitude in {'moderate', 'large'}:
        return 'Collect more data and verify before making a process change.'
    return 'No immediate action; continue monitoring.'


def _difference_status_label(*, adjusted_p_value, effect_size, flags='none'):
    adjusted_p = _safe_numeric(adjusted_p_value)
    magnitude = _pairwise_practical_magnitude(effect_size)
    flags_text = str(flags or '')

    if adjusted_p is not None and adjusted_p <= 0.05:
        return 'DIFFERENCE'
    if _FLAG_LOW_N in flags_text or _FLAG_SEVERELY_IMBALANCED_N in flags_text or _FLAG_IMBALANCED_N in flags_text:
        return 'USE CAUTION'
    if magnitude in {'moderate', 'large'}:
        return 'APPROXIMATE'
    return 'NO DIFFERENCE'


def _distribution_metric_note(distribution_difference):
    verdict = str((distribution_difference or {}).get('comment / verdict') or '').strip()
    if not verdict:
        return ''
    lowered = verdict.lower()
    if 'no statistically significant' in lowered:
        return 'Shape note: no clear distribution-shape difference after correction.'
    if 'statistically significant' in lowered or 'difference' in lowered:
        return 'Shape note: spread or pattern differs across groups, not just the average.'
    return f'Shape note: {verdict}'


def _recommended_metric_action(*, pairwise_rows, distribution_difference, analysis_policy):
    if not analysis_policy.get('allow_pairwise'):
        return 'Recommended action: use descriptive results only; direct pairwise interpretation is not supported for this metric.'

    significant_rows = [row for row in pairwise_rows if str(row.get('difference') or '').strip().upper() == 'YES']
    if significant_rows:
        ranked = sorted(
            significant_rows,
            key=lambda row: (
                _safe_numeric(row.get('adjusted_p_value')) is None,
                _safe_numeric(row.get('adjusted_p_value')) if _safe_numeric(row.get('adjusted_p_value')) is not None else float('inf'),
                -abs(_safe_numeric(row.get('effect_size')) or 0.0),
            ),
        )
        strongest = ranked[0]
        return (
            'Recommended action: start with '
            f"{strongest.get('group_a')} vs {strongest.get('group_b')} and verify likely process drivers before changing settings."
        )

    verdict = str((distribution_difference or {}).get('comment / verdict') or '').lower()
    if 'statistically significant' in verdict and 'no statistically significant' not in verdict:
        return 'Recommended action: averages may be similar, but review variation and consistency by group before changing the process.'

    return 'Recommended action: no immediate escalation; keep monitoring and collect more data if the gap still matters.'


def _metric_index_status(*, pairwise_rows, diagnostics_comment):
    labels = [
        _difference_status_label(
            adjusted_p_value=row.get('adjusted_p_value'),
            effect_size=row.get('effect_size'),
            flags=row.get('flags'),
        )
        for row in (pairwise_rows or [])
    ]
    if 'DIFFERENCE' in labels:
        return 'DIFFERENCE'
    if 'USE CAUTION' in labels or 'Descriptive-only' in str(diagnostics_comment or ''):
        return 'USE CAUTION'
    if 'APPROXIMATE' in labels:
        return 'APPROXIMATE'
    return 'NO DIFFERENCE'


def _metric_takeaway(*, pairwise_rows, diagnostics_comment, distribution_difference):
    if pairwise_rows:
        ranked = sorted(
            pairwise_rows,
            key=lambda row: (
                str(row.get('difference_label') or '') != 'DIFFERENCE',
                _safe_numeric(row.get('adjusted_p_value')) is None,
                _safe_numeric(row.get('adjusted_p_value')) if _safe_numeric(row.get('adjusted_p_value')) is not None else float('inf'),
            ),
        )
        best = ranked[0]
        summary = f"{best.get('group_a')} vs {best.get('group_b')}: {best.get('difference_label') or 'REVIEW'}."
        action = str(best.get('suggested_action') or '').strip()
        return f'{summary} {action}'.strip()

    shape_note = str((distribution_difference or {}).get('comment / verdict') or '').strip()
    if shape_note:
        return shape_note
    return str(diagnostics_comment or 'Review descriptive statistics only.').strip()

def _build_pairwise_test_rationale(*, group_count, test_used):
    test_name = str(test_used or '').strip().lower()
    if group_count <= 2:
        if 'mann-whitney' in test_name:
            return 'Chosen because only two groups are compared and a rank-based comparison is safer here.'
        if 'welch' in test_name:
            return 'Chosen because only two groups are compared and unequal-variance assumptions were safer.'
        if 'student' in test_name or 't-test' in test_name:
            return 'Chosen because only two groups are compared and the parametric assumptions were acceptable.'
        return 'Chosen because only two groups are compared.'
    if 'mann-whitney' in test_name:
        return 'Chosen because the data are better handled by a rank-based comparison.'
    if 'welch' in test_name:
        return 'Chosen because parametric assumptions were not reliable enough for a pooled-variance test.'
    if 'student' in test_name or 't-test' in test_name:
        return 'Chosen because the groups were suitable for a standard parametric comparison.'
    return 'Chosen to provide a consistent pairwise comparison across groups.'


def _resolve_pairwise_comment(*, pairwise_eligible, significant, flags):
    """Return standardized pairwise comment vocabulary for worksheet consumers."""
    if not pairwise_eligible:
        return 'DESCRIPTIVE ONLY'
    if flags and flags != 'none':
        return 'USE CAUTION'
    return 'DIFFERENCE' if significant else 'NO DIFFERENCE'


def build_pairwise_rows(
    metric_identity,
    grouped_values,
    *,
    alpha=0.05,
    correction_method='holm',
    pairwise_eligible=True,
    spec_status='EXACT_MATCH',
):
    """Build enriched pairwise A/B rows for worksheet output."""
    raw_rows = compute_pairwise_rows(
        metric_identity,
        grouped_values,
        alpha=alpha,
        correction_method=correction_method,
    )

    means = {
        group_name: float(np.mean(np.asarray(values, dtype=float)))
        for group_name, values in grouped_values.items()
        if np.asarray(values, dtype=float).size
    }

    counts_by_group = {
        group_name: int(np.isfinite(np.asarray(values, dtype=float)).sum())
        for group_name, values in grouped_values.items()
    }
    metric_flags = _build_metric_level_flags(counts_by_group.values(), spec_status=spec_status)

    output = []
    group_count = len(grouped_values)
    for row in raw_rows:
        group_a = row.get('group_a')
        group_b = row.get('group_b')
        delta_mean = None
        if group_a in means and group_b in means:
            delta_mean = _round_display_value(means[group_a] - means[group_b], precision=3)

        adj_p = row.get('adjusted_p_value')
        significant = bool(row.get('significant'))
        flags = []
        if int(counts_by_group.get(group_a, 0)) < 5 or int(counts_by_group.get(group_b, 0)) < 5:
            flags.append(_FLAG_LOW_N)
        flags.extend(metric_flags)
        flags_text = _join_flags(flags)
        difference = 'YES' if pairwise_eligible and significant else 'NO'
        comment = _resolve_pairwise_comment(
            pairwise_eligible=pairwise_eligible,
            significant=significant,
            flags=flags_text,
        )

        rounded_adj_p = _round_display_value_adj_p(adj_p)
        rounded_effect_size = _round_display_value(row.get('effect_size'))
        output.append(
            {
                'group_a': group_a,
                'group_b': group_b,
                'delta_mean': delta_mean,
                'adjusted_p_value': rounded_adj_p,
                'effect_size': rounded_effect_size,
                'difference': difference,
                'difference_label': _difference_status_label(
                    adjusted_p_value=rounded_adj_p,
                    effect_size=rounded_effect_size,
                    flags=flags_text,
                ),
                'comment': comment,
                'flags': flags_text,
                'metric': metric_identity,
                'p_value': row.get('p_value'),
                'test_used': row.get('test_used'),
                'test_rationale': _build_pairwise_test_rationale(group_count=group_count, test_used=row.get('test_used')),
                'takeaway': _pairwise_takeaway(adjusted_p_value=rounded_adj_p, effect_size=rounded_effect_size, flags=flags_text),
                'suggested_action': _pairwise_action(adjusted_p_value=rounded_adj_p, effect_size=rounded_effect_size, flags=flags_text),
            }
        )
    return output


def build_comparability_summary(spec_status, analysis_policy):
    """Build comparability/spec summary block for metric section rendering."""
    status = _normalize_spec_status_key(spec_status)
    interpretation_by_status = {
        'EXACT_MATCH': 'Specs are aligned across groups; direct capability and pairwise interpretation is valid.',
        'LIMIT_MISMATCH': 'Analyzed with caution: limits differ across groups; pairwise comparison is allowed, capability metrics are disabled.',
        'NOM_MISMATCH': 'Descriptive-only: nominal differs across groups; direct pairwise interpretation is disabled.',
        'INVALID_SPEC': 'Descriptive-only: spec missing/invalid; capability metrics are disabled.',
    }
    limitations = []
    if not analysis_policy.get('allow_pairwise'):
        limitations.append('pairwise disabled')
    if not analysis_policy.get('allow_capability'):
        limitations.append('capability disabled')

    return {
        'status': status,
        'interpretation_limits': '; '.join(limitations) if limitations else 'none',
        'summary': interpretation_by_status.get(status, 'Spec comparability could not be determined.'),
    }


def _build_analysis_restriction_fields(spec_status, analysis_policy):
    """Return stable worksheet labels/flags for metric index and overview rendering."""
    status = _normalize_spec_status_key(spec_status)
    pairwise_allowed = bool((analysis_policy or {}).get('allow_pairwise'))
    capability_allowed = bool((analysis_policy or {}).get('allow_capability'))
    restriction_label_by_status = {
        'EXACT_MATCH': 'Full analysis',
        'LIMIT_MISMATCH': 'Pairwise yes; capability off',
        'NOM_MISMATCH': 'Descriptive only',
        'INVALID_SPEC': 'Descriptive only',
    }
    return {
        'pairwise_allowed': pairwise_allowed,
        'capability_allowed': capability_allowed,
        'analysis_restriction_label': restriction_label_by_status.get(status, 'Descriptive only'),
    }


def build_metric_insights(metric_row):
    """Generate deterministic 1-3 line insight block for a metric."""
    desc_rows = metric_row.get('descriptive_stats', [])
    pairwise_rows = metric_row.get('pairwise_rows', [])
    comparability = metric_row.get('comparability_summary', {})

    required_lines = [
        (
            f"Comparability={comparability.get('status')} "
            f"(limits: {comparability.get('interpretation_limits', 'none')})."
        )
    ]
    optional_lines = []

    if desc_rows:
        sorted_by_mean = sorted(
            [row for row in desc_rows if row.get('mean') is not None],
            key=lambda row: row['mean'],
        )
        if sorted_by_mean:
            low = sorted_by_mean[0]
            high = sorted_by_mean[-1]
            optional_lines.append(
                (
                    f"Mean range spans {low.get('group')} ({low.get('mean'):.4g}) to "
                    f"{high.get('group')} ({high.get('mean'):.4g})."
                )
            )

    distribution_difference = metric_row.get('distribution_difference') or {}
    shape_verdict = distribution_difference.get('comment / verdict')

    if pairwise_rows:
        best = sorted(
            pairwise_rows,
            key=lambda row: (row.get('adjusted_p_value') is None, row.get('adjusted_p_value') or float('inf')),
        )[0]
        required_lines.append(
            (
                f"Strongest pairwise location signal: {best.get('group_a')} vs {best.get('group_b')} "
                f"(adj p={best.get('adjusted_p_value')}, comment={best.get('comment')})."
            )
        )
    elif metric_row.get('analysis_policy', {}).get('allow_pairwise'):
        required_lines.append('Pairwise location test enabled but no valid A/B rows were produced.')
    else:
        required_lines.append('Pairwise location interpretation is disabled for this metric.')

    if shape_verdict:
        required_lines.append(f"Distribution shape: {shape_verdict}")

    return (required_lines + optional_lines)[:3]


def compute_pairwise_rows(metric_identity, grouped_values, *, alpha=0.05, correction_method='holm'):
    """Build pairwise comparison rows for a single metric."""
    config = ComparisonStatsConfig(alpha=alpha, correction_method=correction_method)
    pairwise_rows = compute_metric_pairwise_stats(metric_identity, grouped_values, config=config)
    output = []
    group_count = len(grouped_values)
    for row in pairwise_rows:
        output.append(
            {
                'metric': metric_identity,
                'group_a': row.get('group_a'),
                'group_b': row.get('group_b'),
                'p_value': row.get('p_value'),
                'adjusted_p_value': row.get('adjusted_p_value'),
                'effect_size': row.get('effect_size'),
                'test_used': row.get('test_used'),
                'test_rationale': _build_pairwise_test_rationale(group_count=group_count, test_used=row.get('test_used')),
                'significant': row.get('significant'),
            }
        )
    return output


def compute_capability_payload(values, spec_payload):
    """Compute capability payload in a deterministic and nullable structure."""

    def _not_applicable_payload(*, status, sigma=None, mean_value=None, capability_mode=None):
        return {
            'cp': None,
            'capability': None,
            'capability_type': None,
            'cpk': None,
            'capability_ci': {'cp': None, 'cpk': None},
            'status': status,
            'sigma': sigma,
            'mean': mean_value,
            'capability_mode': capability_mode,
        }

    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return _not_applicable_payload(status='insufficient_data')

    sigma = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    mean_value = float(np.mean(arr))

    lsl = spec_payload.get('lsl')
    usl = spec_payload.get('usl')
    nominal = spec_payload.get('nominal')

    has_lsl = lsl is not None
    has_usl = usl is not None

    if has_lsl and has_usl:
        capability_mode = 'bilateral'
    elif has_usl:
        capability_mode = 'upper_only'
    elif has_lsl:
        capability_mode = 'lower_only'
    else:
        capability_mode = 'unusable'

    if capability_mode == 'unusable':
        return _not_applicable_payload(
            status='not_applicable',
            sigma=sigma,
            mean_value=mean_value,
            capability_mode=capability_mode,
        )

    if has_lsl and has_usl and lsl > usl:
        return _not_applicable_payload(
            status='not_applicable',
            sigma=sigma,
            mean_value=mean_value,
            capability_mode=capability_mode,
        )

    if sigma <= 0:
        return _not_applicable_payload(
            status='not_applicable',
            sigma=sigma,
            mean_value=mean_value,
            capability_mode=capability_mode,
        )

    if capability_mode == 'bilateral':
        cp, cpk = safe_process_capability(
            nominal,
            usl,
            lsl,
            sigma,
            mean_value,
        )
        cp_value = None if cp == 'N/A' else cp
        cpk_value = None if cpk == 'N/A' else cpk
        capability_type = 'Cpk'
    elif capability_mode == 'upper_only':
        cp_value = None
        cpk_value = (usl - mean_value) / (3.0 * sigma)
        capability_type = 'Cpk+'
    else:
        cp_value = None
        cpk_value = (mean_value - lsl) / (3.0 * sigma)
        capability_type = 'Cpk-'

    if cpk_value is None:
        return _not_applicable_payload(
            status='not_applicable',
            sigma=sigma,
            mean_value=mean_value,
            capability_mode=capability_mode,
        )

    capability_value = float(cpk_value)
    cpk_value = float(cpk_value)
    status = 'ok' if cp_value is not None or cpk_value is not None else 'not_applicable'
    capability_ci = compute_capability_confidence_intervals(
        sample_size=arr.size,
        cp=cp_value,
        cpk=cpk_value,
    )

    return {
        'cp': cp_value,
        'capability': capability_value,
        'capability_type': capability_type,
        'cpk': cpk_value,
        'capability_ci': capability_ci,
        'status': status,
        'sigma': sigma,
        'mean': mean_value,
        'capability_mode': capability_mode,
    }


def build_group_analysis_diagnostics_payload(
    *,
    effective_scope,
    requested_scope,
    requested_level,
    execution_status,
    reference_count,
    group_count,
    metric_rows,
    skipped_metrics,
    warning_summary,
    histogram_skip_summary,
    unmatched_metrics_summary,
    skip_reason=None,
):
    """Build diagnostics payload for worksheet rendering and debugging."""
    status_counts = {status: 0 for status in _SPEC_STATUSES}
    for row in metric_rows:
        status = str(row.get('spec_status') or '').upper()
        if status in status_counts:
            status_counts[status] += 1

    diagnostics_metric_rows = []
    for metric_row in metric_rows:
        spec_status = _normalize_spec_status_key(metric_row.get('spec_status'))
        policy = metric_row.get('analysis_policy') or {}
        diagnostics_metric_rows.append(
            {
                'metric': metric_row.get('metric'),
                'groups': metric_row.get('group_count'),
                'spec_status': spec_status,
                'spec_status_label': get_spec_status_label(spec_status),
                'pairwise_comparisons': len(metric_row.get('pairwise_rows', []) or []),
                'included_in_light': 'YES' if _resolve_analysis_policy(spec_status, 'light').get('include_metric') else 'NO',
                'included_in_standard': 'YES' if _resolve_analysis_policy(spec_status, 'standard').get('include_metric') else 'NO',
                'comment': metric_row.get('diagnostics_comment')
                or build_diagnostics_comment(
                    include_metric=policy.get('include_metric', True),
                    allow_pairwise=policy.get('allow_pairwise', False),
                    allow_capability=policy.get('allow_capability', False),
                    spec_status=spec_status,
                    pairwise_rows_count=len(metric_row.get('pairwise_rows', []) or []),
                ),
            }
        )

    for skipped in skipped_metrics:
        reason = str(skipped.get('reason') or '').strip().lower()
        if reason in {'nom_mismatch', 'limit_mismatch', 'invalid_spec'}:
            spec_status = _normalize_spec_status_key(reason)
        else:
            spec_status = 'INVALID_SPEC'
        diagnostics_metric_rows.append(
            {
                'metric': skipped.get('metric'),
                'groups': skipped.get('group_count'),
                'spec_status': spec_status,
                'spec_status_label': get_spec_status_label(spec_status),
                'pairwise_comparisons': 0,
                'included_in_light': 'NO' if reason == 'insufficient_groups' else ('YES' if _resolve_analysis_policy(spec_status, 'light').get('include_metric') else 'NO'),
                'included_in_standard': 'NO',
                'comment': build_diagnostics_comment(
                    include_metric=False,
                    allow_pairwise=False,
                    allow_capability=False,
                    spec_status=spec_status,
                    skipped_reason=reason or _status_to_skip_reason(spec_status),
                ),
            }
        )

    return {
        'requested_scope': str(requested_scope or 'auto').strip().lower(),
        'requested_level': str(requested_level or 'light').strip().lower(),
        'execution_status': str(execution_status or 'skipped').strip().lower(),
        'effective_scope': effective_scope,
        'reference_count': int(reference_count),
        'group_count': int(group_count),
        'metric_count': len(metric_rows),
        'skipped_metric_count': len(skipped_metrics),
        'status_counts': status_counts,
        'warning_summary': warning_summary,
        'histogram_skip_summary': histogram_skip_summary,
        'unmatched_metrics_summary': unmatched_metrics_summary,
        'skip_reason': skip_reason,
        'metrics': metric_rows,
        'skipped_metrics': skipped_metrics,
        'metric_diagnostics_rows': diagnostics_metric_rows,
    }


def _build_warning_summary(metric_rows, skipped_metrics):
    warning_messages = []
    warning_counts = {}

    for metric_row in sorted(metric_rows, key=lambda row: str(row.get('metric') or '')):
        interpretation_limits = str(metric_row.get('comparability_summary', {}).get('interpretation_limits') or 'none')
        if interpretation_limits != 'none':
            warning_messages.append(f"{metric_row.get('metric')}: {interpretation_limits}")
        metric_flags = str(metric_row.get('metric_flags') or 'none')
        if metric_flags != 'none':
            warning_messages.append(f"{metric_row.get('metric')}: {metric_flags}")

    for skipped in sorted(skipped_metrics, key=lambda row: str(row.get('metric') or '')):
        reason = str(skipped.get('reason') or 'unknown')
        warning_counts[reason] = warning_counts.get(reason, 0) + 1

    return {
        'count': len(warning_messages) + len(skipped_metrics),
        'messages': warning_messages,
        'skip_reason_counts': dict(sorted(warning_counts.items())),
    }


def _build_histogram_skip_summary(*, analysis_level, metric_rows, skipped_metrics):
    normalized_level = str(analysis_level or 'light').strip().lower()
    if normalized_level != 'standard':
        return {
            'applies': False,
            'count': 0,
            'reason_counts': {},
        }

    reason_counts = {}
    total_count = 0

    for metric_row in metric_rows:
        histogram_meta = ((metric_row.get('plot_eligibility') or {}).get('histogram') or {})
        if bool(histogram_meta.get('eligible')):
            continue
        reason = str(histogram_meta.get('skip_reason') or 'unknown')
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        total_count += 1

    for skipped in skipped_metrics:
        reason = str(skipped.get('reason') or 'unknown')
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        total_count += 1

    return {
        'applies': True,
        'count': total_count,
        'reason_counts': dict(sorted(reason_counts.items())),
    }


def _build_unmatched_metrics_summary(metric_frame, *, metric_column, reference_column):
    if reference_column is None or reference_column not in metric_frame.columns:
        return {'count': 0, 'metrics': []}

    expected_references = sorted(
        {
            str(reference).strip()
            for reference in metric_frame[reference_column].dropna().astype(str)
            if str(reference).strip()
        }
    )
    if not expected_references:
        return {'count': 0, 'metrics': []}

    unmatched_metrics = []
    for metric_name, metric_subset in metric_frame.groupby(metric_column, sort=True):
        present_references = sorted(
            {
                str(reference).strip()
                for reference in metric_subset[reference_column].dropna().astype(str)
                if str(reference).strip()
            }
        )
        missing_references = [reference for reference in expected_references if reference not in present_references]
        if missing_references:
            unmatched_metrics.append(
                {
                    'metric': str(metric_name),
                    'present_references': present_references,
                    'missing_references': missing_references,
                }
            )

    return {'count': len(unmatched_metrics), 'metrics': unmatched_metrics}


def _normalize_grouped_working_df(grouped_df, *, alias_db_path=None):
    working = grouped_df.copy()
    if 'GROUP' not in working.columns:
        working['GROUP'] = 'POPULATION'
    working['GROUP'] = normalize_group_labels(working['GROUP'], missing_label='POPULATION', normalize_blank=True)
    working['MEAS'] = pd.to_numeric(working.get('MEAS'), errors='coerce')

    canonical_metric_series = _build_canonical_metric_series(working)
    working['__canonical_metric__'] = _resolve_canonical_metric_aliases(
        working,
        canonical_metric_series,
        alias_db_path=alias_db_path,
    )

    if 'NOMINAL' not in working.columns and 'NOM' in working.columns:
        working['NOMINAL'] = pd.to_numeric(working.get('NOM'), errors='coerce')
    elif 'NOMINAL' in working.columns:
        working['NOMINAL'] = pd.to_numeric(working.get('NOMINAL'), errors='coerce')

    if 'USL' not in working.columns and {'NOM', '+TOL'}.issubset(set(working.columns)):
        working['USL'] = pd.to_numeric(working.get('NOM'), errors='coerce') + pd.to_numeric(working.get('+TOL'), errors='coerce')
    elif 'USL' in working.columns:
        working['USL'] = pd.to_numeric(working.get('USL'), errors='coerce')

    if 'LSL' not in working.columns and {'NOM', '-TOL'}.issubset(set(working.columns)):
        working['LSL'] = pd.to_numeric(working.get('NOM'), errors='coerce') + pd.to_numeric(working.get('-TOL'), errors='coerce')
    elif 'LSL' in working.columns:
        working['LSL'] = pd.to_numeric(working.get('LSL'), errors='coerce')

    return working.dropna(subset=['MEAS'])


def evaluate_group_analysis_readiness(grouped_df, *, requested_scope='auto', eligible_metrics=None, alias_db_path=None):
    """Check minimum runnable conditions and return skip metadata when unmet."""
    if not isinstance(grouped_df, pd.DataFrame):
        grouped_df = pd.DataFrame()

    reference_count = int(grouped_df.get('REFERENCE', pd.Series(dtype=object)).dropna().nunique())
    effective_scope = resolve_group_analysis_scope(requested_scope, reference_count)
    forced_scope = str(requested_scope or 'auto').strip().lower()

    if forced_scope == 'single_reference' and reference_count > 1:
        return {
            'runnable': False,
            'effective_scope': effective_scope,
            'skip_reason': build_group_analysis_skip_reason(
                'forced_single_reference_scope_mismatch',
                requested_scope=forced_scope,
                effective_scope=effective_scope,
                reference_count=reference_count,
            ),
        }

    if forced_scope == 'multi_reference' and reference_count <= 1:
        return {
            'runnable': False,
            'effective_scope': effective_scope,
            'skip_reason': build_group_analysis_skip_reason(
                'forced_multi_reference_scope_mismatch',
                requested_scope=forced_scope,
                effective_scope=effective_scope,
                reference_count=reference_count,
            ),
        }

    working = _normalize_grouped_working_df(grouped_df, alias_db_path=alias_db_path)

    if working.empty:
        return {
            'runnable': False,
            'effective_scope': effective_scope,
            'skip_reason': build_group_analysis_skip_reason('missing_numeric_meas'),
        }

    group_count = int(working['GROUP'].nunique())
    if group_count < 2:
        return {
            'runnable': False,
            'effective_scope': effective_scope,
            'skip_reason': build_group_analysis_skip_reason('insufficient_groups', group_count=group_count),
        }

    metric_column = '__canonical_metric__'
    if metric_column in working.columns:
        metric_series = working[metric_column].fillna('').astype(str).str.strip()
        if eligible_metrics is not None:
            allowed = {str(value).strip() for value in eligible_metrics if str(value).strip()}
            metric_series = metric_series[metric_series.isin(allowed)]
        eligible_metric_count = int((metric_series != '').sum())
    else:
        eligible_metric_count = 0

    if eligible_metric_count == 0:
        return {
            'runnable': False,
            'effective_scope': effective_scope,
            'skip_reason': build_group_analysis_skip_reason('no_eligible_metrics'),
        }

    return {
        'runnable': True,
        'effective_scope': effective_scope,
        'skip_reason': None,
    }


def build_group_analysis_payload(
    grouped_df,
    *,
    requested_scope='auto',
    eligible_metrics=None,
    alpha=0.05,
    correction_method='holm',
    analysis_level='light',
    alias_db_path=None,
):
    """Assemble metric-level Group Analysis payload for writer modules."""
    if not isinstance(grouped_df, pd.DataFrame):
        grouped_df = pd.DataFrame()

    readiness = evaluate_group_analysis_readiness(
        grouped_df,
        requested_scope=requested_scope,
        eligible_metrics=eligible_metrics,
        alias_db_path=alias_db_path,
    )
    reference_count = int(grouped_df.get('REFERENCE', pd.Series(dtype=object)).dropna().nunique())
    effective_scope = readiness['effective_scope']
    normalized_level = str(analysis_level or 'light').strip().lower()

    if isinstance(grouped_df, pd.DataFrame) and 'GROUP' in grouped_df.columns:
        grouped_series = normalize_group_labels(grouped_df['GROUP'], missing_label='POPULATION', normalize_blank=True)
        group_count = int(grouped_series.dropna().nunique())
    else:
        group_count = 0

    if not readiness['runnable']:
        diagnostics = build_group_analysis_diagnostics_payload(
            effective_scope=effective_scope,
            requested_scope=requested_scope,
            requested_level=normalized_level,
            execution_status='skipped',
            reference_count=reference_count,
            group_count=group_count,
            metric_rows=[],
            skipped_metrics=[],
            warning_summary={'count': 0, 'messages': [], 'skip_reason_counts': {}},
            histogram_skip_summary={'applies': normalized_level == 'standard', 'count': 0, 'reason_counts': {}},
            unmatched_metrics_summary={'count': 0, 'metrics': []},
            skip_reason=readiness['skip_reason'],
        )
        return {
            'status': 'skipped',
            'analysis_level': normalized_level,
            'readiness': readiness,
            'effective_scope': effective_scope,
            'skip_reason': readiness['skip_reason'],
            'metric_rows': [],
            'diagnostics': diagnostics,
        }

    working = _normalize_grouped_working_df(grouped_df, alias_db_path=alias_db_path)
    metric_column = '__canonical_metric__'
    reference_column = 'REFERENCE' if 'REFERENCE' in working.columns else None
    spec_columns = {
        'lsl': 'LSL' if 'LSL' in working.columns else None,
        'nominal': 'NOMINAL' if 'NOMINAL' in working.columns else None,
        'usl': 'USL' if 'USL' in working.columns else None,
    }

    metrics = []
    skipped_metrics = []
    metric_frame = working.copy()
    metric_frame[metric_column] = metric_frame[metric_column].fillna('').astype(str).str.strip()
    metric_frame = metric_frame[metric_frame[metric_column] != '']

    if eligible_metrics is not None:
        allowed = {str(value).strip() for value in eligible_metrics if str(value).strip()}
        metric_frame = metric_frame[metric_frame[metric_column].isin(allowed)]

    group_count = int(metric_frame.get('GROUP', pd.Series(dtype=object)).dropna().nunique())
    unmatched_metrics_summary = _build_unmatched_metrics_summary(
        metric_frame,
        metric_column=metric_column,
        reference_column=reference_column,
    )

    grouping_columns = [metric_column]
    if effective_scope == 'multi_reference' and reference_column is not None:
        grouping_columns.append(reference_column)

    for key_tuple, metric_rows_df in metric_frame.groupby(grouping_columns, dropna=False, sort=True):
        if not isinstance(key_tuple, tuple):
            key_tuple = (key_tuple,)
        metric_name = key_tuple[0]
        reference_value = key_tuple[1] if len(key_tuple) > 1 else None
        metric_identity = normalize_metric_identity(metric_name, reference_value, scope=effective_scope)

        grouped_values = {
            group_name: group_df['MEAS'].to_numpy(dtype=float)
            for group_name, group_df in metric_rows_df.groupby('GROUP', sort=True)
        }
        populated_groups = [name for name, values in grouped_values.items() if np.isfinite(values).sum() > 0]
        if len(populated_groups) < 2:
            skipped_metrics.append({'metric': metric_identity, 'reason': 'insufficient_groups', 'group_count': len(populated_groups)})
            continue

        spec_status, spec_payload = classify_metric_spec_status(metric_rows_df, spec_columns)
        policy = _resolve_analysis_policy(spec_status, analysis_level)
        if not policy['include_metric']:
            skipped_metrics.append({'metric': metric_identity, 'reason': spec_status.lower(), 'group_count': len(populated_groups)})
            continue

        descriptive_stats = build_group_descriptive_rows(
            grouped_values,
            spec_payload=spec_payload,
            allow_capability=policy['allow_capability'],
            spec_status=spec_status,
        )
        all_metric_values = np.concatenate([np.asarray(values, dtype=float) for values in grouped_values.values()])
        capability = (
            compute_capability_payload(all_metric_values, spec_payload)
            if policy['allow_capability']
            else {
                'cp': None,
                'capability': None,
                'capability_type': None,
                'cpk': None,
                'status': 'not_applicable',
                'sigma': float(np.std(all_metric_values, ddof=1)) if all_metric_values.size > 1 else 0.0,
                'mean': float(np.mean(all_metric_values)) if all_metric_values.size else None,
            }
        )
        pairwise_rows = (
            build_pairwise_rows(
                metric_identity,
                grouped_values,
                alpha=alpha,
                correction_method=correction_method,
                spec_status=spec_status,
            )
            if policy['allow_pairwise']
            else []
        )

        metric_level_flags = _join_flags(_build_metric_level_flags((row.get('n', 0) for row in descriptive_stats), spec_status=spec_status))

        comparability_summary = build_comparability_summary(spec_status, policy)
        restriction_fields = _build_analysis_restriction_fields(spec_status, policy)
        plot_eligibility = _build_metric_plot_eligibility(
            grouped_values=grouped_values,
            analysis_level=normalized_level,
            include_metric=policy.get('include_metric', True),
        )

        diagnostics_comment = build_diagnostics_comment(
            include_metric=policy.get('include_metric', True),
            allow_pairwise=policy.get('allow_pairwise', False),
            allow_capability=policy.get('allow_capability', False),
            spec_status=spec_status,
            pairwise_rows_count=len(pairwise_rows),
        )
        histogram_meta = plot_eligibility.get('histogram') or {}
        if normalized_level == 'standard' and not bool(histogram_meta.get('eligible')):
            diagnostics_comment = (
                f"{diagnostics_comment} Histogram omitted: {_plot_skip_reason_message(histogram_meta.get('skip_reason'))}."
            )

        distribution_analysis = compute_distribution_difference(
            metric_identity,
            grouped_values,
            alpha=alpha,
            correction_method=correction_method,
        )
        profile_by_group = {
            row.get('Group'): row
            for row in distribution_analysis.get('profile_rows', [])
        }
        for desc_row in descriptive_stats:
            group_profile = profile_by_group.get(desc_row.get('group')) or {}
            desc_row['best_fit_model'] = group_profile.get('best fit model') or group_profile.get('Best fit model')
            desc_row['fit_quality'] = group_profile.get('fit quality') or group_profile.get('Fit quality')
            desc_row['distribution_shape_caution'] = group_profile.get('Warning / notes summary')

        distribution_omnibus = distribution_analysis.get('omnibus_row')
        metrics.append(
            {
                'metric': metric_identity,
                'reference': reference_value,
                'group_count': len(populated_groups),
                'descriptive_stats': descriptive_stats,
                'pairwise_rows': pairwise_rows,
                'distribution_difference': distribution_omnibus,
                'distribution_pairwise_rows': distribution_analysis.get('pairwise_rows', []),
                'spec': spec_payload,
                'spec_status': spec_status,
                'spec_status_label': get_spec_status_label(spec_status),
                'analysis_policy': policy,
                'pairwise_allowed': restriction_fields['pairwise_allowed'],
                'capability_allowed': restriction_fields['capability_allowed'],
                'analysis_restriction_label': restriction_fields['analysis_restriction_label'],
                'capability': capability,
                'comparability_summary': comparability_summary,
                'plot_eligibility': plot_eligibility,
                'chart_payload': _build_metric_chart_payload(
                    grouped_values=grouped_values,
                    spec_payload=spec_payload,
                ),
                'diagnostics_comment': diagnostics_comment,
                'metric_flags': metric_level_flags,
                'metric_note': _distribution_metric_note(distribution_omnibus),
                'recommended_action': _recommended_metric_action(
                    pairwise_rows=pairwise_rows,
                    distribution_difference=distribution_omnibus,
                    analysis_policy=policy,
                ),
            }
        )
        metrics[-1]['index_status'] = _metric_index_status(
            pairwise_rows=pairwise_rows,
            diagnostics_comment=diagnostics_comment,
        )
        if not policy.get('allow_pairwise') and metrics[-1]['index_status'] == 'NO DIFFERENCE':
            metrics[-1]['index_status'] = 'USE CAUTION'
        metrics[-1]['metric_takeaway'] = _metric_takeaway(
            pairwise_rows=pairwise_rows,
            diagnostics_comment=diagnostics_comment,
            distribution_difference=distribution_omnibus,
        )
        metrics[-1]['insights'] = build_metric_insights(metrics[-1])

    diagnostics = build_group_analysis_diagnostics_payload(
        effective_scope=effective_scope,
        requested_scope=requested_scope,
        requested_level=normalized_level,
        execution_status='ran',
        reference_count=reference_count,
        group_count=group_count,
        metric_rows=metrics,
        skipped_metrics=skipped_metrics,
        warning_summary=_build_warning_summary(metrics, skipped_metrics),
        histogram_skip_summary=_build_histogram_skip_summary(
            analysis_level=normalized_level,
            metric_rows=metrics,
            skipped_metrics=skipped_metrics,
        ),
        unmatched_metrics_summary=unmatched_metrics_summary,
    )

    return {
        'status': 'ready',
        'analysis_level': normalized_level,
        'readiness': readiness,
        'effective_scope': effective_scope,
        'skip_reason': None,
        'metric_rows': metrics,
        'diagnostics': diagnostics,
    }
