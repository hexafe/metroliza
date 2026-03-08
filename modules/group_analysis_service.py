"""Helpers for workbook-level Group Analysis payload construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats
from modules.export_grouping_utils import normalize_group_labels
from modules.stats_utils import safe_process_capability

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
    normalized_level = str(analysis_level or 'light').strip().lower()
    if normalized_level == 'standard':
        return {
            'include_metric': spec_status == 'EXACT_MATCH',
            'allow_pairwise': spec_status == 'EXACT_MATCH',
            'allow_capability': spec_status == 'EXACT_MATCH',
        }

    return {
        'include_metric': True,
        'allow_pairwise': spec_status in {'EXACT_MATCH', 'LIMIT_MISMATCH'},
        'allow_capability': spec_status == 'EXACT_MATCH',
    }


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


def _build_group_flags(row, spec_payload):
    """Return deterministic quality flags for a group descriptive row."""
    flags = []
    if int(row.get('n') or 0) < 3:
        flags.append('low_n')

    std_value = row.get('std')
    if std_value is not None and float(std_value) == 0.0:
        flags.append('zero_variance')

    lsl = spec_payload.get('lsl')
    usl = spec_payload.get('usl')
    mean_value = row.get('mean')
    if mean_value is not None and lsl is not None and usl is not None and not (lsl <= mean_value <= usl):
        flags.append('mean_outside_limits')

    if row.get('cp') is None and row.get('capability') is None:
        flags.append('capability_unavailable')

    return '; '.join(flags) if flags else 'none'


def build_group_descriptive_rows(grouped_values, *, spec_payload, allow_capability):
    """Build final per-group rows with expanded statistics and capability columns."""
    base_rows = compute_group_descriptive_stats(grouped_values)
    output = []
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

        output_row = {
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
        output_row['flags'] = _build_group_flags(output_row, spec_payload)
        output.append(output_row)
    return output


def build_pairwise_rows(metric_identity, grouped_values, *, alpha=0.05, correction_method='holm'):
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

    output = []
    for row in raw_rows:
        group_a = row.get('group_a')
        group_b = row.get('group_b')
        delta_mean = None
        if group_a in means and group_b in means:
            delta_mean = means[group_a] - means[group_b]

        adj_p = row.get('adjusted_p_value')
        significant = bool(row.get('significant'))
        verdict = 'different' if significant else 'no_evidence_of_difference'
        flags = []
        if adj_p is None:
            flags.append('missing_adjusted_p')
        if row.get('effect_size') is None:
            flags.append('missing_effect_size')

        output.append(
            {
                'group_a': group_a,
                'group_b': group_b,
                'delta_mean': delta_mean,
                'adjusted_p_value': adj_p,
                'effect_size': row.get('effect_size'),
                'verdict': verdict,
                'flags': '; '.join(flags) if flags else 'none',
                'metric': metric_identity,
                'p_value': row.get('p_value'),
                'test_used': row.get('test_used'),
                'significant': significant,
            }
        )
    return output


def build_comparability_summary(spec_status, analysis_policy):
    """Build comparability/spec summary block for metric section rendering."""
    interpretation_by_status = {
        'EXACT_MATCH': 'Specs are aligned across groups; direct capability and pairwise interpretation is valid.',
        'LIMIT_MISMATCH': 'Nominals align but limits differ; compare central tendency carefully across groups.',
        'NOM_MISMATCH': 'Nominals differ across groups; avoid direct between-group interpretation.',
        'INVALID_SPEC': 'One or more spec values are invalid/missing; capability is limited or unavailable.',
    }
    limitations = []
    if not analysis_policy.get('allow_pairwise'):
        limitations.append('pairwise disabled')
    if not analysis_policy.get('allow_capability'):
        limitations.append('capability disabled')

    return {
        'status': spec_status,
        'interpretation_limits': '; '.join(limitations) if limitations else 'none',
        'summary': interpretation_by_status.get(spec_status, 'Spec comparability could not be determined.'),
    }


def build_metric_insights(metric_row):
    """Generate deterministic 1-3 line insight block for a metric."""
    desc_rows = metric_row.get('descriptive_stats', [])
    pairwise_rows = metric_row.get('pairwise_rows', [])
    comparability = metric_row.get('comparability_summary', {})

    lines = [
        (
            f"Comparability={comparability.get('status')} "
            f"(limits: {comparability.get('interpretation_limits', 'none')})."
        )
    ]

    if desc_rows:
        sorted_by_mean = sorted(
            [row for row in desc_rows if row.get('mean') is not None],
            key=lambda row: row['mean'],
        )
        if sorted_by_mean:
            low = sorted_by_mean[0]
            high = sorted_by_mean[-1]
            lines.append(
                (
                    f"Mean range spans {low.get('group')} ({low.get('mean'):.4g}) to "
                    f"{high.get('group')} ({high.get('mean'):.4g})."
                )
            )

    if pairwise_rows:
        best = sorted(
            pairwise_rows,
            key=lambda row: (row.get('adjusted_p_value') is None, row.get('adjusted_p_value') or float('inf')),
        )[0]
        lines.append(
            (
                f"Strongest pairwise signal: {best.get('group_a')} vs {best.get('group_b')} "
                f"(adj p={best.get('adjusted_p_value')}, verdict={best.get('verdict')})."
            )
        )
    elif metric_row.get('analysis_policy', {}).get('allow_pairwise'):
        lines.append('Pairwise enabled but no valid A/B rows were produced.')
    else:
        lines.append('Pairwise interpretation is disabled for this metric.')

    return lines[:3]


def compute_pairwise_rows(metric_identity, grouped_values, *, alpha=0.05, correction_method='holm'):
    """Build pairwise comparison rows for a single metric."""
    config = ComparisonStatsConfig(alpha=alpha, correction_method=correction_method)
    pairwise_rows = compute_metric_pairwise_stats(metric_identity, grouped_values, config=config)
    output = []
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

    return {
        'cp': cp_value,
        'capability': capability_value,
        'capability_type': capability_type,
        'cpk': cpk_value,
        'status': status,
        'sigma': sigma,
        'mean': mean_value,
        'capability_mode': capability_mode,
    }


def build_group_analysis_diagnostics_payload(
    *,
    effective_scope,
    requested_scope,
    reference_count,
    metric_rows,
    skipped_metrics,
    skip_reason=None,
):
    """Build diagnostics payload for worksheet rendering and debugging."""
    status_counts = {status: 0 for status in _SPEC_STATUSES}
    for row in metric_rows:
        status = str(row.get('spec_status') or '').upper()
        if status in status_counts:
            status_counts[status] += 1

    return {
        'requested_scope': str(requested_scope or 'auto').strip().lower(),
        'effective_scope': effective_scope,
        'reference_count': int(reference_count),
        'metric_count': len(metric_rows),
        'skipped_metric_count': len(skipped_metrics),
        'status_counts': status_counts,
        'skip_reason': skip_reason,
        'metrics': metric_rows,
        'skipped_metrics': skipped_metrics,
    }


def _normalize_grouped_working_df(grouped_df):
    working = grouped_df.copy()
    if 'GROUP' not in working.columns:
        working['GROUP'] = 'POPULATION'
    working['GROUP'] = normalize_group_labels(working['GROUP'], missing_label='POPULATION', normalize_blank=True)
    working['MEAS'] = pd.to_numeric(working.get('MEAS'), errors='coerce')
    return working.dropna(subset=['MEAS'])


def evaluate_group_analysis_readiness(grouped_df, *, requested_scope='auto', eligible_metrics=None):
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

    working = _normalize_grouped_working_df(grouped_df)

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

    metric_column = 'HEADER - AX' if 'HEADER - AX' in working.columns else 'HEADER'
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
):
    """Assemble metric-level Group Analysis payload for writer modules."""
    if not isinstance(grouped_df, pd.DataFrame):
        grouped_df = pd.DataFrame()

    readiness = evaluate_group_analysis_readiness(
        grouped_df,
        requested_scope=requested_scope,
        eligible_metrics=eligible_metrics,
    )
    reference_count = int(grouped_df.get('REFERENCE', pd.Series(dtype=object)).dropna().nunique())
    effective_scope = readiness['effective_scope']

    if not readiness['runnable']:
        diagnostics = build_group_analysis_diagnostics_payload(
            effective_scope=effective_scope,
            requested_scope=requested_scope,
            reference_count=reference_count,
            metric_rows=[],
            skipped_metrics=[],
            skip_reason=readiness['skip_reason'],
        )
        return {
            'status': 'skipped',
            'effective_scope': effective_scope,
            'skip_reason': readiness['skip_reason'],
            'metric_rows': [],
            'diagnostics': diagnostics,
        }

    working = _normalize_grouped_working_df(grouped_df)
    metric_column = 'HEADER - AX' if 'HEADER - AX' in working.columns else 'HEADER'
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
            skipped_metrics.append({'metric': metric_identity, 'reason': 'insufficient_groups'})
            continue

        spec_status, spec_payload = classify_metric_spec_status(metric_rows_df, spec_columns)
        policy = _resolve_analysis_policy(spec_status, analysis_level)
        if not policy['include_metric']:
            skipped_metrics.append({'metric': metric_identity, 'reason': spec_status.lower()})
            continue

        descriptive_stats = build_group_descriptive_rows(
            grouped_values,
            spec_payload=spec_payload,
            allow_capability=policy['allow_capability'],
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
            )
            if policy['allow_pairwise']
            else []
        )

        comparability_summary = build_comparability_summary(spec_status, policy)

        metrics.append(
            {
                'metric': metric_identity,
                'reference': reference_value,
                'group_count': len(populated_groups),
                'descriptive_stats': descriptive_stats,
                'pairwise_rows': pairwise_rows,
                'spec': spec_payload,
                'spec_status': spec_status,
                'analysis_policy': policy,
                'capability': capability,
                'comparability_summary': comparability_summary,
            }
        )
        metrics[-1]['insights'] = build_metric_insights(metrics[-1])

    diagnostics = build_group_analysis_diagnostics_payload(
        effective_scope=effective_scope,
        requested_scope=requested_scope,
        reference_count=reference_count,
        metric_rows=metrics,
        skipped_metrics=skipped_metrics,
    )

    return {
        'status': 'ready',
        'effective_scope': effective_scope,
        'skip_reason': None,
        'metric_rows': metrics,
        'diagnostics': diagnostics,
    }
