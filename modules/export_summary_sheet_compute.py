"""Pure computation helpers for summary-sheet export orchestration."""

from __future__ import annotations

from typing import Any

import pandas as pd

from modules.chart_render_service import (
    ChartSamplingPolicy,
    build_violin_payload_vectorized,
    sample_frame_for_chart,
)
from modules.export_sheet_writer import build_summary_panel_write_plan
from modules.export_summary_composition_service import build_summary_table_composition
from modules.export_summary_sheet_planner import build_summary_image_anchor_plan
from modules.export_summary_utils import (
    build_summary_panel_labels,
    build_trend_plot_payload,
    compute_estimated_tail_metrics,
    compute_measurement_summary,
    compute_normality_status,
    resolve_nominal_and_limits,
)
from modules.export_chart_payload_helpers import resolve_summary_annotation_strategy
from modules.export_chart_payload_helpers import build_histogram_table_data
from modules.stats_utils import is_one_sided_geometric_tolerance, safe_process_capability


def retrieve_summary_statistics(
    header_group: pd.DataFrame,
    *,
    sql_summary: dict[str, Any] | None,
    nom: float | None,
    usl: float | None,
    lsl: float | None,
) -> dict[str, Any]:
    """Resolve stable summary statistics for a header group.

    Uses the SQL aggregate when complete, otherwise falls back to the existing
    in-memory summary helper.
    """

    meas_series = pd.to_numeric(header_group.get('MEAS'), errors='coerce')
    summary_stats = None
    if sql_summary is not None:
        sample_size = int(sql_summary.get('sample_size') or 0)
        average_raw = sql_summary.get('average')
        minimum_raw = sql_summary.get('minimum')
        maximum_raw = sql_summary.get('maximum')
        sigma_raw = sql_summary.get('sigma')
        nok_count = int(sql_summary.get('nok_count') or 0)
        has_complete_sql_summary = (
            sample_size > 0
            and average_raw is not None
            and minimum_raw is not None
            and maximum_raw is not None
        )
        if has_complete_sql_summary:
            average = float(average_raw)
            sigma = float(sigma_raw or 0.0)
            cp, cpk = safe_process_capability(nom, usl, lsl, sigma, average)
            one_sided_mode = bool(is_one_sided_geometric_tolerance(nom, lsl))
            normality = compute_normality_status(
                meas_series,
                one_sided=one_sided_mode,
                location_bound=lsl,
            )
            summary_stats = {
                'minimum': float(minimum_raw),
                'maximum': float(maximum_raw),
                'sigma': sigma,
                'average': average,
                'median': float(meas_series.median()),
                'cp': cp,
                'cpk': cpk,
                'sample_size': sample_size,
                'nok_count': nok_count,
                'nok_pct': (nok_count / sample_size),
                'observed_nok_count': nok_count,
                'observed_nok_pct': (nok_count / sample_size),
                'estimated_nok_pct': None,
                'estimated_nok_ppm': None,
                'estimated_yield_pct': None,
                'normality_status': normality['status'],
                'normality_text': normality['text'],
                'normality_test_name': normality.get('test_name', 'Shapiro'),
                'normality_p_value': normality.get('p_value'),
                'usl': usl,
            }

    if summary_stats is None:
        summary_stats = compute_measurement_summary(header_group, usl=usl, lsl=lsl, nom=nom)

    summary_stats.setdefault('normality_test_name', 'Shapiro')
    summary_stats.setdefault('normality_p_value', None)
    summary_stats.setdefault('observed_nok_count', summary_stats.get('nok_count', 0))
    summary_stats.setdefault('observed_nok_pct', summary_stats.get('nok_pct', 0))
    summary_stats.setdefault('estimated_nok_pct', None)
    summary_stats.setdefault('estimated_nok_ppm', None)
    summary_stats.setdefault('estimated_yield_pct', None)
    if lsl is not None:
        summary_stats.setdefault('observed_nok_below_lsl_count', int((meas_series < lsl).sum()))
    if usl is not None:
        summary_stats.setdefault('observed_nok_above_usl_count', int((meas_series > usl).sum()))
    summary_stats['usl'] = usl
    return summary_stats


