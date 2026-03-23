import pandas as pd

from modules.chart_render_service import resolve_chart_sampling_policy
from modules.export_summary_sheet_compute import (
    build_summary_worksheet_plan,
    normalize_summary_group_frame,
    prepare_summary_chart_payloads,
    resolve_sampling_context,
    retrieve_summary_statistics,
)


def _header_group():
    return pd.DataFrame(
        {
            'REFERENCE': ['R1'] * 4,
            'HEADER': ['H1'] * 4,
            'AX': ['X'] * 4,
            'SAMPLE_NUMBER': ['1', '2', '3', '4'],
            'GROUP': ['A', 'A', 'B', 'B'],
            'MEAS': ['1.0', '2.0', '3.5', '4.5'],
            'NOM': [2.5] * 4,
            '+TOL': [1.0] * 4,
            '-TOL': [-1.0] * 4,
        }
    )


def test_build_summary_worksheet_plan_preserves_legacy_layout_contract():
    plan = build_summary_worksheet_plan(header='H1', col=5, panel_subtitle='subtitle')

    assert plan['header_cell'] == {'row': 0, 'col': 0, 'value': 'H1'}
    assert plan['subtitle_value'] == 'subtitle'
    assert plan['image_slots']['distribution'] == {'row': 1, 'col': 1}
    assert plan['image_slots']['iqr'] == {'row': 1, 'col': 11}
    assert plan['image_slots']['histogram'] == {'row': 1, 'col': 21}
    assert plan['image_slots']['trend'] == {'row': 1, 'col': 35}


def test_resolve_sampling_context_normalizes_numeric_measurements_once_and_returns_typed_payloads():
    normalized = normalize_summary_group_frame(_header_group(), grouping_key='GROUP')

    assert normalized['MEAS'].dtype.kind in {'f', 'i'}

    context = resolve_sampling_context(
        normalized,
        grouping_applied=True,
        sampling_policy=resolve_chart_sampling_policy(density_mode='full'),
        violin_plot_min_samplesize=1,
    )

    assert context['distribution_key'] == 'GROUP'
    assert list(context['sampled_frames']['histogram']['MEAS']) == [1.0, 2.0, 3.5, 4.5]
    assert context['histogram_payload']['measurements'].dtype.kind == 'f'
    assert context['distribution_payload']['can_render_violin'] is True
    assert context['distribution_payload']['labels'] == ['A', 'B']
    assert context['iqr_payload']['values'] == [[1.0, 2.0], [3.5, 4.5]]


def test_prepare_summary_chart_payloads_keeps_group_count_labels_and_titles_stable():
    frame = normalize_summary_group_frame(_header_group(), grouping_key='GROUP')
    summary_stats = retrieve_summary_statistics(frame, sql_summary=None, nom=2.5, usl=3.5, lsl=1.5)
    sampling_context = resolve_sampling_context(
        frame,
        grouping_applied=True,
        sampling_policy=resolve_chart_sampling_policy(density_mode='full'),
        violin_plot_min_samplesize=1,
    )

    payloads = prepare_summary_chart_payloads(
        header='H1',
        grouping_applied=True,
        sampling_context=sampling_context,
        summary_stats=summary_stats,
    )

    assert payloads['distribution']['labels'] == ['A (n=2)', 'B (n=2)']
    assert payloads['iqr']['labels'] == ['A (n=2)', 'B (n=2)']
    assert payloads['distribution']['title'] == 'H1'
    assert payloads['composition']['panel_subtitle']
    assert payloads['annotation_strategy']['label_mode'] in {'all', 'adaptive', 'sparse'}
