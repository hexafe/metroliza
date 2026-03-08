"""Helpers for workbook-level Group Analysis export decisions."""

from __future__ import annotations

import pandas as pd

from modules.export_grouping_utils import normalize_group_labels


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

    working = grouped_df.copy()
    if 'GROUP' not in working.columns:
        working['GROUP'] = 'POPULATION'
    working['GROUP'] = normalize_group_labels(working['GROUP'], missing_label='POPULATION', normalize_blank=True)
    working['MEAS'] = pd.to_numeric(working.get('MEAS'), errors='coerce')
    working = working.dropna(subset=['MEAS'])

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