def normalize_summary_group_frame(header_group: pd.DataFrame, *, grouping_key: str | None = None) -> pd.DataFrame:
    """Return a copy with numeric measurement values normalized once."""

    normalized = header_group.copy()
    normalized['MEAS'] = pd.to_numeric(normalized.get('MEAS'), errors='coerce')
    if grouping_key and grouping_key in normalized.columns:
        grouping_series = normalized[grouping_key]
        if pd.api.types.is_string_dtype(grouping_series) or pd.api.types.is_object_dtype(grouping_series):
            normalized[grouping_key] = grouping_series.astype(str).str.strip()
    return normalized


def resolve_sampling_context(
    header_group: pd.DataFrame,
    *,
    grouping_applied: bool,
    sampling_policy: ChartSamplingPolicy,
    violin_plot_min_samplesize: int,
) -> dict[str, Any]:
    """Build shared sampled frames and typed chart payload inputs.

    Sampling work is cached per chart type while exposing the derived frames and
    typed payload structures needed by downstream render helpers.
    """

    distribution_key = 'GROUP' if grouping_applied else 'SAMPLE_NUMBER'
    scatter_key = distribution_key
    sampled_frames = {
        chart_type: sample_frame_for_chart(header_group, chart_type, sampling_policy)
        for chart_type in ('distribution', 'iqr', 'histogram', 'trend')
    }

    distribution_labels, distribution_values, can_render_violin = build_violin_payload_vectorized(
        sampled_frames['distribution'],
        distribution_key,
        violin_plot_min_samplesize,
    )
    iqr_labels, iqr_values, _ = build_violin_payload_vectorized(
        sampled_frames['iqr'],
        distribution_key,
        violin_plot_min_samplesize,
    )

    return {
        'distribution_key': distribution_key,
        'scatter_key': scatter_key,
        'sampled_frames': sampled_frames,
        'distribution_payload': {
            'labels': distribution_labels,
            'values': distribution_values,
            'can_render_violin': can_render_violin,
        },
        'iqr_payload': {
            'labels': iqr_labels,
            'values': iqr_values,
        },
        'histogram_payload': {
            'measurements': sampled_frames['histogram']['MEAS'].dropna().to_numpy(dtype=float, copy=False),
            'sampled_group': sampled_frames['histogram'],
        },
        'trend_payload': {
            'sampled_group': sampled_frames['trend'],
            'payload': build_trend_plot_payload(
                sampled_frames['trend'],
                grouping_active=grouping_applied,
                label_column=distribution_key,
            ),
        },
    }


def prepare_summary_chart_payloads(
    *,
    header: str,
    grouping_applied: bool,
    sampling_context: dict[str, Any],
    summary_stats: dict[str, Any],
) -> dict[str, Any]:
    """Prepare pure chart payload metadata for the summary sheet."""

    distribution_payload = dict(sampling_context['distribution_payload'])
    iqr_payload = dict(sampling_context['iqr_payload'])

    if grouping_applied:
        distribution_counts = compute_group_sample_counts(
            sampling_context['sampled_frames']['distribution'],
            sampling_context['distribution_key'],
        )
        iqr_counts = compute_group_sample_counts(
            sampling_context['sampled_frames']['iqr'],
            sampling_context['distribution_key'],
        )
        distribution_payload['labels'] = append_group_sample_counts(distribution_payload['labels'], distribution_counts)
        iqr_payload['labels'] = append_group_sample_counts(iqr_payload['labels'], iqr_counts)

    distribution_labels = build_summary_panel_labels(
        distribution_payload.get('labels') or [],
        grouping_active=grouping_applied,
    )
    iqr_labels = build_summary_panel_labels(
        iqr_payload.get('labels') or [],
        grouping_active=grouping_applied,
    )

    distribution_title = header if distribution_payload['can_render_violin'] else f"{header} (means)"
    summary_point_count = len(distribution_labels)
    annotation_strategy = resolve_summary_annotation_strategy(x_point_count=summary_point_count)

    histogram_table_payload = build_histogram_table_data(summary_stats)
    summary_table_composition = build_summary_table_composition(summary_stats, histogram_table_payload)

    return {
        'distribution': {
            **distribution_payload,
            'labels': distribution_labels,
            'title': distribution_title,
        },
        'iqr': {
            **iqr_payload,
            'labels': iqr_labels,
        },
        'trend': sampling_context['trend_payload']['payload'],
        'histogram': {
            **sampling_context['histogram_payload'],
            'histogram_table_payload': histogram_table_payload,
        },
        'composition': summary_table_composition,
        'annotation_strategy': annotation_strategy,
    }


