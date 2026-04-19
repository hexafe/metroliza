"""Bridge Metroliza Group Analysis payloads to the hexafe-groupstats engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hexafe_groupstats import AnalysisConfig, analyze_metric

_CORRECTION_METHOD_ALIASES = {
    'holm': 'holm',
    'holm_bonferroni': 'holm',
    'bh': 'bh',
    'benjamini_hochberg': 'bh',
    'fdr_bh': 'bh',
}


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _round_float(value: Any, *, precision: int = 3) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    return round(numeric, precision)


def _normalize_correction_method(value: str | None) -> str:
    normalized = str(value or 'holm').strip().lower()
    return _CORRECTION_METHOD_ALIASES.get(normalized, 'holm')


def _normalize_spec_record(spec_record: Mapping[str, Any] | None) -> dict[str, float | None]:
    record = spec_record or {}
    return {
        'lsl': _round_float(record.get('lsl')),
        'nominal': _round_float(record.get('nominal')),
        'usl': _round_float(record.get('usl')),
    }


def _analysis_policy_payload(result) -> dict[str, Any]:
    return {
        'include_metric': bool(result.analysis_policy.include_metric),
        'allow_pairwise': bool(result.analysis_policy.allow_pairwise),
        'allow_capability': bool(result.analysis_policy.allow_capability),
    }


def _ci_interval_payload(interval: tuple[float, float] | None) -> dict[str, float] | None:
    if interval is None or len(interval) != 2:
        return None
    lower = _round_float(interval[0])
    upper = _round_float(interval[1])
    if lower is None or upper is None:
        return None
    return {'lower': lower, 'upper': upper}


def _capability_value_and_type(capability_row) -> tuple[float | None, str | None]:
    if capability_row.cpk is not None:
        return float(capability_row.cpk), 'Cpk'
    if capability_row.cpu is not None:
        return float(capability_row.cpu), 'Cpk+'
    if capability_row.cpl is not None:
        return float(capability_row.cpl), 'Cpk-'
    return None, None


def _capability_mode(spec_payload: Mapping[str, Any]) -> str:
    lsl = spec_payload.get('lsl')
    usl = spec_payload.get('usl')
    if lsl is not None and usl is not None:
        return 'bilateral'
    if usl is not None:
        return 'upper_only'
    if lsl is not None:
        return 'lower_only'
    return 'unusable'


def _capability_ci_payload(capability_row) -> dict[str, dict[str, float] | None]:
    capability_value, capability_type = _capability_value_and_type(capability_row)
    if capability_type == 'Cpk':
        cpk_interval = _ci_interval_payload(capability_row.cpk_ci)
    elif capability_type == 'Cpk+':
        cpk_interval = _ci_interval_payload(capability_row.cpu_ci)
    elif capability_type == 'Cpk-':
        cpk_interval = _ci_interval_payload(capability_row.cpl_ci)
    else:
        cpk_interval = None
    return {
        'cp': _ci_interval_payload(capability_row.cp_ci),
        'cpk': cpk_interval if capability_value is not None else None,
    }


def _descriptive_rows(result) -> list[dict[str, Any]]:
    capability_by_group = {row.group: row for row in result.capability_results}
    rows = []
    for row in result.descriptive_stats:
        capability_row = capability_by_group.get(row.group)
        capability_value, capability_type = (
            _capability_value_and_type(capability_row)
            if capability_row is not None
            else (None, None)
        )
        rows.append(
            {
                'group': row.group,
                'n': int(row.n),
                'mean': _round_float(row.mean),
                'std': _round_float(row.std),
                'median': _round_float(row.median),
                'iqr': _round_float(row.iqr),
                'min': _round_float(row.minimum),
                'max': _round_float(row.maximum),
                'cp': _round_float(None if capability_row is None else capability_row.cp),
                'capability': _round_float(capability_value),
                'capability_type': capability_type,
                'capability_ci': (
                    _capability_ci_payload(capability_row)
                    if capability_row is not None
                    else {'cp': None, 'cpk': None}
                ),
            }
        )
    return rows


def _pairwise_rows(result, grouped_values: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    means = {}
    for group_name, values in grouped_values.items():
        arr = np.asarray(values, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size:
            means[str(group_name)] = float(np.mean(arr))

    rows = []
    for row in result.pairwise_results:
        delta_mean = None
        if row.comparison_estimate_label == 'mean_difference' and row.comparison_estimate is not None:
            delta_mean = float(row.comparison_estimate)
        elif row.group_a in means and row.group_b in means:
            delta_mean = means[row.group_a] - means[row.group_b]
        rows.append(
            {
                'metric': row.metric,
                'group_a': row.group_a,
                'group_b': row.group_b,
                'p_value': row.p_value,
                'adjusted_p_value': row.adjusted_p_value,
                'effect_size': row.effect_size,
                'test_used': row.test_name,
                'significant': bool(row.significant),
                'delta_mean': delta_mean,
                'method_family': row.method_family,
                'comparison_estimate_label': row.comparison_estimate_label,
                'warnings': list(row.warnings),
            }
        )
    return rows


def _structured_insight_payloads(result) -> list[dict[str, Any]]:
    payloads = []
    for row in getattr(result, 'structured_insights', ()) or ():
        payloads.append(
            {
                'headline': str(getattr(row, 'headline', '') or '').strip(),
                'why': str(getattr(row, 'why', '') or '').strip(),
                'first_action': str(getattr(row, 'first_action', '') or '').strip(),
                'confidence_or_caution': [
                    str(item)
                    for item in (getattr(row, 'confidence_or_caution', ()) or ())
                    if str(item).strip()
                ],
                'priority_score': getattr(row, 'priority_score', None),
                'status_class': str(getattr(row, 'status_class', '') or '').strip(),
            }
        )
    return [row for row in payloads if row.get('headline') or row.get('why') or row.get('first_action')]


def _metric_capability_payload(result, grouped_values: Mapping[str, Sequence[Any]], spec_payload: Mapping[str, Any]) -> dict[str, Any]:
    all_values = (
        np.concatenate([np.asarray(values, dtype=float) for values in grouped_values.values()])
        if grouped_values
        else np.asarray([], dtype=float)
    )
    all_values = all_values[np.isfinite(all_values)]
    sigma = float(np.std(all_values, ddof=1)) if all_values.size > 1 else (0.0 if all_values.size == 1 else None)
    mean_value = float(np.mean(all_values)) if all_values.size else None
    capability_mode = _capability_mode(spec_payload)

    if not result.capability_results:
        return {
            'cp': None,
            'capability': None,
            'capability_type': None,
            'cpk': None,
            'capability_ci': {'cp': None, 'cpk': None},
            'status': 'not_applicable',
            'sigma': sigma,
            'mean': mean_value,
            'capability_mode': capability_mode,
        }

    ranking = []
    for row in result.capability_results:
        capability_value, _capability_type = _capability_value_and_type(row)
        ranking.append(
            (
                float('inf') if capability_value is None else capability_value,
                float('inf') if row.cp is None else float(row.cp),
                row.group,
                row,
            )
        )
    _value, _cp, _group, selected = sorted(ranking)[0]
    capability_value, capability_type = _capability_value_and_type(selected)

    return {
        'cp': _round_float(selected.cp),
        'capability': _round_float(capability_value),
        'capability_type': capability_type,
        'cpk': _round_float(capability_value),
        'capability_ci': _capability_ci_payload(selected),
        'status': 'ok' if capability_value is not None or selected.cp is not None else 'not_applicable',
        'sigma': _round_float(selected.sigma),
        'mean': _round_float(selected.mean),
        'capability_mode': capability_mode,
    }


def analyze_group_metric(
    metric_identity: str,
    grouped_values: Mapping[str, Sequence[Any]],
    *,
    spec_records: Sequence[Mapping[str, Any]],
    alpha: float = 0.05,
    correction_method: str = 'holm',
) -> dict[str, Any]:
    """Analyze one metric through hexafe-groupstats and map results for Metroliza."""

    normalized_spec_records = [_normalize_spec_record(record) for record in spec_records]
    result = analyze_metric(
        metric_identity,
        grouped_values,
        spec_limits=normalized_spec_records,
        config=AnalysisConfig(
            alpha=float(alpha),
            correction_method=_normalize_correction_method(correction_method),
            distribution_diagnostics=False,
        ),
    )
    spec_payload = normalized_spec_records[0] if normalized_spec_records else {'lsl': None, 'nominal': None, 'usl': None}
    structured_insights = _structured_insight_payloads(result)
    legacy_insights = [str(item) for item in (getattr(result, 'insights', ()) or ()) if str(item).strip()]
    return {
        'result': result,
        'spec_status': result.spec_status.value,
        'spec_payload': spec_payload,
        'analysis_policy': _analysis_policy_payload(result),
        'descriptive_stats': _descriptive_rows(result),
        'pairwise_rows': _pairwise_rows(result, grouped_values),
        'capability': _metric_capability_payload(result, grouped_values, spec_payload),
        'backend_used': result.backend_used,
        'selection_detail': result.assumptions.selection_detail,
        'posthoc_family': None if result.posthoc_summary is None else result.posthoc_summary.family,
        'posthoc_method_name': None if result.posthoc_summary is None else result.posthoc_summary.method_name,
        'pairwise_strategy': result.diagnostics.pairwise_strategy,
        'posthoc_strategy': result.diagnostics.posthoc_strategy,
        'capability_strategy': result.diagnostics.capability_strategy,
        'structured_insights': structured_insights,
        'primary_insight': structured_insights[0] if structured_insights else {},
        'insights': legacy_insights,
        'warnings': list(result.warnings),
    }


__all__ = ['analyze_group_metric']
