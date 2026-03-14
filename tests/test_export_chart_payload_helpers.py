from modules.export_chart_payload_helpers import (
    build_histogram_table_data,
    build_histogram_table_render_data,
    resolve_summary_annotation_strategy,
)


def test_build_histogram_table_data_preserves_capability_rows():
    payload = build_histogram_table_data(
        {
            'minimum': 1.0,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5,
            'cpk': 1.2,
            'sample_size': 10,
            'nok_count': 1,
            'nok_pct': 0.1,
        }
    )

    assert payload['rows'][5] == ('Cp', 1.5)
    assert payload['capability_rows']['Cpk']['display_value'] == 1.2


def test_build_histogram_table_render_data_supports_three_column_mode():
    rows = [('Min', 1.0), ('Max', 2.0)]

    assert build_histogram_table_render_data(rows, three_column=True) == [['Min', '', 1.0], ['Max', '', 2.0]]


def test_resolve_summary_annotation_strategy_switches_at_density_thresholds():
    assert resolve_summary_annotation_strategy(x_point_count=8)['annotation_mode'] == 'dynamic'
    assert resolve_summary_annotation_strategy(x_point_count=24)['annotation_mode'] == 'static_compact'
    assert resolve_summary_annotation_strategy(x_point_count=60)['label_mode'] == 'sparse'