def finalize_histogram_summary_payload(
    summary_stats: dict[str, Any],
    distribution_fit_result: dict[str, Any],
    *,
    lsl: float | None,
    usl: float | None,
) -> dict[str, Any]:
    """Return a copy of summary stats enriched with modeled tail metrics."""

    updated_summary_stats = dict(summary_stats)
    updated_summary_stats.update(compute_estimated_tail_metrics(distribution_fit_result, lsl=lsl, usl=usl))
    histogram_table_payload = build_histogram_table_data(updated_summary_stats)
    summary_table_composition = build_summary_table_composition(updated_summary_stats, histogram_table_payload)
    return {
        'summary_stats': updated_summary_stats,
        'histogram_table_payload': histogram_table_payload,
        'summary_table_composition': summary_table_composition,
    }


def build_summary_worksheet_plan(*, header: str, col: int, panel_subtitle: str) -> dict[str, Any]:
    """Return stable worksheet write metadata for one summary header panel."""

    anchors = build_summary_image_anchor_plan(col)
    panel_plan = build_summary_panel_write_plan(anchors, header)
    return {
        'summary_anchors': anchors,
        'panel_plan': panel_plan,
        'header_cell': panel_plan['header_cell'],
        'subtitle_value': panel_subtitle,
        'image_slots': panel_plan['image_slots'],
    }


def compute_group_sample_counts(sampled_group: pd.DataFrame, grouping_key: str) -> dict[str, int]:
    if sampled_group is None or sampled_group.empty:
        return {}
    if grouping_key not in sampled_group.columns or 'MEAS' not in sampled_group.columns:
        return {}

    count_frame = sampled_group[[grouping_key, 'MEAS']].dropna(subset=[grouping_key, 'MEAS']).copy()
    if count_frame.empty:
        return {}

    count_frame[grouping_key] = count_frame[grouping_key].astype(str)
    grouped_counts = count_frame.groupby(grouping_key, sort=False)['MEAS'].size()
    return {str(label): int(count) for label, count in grouped_counts.items()}


def append_group_sample_counts(labels: list[str], sample_counts: dict[str, int]) -> list[str]:
    if not labels:
        return []
    return [f"{str(label)} (n={int(sample_counts.get(str(label), 0))})" for label in labels]


def resolve_summary_stages(
    header_group: pd.DataFrame,
    *,
    sql_summary: dict[str, Any] | None,
    grouping_applied: bool,
    density_mode: str,
    violin_plot_min_samplesize: int,
    header: str,
    col: int,
) -> dict[str, Any]:
    """Compute all pure summary planning stages in one contract-friendly payload."""

    limits = resolve_nominal_and_limits(header_group)
    summary_stats = retrieve_summary_statistics(
        header_group,
        sql_summary=sql_summary,
        nom=limits['nom'],
        usl=limits['usl'],
        lsl=limits['lsl'],
    )
    normalized_group = normalize_summary_group_frame(
        header_group,
        grouping_key='GROUP' if grouping_applied else 'SAMPLE_NUMBER',
    )
    from modules.chart_render_service import resolve_chart_sampling_policy

    sampling_context = resolve_sampling_context(
        normalized_group,
        grouping_applied=grouping_applied,
        sampling_policy=resolve_chart_sampling_policy(density_mode=density_mode),
        violin_plot_min_samplesize=violin_plot_min_samplesize,
    )
    chart_payloads = prepare_summary_chart_payloads(
        header=header,
        grouping_applied=grouping_applied,
        sampling_context=sampling_context,
        summary_stats=summary_stats,
    )
    worksheet_plan = build_summary_worksheet_plan(
        header=header,
        col=col,
        panel_subtitle=chart_payloads['composition']['panel_subtitle'],
    )
    return {
        'limits': limits,
        'summary_stats': summary_stats,
        'normalized_group': normalized_group,
        'sampling_context': sampling_context,
        'chart_payloads': chart_payloads,
        'worksheet_plan': worksheet_plan,
    }
