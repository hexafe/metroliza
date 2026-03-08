"""Helpers for workbook-level Group Analysis payload construction."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.comparison_stats import ComparisonStatsConfig, compute_metric_pairwise_stats
from modules.export_grouping_utils import normalize_group_labels
from modules.stats_utils import safe_process_capability

_SKIP_REASON_MESSAGES = {
    'forced_single_reference_scope_mismatch': (
        'Group Analysis skipped: scope is single_reference but export contains multiple references.'
    ),
    'forced_multi_reference_scope_mismatch': (
        'Group Analysis skipped: scope is multi_reference but export does not contain multiple references.'
    ),
    'insufficient_groups': 'Group Analysis skipped: at least 2 groups are required.',
    'missing_numeric_meas': 'Group Analysis skipped: no numeric MEAS values are available.',
    'no_eligible_metrics': 'Group Analysis skipped: no eligible metrics are available.',
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

    if lsl is None and nominal is None and usl is None:
        return 'missing'
    if lsl is None or nominal is None or usl is None:
        return 'partial'
    if lsl > usl:
        return 'invalid_bounds'
    if not (lsl <= nominal <= usl):
        return 'nominal_outside_bounds'
    return 'complete'


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
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {'cp': None, 'cpk': None, 'status': 'insufficient_data'}

    sigma = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    mean_value = float(np.mean(arr))
    cp, cpk = safe_process_capability(
        spec_payload.get('nominal'),
        spec_payload.get('usl'),
        spec_payload.get('lsl'),
        sigma,
        mean_value,
    )
    cp_value = None if cp == 'N/A' else cp
    cpk_value = None if cpk == 'N/A' else cpk
    status = 'ok' if cp_value is not None or cpk_value is not None else 'not_applicable'
    return {
        'cp': cp_value,
        'cpk': cpk_value,
        'status': status,
        'sigma': sigma,
        'mean': mean_value,
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
    return {
        'requested_scope': str(requested_scope or 'auto').strip().lower(),
        'effective_scope': effective_scope,
        'reference_count': int(reference_count),
        'metric_count': len(metric_rows),
        'skipped_metric_count': len(skipped_metrics),
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

        spec_payload = normalize_spec_limits(
            metric_rows_df[spec_columns['lsl']].iloc[0] if spec_columns['lsl'] else None,
            metric_rows_df[spec_columns['nominal']].iloc[0] if spec_columns['nominal'] else None,
            metric_rows_df[spec_columns['usl']].iloc[0] if spec_columns['usl'] else None,
        )
        spec_status = classify_spec_status(spec_payload)

        descriptive_stats = compute_group_descriptive_stats(grouped_values)
        all_metric_values = np.concatenate([np.asarray(values, dtype=float) for values in grouped_values.values()])
        capability = compute_capability_payload(all_metric_values, spec_payload)
        pairwise_rows = compute_pairwise_rows(
            metric_identity,
            grouped_values,
            alpha=alpha,
            correction_method=correction_method,
        )

        metrics.append(
            {
                'metric': metric_identity,
                'reference': reference_value,
                'group_count': len(populated_groups),
                'descriptive_stats': descriptive_stats,
                'pairwise_rows': pairwise_rows,
                'spec': spec_payload,
                'spec_status': spec_status,
                'capability': capability,
            }
        )

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
