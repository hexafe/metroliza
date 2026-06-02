"""Bridge Metroliza Group Analysis payloads to the hexafe-groupstats engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hexafe_groupstats import (
    AnalysisConfig,
    analyze_metric,
    describe_correction_policy,
    format_correction_method,
)
from metroliza.shared.numeric_coercion import coerce_finite_float as _coerce_float
try:
    from hexafe_groupstats.adapters import (
        capability_rows as _package_capability_rows,
        descriptive_rows as _package_descriptive_rows,
        distribution_rows as _package_distribution_rows,
        metric_row as _package_metric_row,
        pairwise_rows as _package_pairwise_rows,
        posthoc_rows as _package_posthoc_rows,
    )
except Exception:  # pragma: no cover - compatibility with older package builds
    _package_capability_rows = None
    _package_descriptive_rows = None
    _package_distribution_rows = None
    _package_metric_row = None
    _package_pairwise_rows = None
    _package_posthoc_rows = None

_CORRECTION_METHOD_ALIASES = {
    'holm': 'holm',
    'holm_bonferroni': 'holm',
    'bh': 'bh',
    'benjamini_hochberg': 'bh',
    'fdr_bh': 'bh',
}

_POSTHOC_METHOD_ALIASES = {
    'auto': 'auto',
    'legacy': 'legacy',
    'pairwise': 'legacy',
    'tukey': 'tukey',
    'tukey_hsd': 'tukey',
    'tukey-kramer': 'tukey',
    'tukey_kramer': 'tukey',
    'games_howell': 'games_howell',
    'games-howell': 'games_howell',
    'dunn': 'dunn',
}

_BACKEND_ALIASES = {
    'auto': 'auto',
    'python': 'python',
    'py': 'python',
    'rust': 'rust',
    'native': 'rust',
}


def _round_float(value: Any, *, precision: int = 3) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    return round(numeric, precision)


def _normalize_correction_method(value: str | None) -> str:
    normalized = str(value or 'holm').strip().lower()
    return _CORRECTION_METHOD_ALIASES.get(normalized, 'holm')


def _normalize_posthoc_method(value: str | None) -> str:
    normalized = str(value or 'auto').strip().lower()
    return _POSTHOC_METHOD_ALIASES.get(normalized, 'auto')


def _normalize_backend(value: str | None) -> str:
    normalized = str(value or 'auto').strip().lower()
    return _BACKEND_ALIASES.get(normalized, 'auto')


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


def _package_rows(adapter, result) -> list[dict[str, Any]]:
    if not callable(adapter):
        return []
    try:
        return [dict(row) for row in adapter(result)]
    except Exception:
        return []


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
    package_rows = _package_rows(_package_descriptive_rows, result)
    package_by_group = {str(row.get('group')): row for row in package_rows}
    rows = []
    for row in result.descriptive_stats:
        capability_row = capability_by_group.get(row.group)
        package_row = dict(package_by_group.get(str(row.group), {}))
        capability_value, capability_type = (
            _capability_value_and_type(capability_row)
            if capability_row is not None
            else (None, None)
        )
        package_row.update(
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
                'warnings': list(getattr(row, 'warnings', ()) or ()),
            }
        )
        rows.append(package_row)
    return rows


def _pairwise_rows(result, grouped_values: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    package_rows = _package_rows(_package_pairwise_rows, result)
    if not package_rows:
        package_rows = [
            {
                'metric': row.metric,
                'group_a': row.group_a,
                'group_b': row.group_b,
                'test_name': row.test_name,
                'p_value': row.p_value,
                'adjusted_p_value': row.adjusted_p_value,
                'significant': row.significant,
                'effect_size': row.effect_size,
                'effect_type': row.effect_type,
                'method_family': row.method_family,
                'comparison_estimate': row.comparison_estimate,
                'comparison_estimate_label': row.comparison_estimate_label,
                'comparison_ci': row.comparison_ci,
                'effect_size_ci': row.effect_size_ci,
                'warnings': list(row.warnings),
            }
            for row in result.pairwise_results
        ]

    needs_group_mean_delta = any(
        not (
            row.get('comparison_estimate_label') == 'mean_difference'
            and row.get('comparison_estimate') is not None
        )
        for row in package_rows
    )
    means = {}
    if needs_group_mean_delta:
        for group_name, values in grouped_values.items():
            arr = np.asarray(values, dtype=float)
            arr = arr[np.isfinite(arr)]
            if arr.size:
                means[str(group_name)] = float(np.mean(arr))

    rows = []
    for row in package_rows:
        delta_mean = None
        if row.get('comparison_estimate_label') == 'mean_difference' and row.get('comparison_estimate') is not None:
            delta_mean = float(row['comparison_estimate'])
        elif row.get('group_a') in means and row.get('group_b') in means:
            delta_mean = means[row['group_a']] - means[row['group_b']]
        rows.append(
            {
                'metric': row.get('metric'),
                'group_a': row.get('group_a'),
                'group_b': row.get('group_b'),
                'p_value': row.get('p_value'),
                'adjusted_p_value': row.get('adjusted_p_value'),
                'effect_size': row.get('effect_size'),
                'effect_type': row.get('effect_type'),
                'test_used': row.get('test_name') or row.get('test_used'),
                'test_name': row.get('test_name') or row.get('test_used'),
                'significant': bool(row.get('significant')),
                'delta_mean': delta_mean,
                'method_family': row.get('method_family'),
                'comparison_estimate': row.get('comparison_estimate'),
                'comparison_estimate_label': row.get('comparison_estimate_label'),
                'comparison_ci': row.get('comparison_ci'),
                'effect_size_ci': row.get('effect_size_ci'),
                'warnings': list(row.get('warnings') or []),
            }
        )
    return rows


def _omnibus_payload(result, *, alpha: float) -> dict[str, Any]:
    omnibus = getattr(result, 'omnibus', None)
    if omnibus is None:
        return {}
    p_value = getattr(omnibus, 'p_value', None)
    return {
        'test_name': getattr(omnibus, 'test_name', None),
        'p_value': p_value,
        'effect_size': getattr(omnibus, 'effect_size', None),
        'effect_type': getattr(omnibus, 'effect_type', None),
        'significant': bool(p_value is not None and p_value < alpha),
        'warnings': list(getattr(omnibus, 'warnings', ()) or ()),
    }


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


def _distribution_rows(result) -> list[dict[str, Any]]:
    package_rows = _package_rows(_package_distribution_rows, result)
    if package_rows:
        return package_rows
    rows = []
    for row in getattr(result, 'distribution_profiles', ()) or ():
        rows.append(
            {
                'metric': getattr(row, 'metric', None),
                'group': getattr(row, 'group', None),
                'n': getattr(row, 'n', None),
                'skewness': getattr(row, 'skewness', None),
                'excess_kurtosis': getattr(row, 'excess_kurtosis', None),
                'normality_test': getattr(row, 'normality_test', None),
                'normality_p_value': getattr(row, 'normality_p_value', None),
                'normality_status': getattr(row, 'normality_status', None),
                'warnings': list(getattr(row, 'warnings', ()) or ()),
            }
        )
    return rows


def _metric_summary_row(result) -> dict[str, Any]:
    if callable(_package_metric_row):
        try:
            row = dict(_package_metric_row(result))
        except Exception:
            row = {}
        if row:
            row.setdefault('correction_method', getattr(result.diagnostics, 'correction_method', ''))
            row.setdefault('correction_policy', getattr(result.diagnostics, 'correction_policy', ''))
            row.setdefault('analysis_restriction_label', result.analysis_policy.analysis_restriction_label)
            return row
    return {
        'metric': result.metric,
        'backend_used': result.backend_used,
        'group_count': result.group_count,
        'group_order': list(result.group_order),
        'spec_status': result.spec_status.value,
        'analysis_restriction_label': result.analysis_policy.analysis_restriction_label,
        'pairwise_allowed': result.analysis_policy.allow_pairwise,
        'capability_allowed': result.analysis_policy.allow_capability,
        'diagnostics_comment': result.diagnostics.comment,
        'selection_detail': result.assumptions.selection_detail,
        'posthoc_family': None if result.posthoc_summary is None else result.posthoc_summary.family,
        'posthoc_method_name': None if result.posthoc_summary is None else result.posthoc_summary.method_name,
        'posthoc_strategy': result.diagnostics.posthoc_strategy,
        'capability_strategy': result.diagnostics.capability_strategy,
        'correction_method': getattr(result.diagnostics, 'correction_method', ''),
        'correction_policy': getattr(result.diagnostics, 'correction_policy', ''),
        'distribution_flags': list(getattr(result.diagnostics, 'distribution_flags', ()) or ()),
        'simulation_validation': None,
        'warnings': list(result.warnings),
        'structured_insights': _structured_insight_payloads(result),
        'insights': [str(item) for item in (getattr(result, 'insights', ()) or ()) if str(item).strip()],
    }


def _pooled_mean_sigma(result) -> tuple[float | None, float | None]:
    rows = [
        row
        for row in getattr(result, 'descriptive_stats', ())
        if int(getattr(row, 'n', 0) or 0) > 0
    ]
    total_n = sum(int(row.n) for row in rows)
    if total_n <= 0:
        return None, None
    mean_value = sum(float(row.n) * float(row.mean) for row in rows) / float(total_n)
    if total_n == 1:
        return mean_value, 0.0
    sum_squares = 0.0
    for row in rows:
        n = int(row.n)
        row_std = _coerce_float(row.std)
        within = 0.0 if row_std is None or n < 2 else float(n - 1) * (row_std**2)
        between = float(n) * ((float(row.mean) - mean_value) ** 2)
        sum_squares += within + between
    sigma = float(np.sqrt(sum_squares / float(total_n - 1))) if sum_squares >= 0 else None
    return mean_value, sigma


def _metric_capability_payload(result, grouped_values: Mapping[str, Sequence[Any]], spec_payload: Mapping[str, Any]) -> dict[str, Any]:
    capability_mode = _capability_mode(spec_payload)

    if not result.capability_results:
        mean_value, sigma = _pooled_mean_sigma(result)
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
    posthoc_method: str = 'auto',
    include_effect_size_ci: bool = False,
    ci_level: float = 0.95,
    ci_bootstrap_iterations: int = 1000,
    capability_benchmark: float = 1.33,
    simulation_validation_iterations: int = 0,
    simulation_random_seed: int = 42,
    backend: str = 'auto',
    enable_rust_in_auto: bool = False,
    distribution_diagnostics: bool = True,
) -> dict[str, Any]:
    """Analyze one metric through hexafe-groupstats and map results for Metroliza."""

    normalized_spec_records = [_normalize_spec_record(record) for record in spec_records]
    normalized_correction_method = _normalize_correction_method(correction_method)
    normalized_posthoc_method = _normalize_posthoc_method(posthoc_method)
    normalized_backend = _normalize_backend(backend)
    result = analyze_metric(
        metric_identity,
        grouped_values,
        spec_limits=normalized_spec_records,
        config=AnalysisConfig(
            alpha=float(alpha),
            correction_method=normalized_correction_method,
            posthoc_method=normalized_posthoc_method,
            include_effect_size_ci=bool(include_effect_size_ci),
            ci_level=float(ci_level),
            ci_bootstrap_iterations=int(ci_bootstrap_iterations),
            capability_benchmark=float(capability_benchmark),
            simulation_validation_iterations=int(simulation_validation_iterations),
            simulation_random_seed=int(simulation_random_seed),
            backend=normalized_backend,
            enable_rust_in_auto=bool(enable_rust_in_auto),
            distribution_diagnostics=bool(distribution_diagnostics),
        ),
    )
    spec_payload = normalized_spec_records[0] if normalized_spec_records else {'lsl': None, 'nominal': None, 'usl': None}
    metric_summary = _metric_summary_row(result)
    structured_insights = _structured_insight_payloads(result)
    legacy_insights = [str(item) for item in (getattr(result, 'insights', ()) or ()) if str(item).strip()]
    return {
        'result': result,
        'spec_status': result.spec_status.value,
        'spec_payload': spec_payload,
        'analysis_policy': _analysis_policy_payload(result),
        'descriptive_stats': _descriptive_rows(result),
        'distribution_rows': _distribution_rows(result),
        'omnibus': _omnibus_payload(result, alpha=float(alpha)),
        'pairwise_rows': _pairwise_rows(result, grouped_values),
        'posthoc_rows': _package_rows(_package_posthoc_rows, result),
        'capability_rows': _package_rows(_package_capability_rows, result),
        'capability': _metric_capability_payload(result, grouped_values, spec_payload),
        'metric_summary': metric_summary,
        'backend_used': result.backend_used,
        'selection_detail': result.assumptions.selection_detail,
        'posthoc_family': None if result.posthoc_summary is None else result.posthoc_summary.family,
        'posthoc_method_name': None if result.posthoc_summary is None else result.posthoc_summary.method_name,
        'pairwise_strategy': result.diagnostics.pairwise_strategy,
        'posthoc_strategy': result.diagnostics.posthoc_strategy,
        'capability_strategy': result.diagnostics.capability_strategy,
        'correction_method': metric_summary.get('correction_method') or format_correction_method(normalized_correction_method),
        'correction_policy': metric_summary.get('correction_policy') or describe_correction_policy(normalized_correction_method),
        'analysis_restriction_label': metric_summary.get('analysis_restriction_label')
        or result.analysis_policy.analysis_restriction_label,
        'distribution_flags': list(metric_summary.get('distribution_flags') or []),
        'simulation_validation': metric_summary.get('simulation_validation'),
        'capability_benchmark': float(capability_benchmark),
        'posthoc_method': normalized_posthoc_method,
        'backend_requested': normalized_backend,
        'enable_rust_in_auto': bool(enable_rust_in_auto),
        'structured_insights': structured_insights,
        'primary_insight': structured_insights[0] if structured_insights else {},
        'insights': legacy_insights,
        'warnings': list(result.warnings),
    }


__all__ = ['analyze_group_metric']
