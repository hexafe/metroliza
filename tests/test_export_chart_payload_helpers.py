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

    assert payload['rows'][5] == ('Spec type', 'two-sided')
    cp_row = dict(payload['rows'])['Cp']
    cpk_row = dict(payload['rows'])['Cpk']
    assert cp_row.startswith('1.50 [')
    assert cpk_row.startswith('1.20 [')
    assert payload['capability_rows']['Cpk']['display_value'].startswith('1.20 [')
    assert 'Cpk 95% CI' in dict(payload['rows'])


def test_build_histogram_table_render_data_supports_three_column_mode():
    rows = [('Min', 1.0), ('Max', 2.0)]

    assert build_histogram_table_render_data(rows, three_column=True) == [['Min', '', 1.0], ['Max', '', 2.0]]


def test_resolve_summary_annotation_strategy_switches_at_density_thresholds():
    assert resolve_summary_annotation_strategy(x_point_count=8)['annotation_mode'] == 'dynamic'
    assert resolve_summary_annotation_strategy(x_point_count=24)['annotation_mode'] == 'static_compact'
    assert resolve_summary_annotation_strategy(x_point_count=60)['label_mode'] == 'sparse'


def test_build_histogram_table_data_exposes_observed_and_estimated_metrics():
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
            'observed_nok_count': 1,
            'observed_nok_pct': 0.1,
            'estimated_nok_pct': 0.2,
            'estimated_nok_ppm': 200000.0,
            'estimated_yield_pct': 0.8,
        }
    )

    assert payload['summary_metrics'] == {
        'observed_nok_count': 1,
        'observed_nok_pct': 0.1,
        'estimated_nok_pct': 0.2,
        'estimated_nok_ppm': 200000.0,
        'estimated_yield_pct': 0.8,
        'nok_pct_abs_diff': 0.1,
        'nok_pct_abs_diff_pp': 10.0,
        'nok_pct_rel_diff': 1.0,
        'nok_pct_discrepancy_threshold': 0.02,
        'nok_pct_discrepancy_warning': True,
    }


def test_build_histogram_table_data_flags_n10_with_warning_confidence_rows():
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

    labels = [label for label, _ in payload['rows']]
    assert 'Confidence !' in labels
    assert 'Cp uncertainty' in labels
    assert 'Cpk uncertainty' in labels
    assert payload['sample_confidence']['severity'] == 'warning'
    assert payload['capability_rows']['Cp']['label'] == 'Cp'


def test_build_histogram_table_data_flags_warning_low_n_with_uncertainty_bands():
    payload = build_histogram_table_data(
        {
            'minimum': 1.0,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5,
            'cpk': 1.2,
            'sample_size': 20,
            'nok_count': 1,
            'nok_pct': 0.1,
        }
    )

    labels = [label for label, _ in payload['rows']]
    assert 'Confidence !' in labels
    assert 'Cp uncertainty' in labels
    assert 'Cpk uncertainty' in labels
    assert payload['sample_confidence']['is_low_n'] is True
    assert payload['sample_confidence']['severity'] == 'warning'


def test_build_histogram_table_data_keeps_standard_labels_for_stable_n():
    payload = build_histogram_table_data(
        {
            'minimum': 1.0,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5,
            'cpk': 1.2,
            'sample_size': 50,
            'nok_count': 1,
            'nok_pct': 0.1,
        }
    )

    labels = [label for label, _ in payload['rows']]
    assert 'Cp' in labels
    assert not any('uncertainty' in label for label in labels)
    assert payload['sample_confidence']['is_low_n'] is False


def test_build_histogram_table_data_uses_cpu_and_cp_not_defined_for_one_sided_upper():
    payload = build_histogram_table_data(
        {
            'minimum': 0.0,
            'maximum': 0.06,
            'average': 0.03,
            'median': 0.03,
            'sigma': 0.01,
            'cp': 'N/A',
            'cpk': 0.0,
            'sample_size': 8,
            'nok_count': 0,
            'nok_pct': 0.0,
            'nom': 0.0,
            'lsl': 0.0,
            'usl': 0.06,
        }
    )

    labels = [label for label, _ in payload['rows']]
    assert ('Spec type', 'one-sided upper') in payload['rows']
    assert 'Cp (not defined for one-sided) (info)' in labels
    assert 'Cpu' in labels
    assert 'Cp uncertainty' not in labels
    assert 'Cpu uncertainty' in labels
    assert 'Cpu 95% CI' in labels


def test_build_histogram_table_data_uses_cpl_for_one_sided_lower():
    payload = build_histogram_table_data(
        {
            'minimum': -0.06,
            'maximum': 0.0,
            'average': -0.03,
            'median': -0.03,
            'sigma': 0.01,
            'cp': 'N/A',
            'cpk': 0.0,
            'sample_size': 8,
            'nok_count': 0,
            'nok_pct': 0.0,
            'nom': 0.0,
            'lsl': -0.06,
            'usl': 0.0,
        }
    )

    labels = [label for label, _ in payload['rows']]
    assert ('Spec type', 'one-sided lower') in payload['rows']
    assert 'Cpl' in labels
    assert 'Cpl 95% CI' in labels


def test_build_histogram_table_data_supports_opt_out_of_capability_ci_annotations():
    payload = build_histogram_table_data(
        {
            'minimum': 1.0,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5,
            'cpk': 1.2,
            'sample_size': 50,
            'nok_count': 1,
            'nok_pct': 0.1,
            'include_capability_ci': False,
        }
    )

    rows = dict(payload['rows'])
    assert rows['Cp'] == '1.50'
    assert rows['Cpk'] == '1.20'
    assert 'Cp 95% CI' not in rows
    assert 'Cpk 95% CI' not in rows


def test_build_histogram_table_data_adds_obs_vs_est_comparison_rows():
    payload = build_histogram_table_data(
        {
            'minimum': 1.0,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5,
            'cpk': 1.2,
            'sample_size': 30,
            'nok_count': 3,
            'nok_pct': 0.1,
            'estimated_nok_pct': 0.12,
        }
    )

    rows = dict(payload['rows'])
    assert rows['NOK % (obs vs est)'] == 'Obs 10.00% vs Est 12.00%'
    assert rows['NOK % Δ (abs/rel)'] == '2.00 pp / 20.0%'


def test_build_histogram_table_data_flags_obs_vs_est_discrepancy_warning():
    payload = build_histogram_table_data(
        {
            'minimum': 1.0,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5,
            'cpk': 1.2,
            'sample_size': 30,
            'nok_count': 3,
            'nok_pct': 0.1,
            'estimated_nok_pct': 0.2,
        }
    )

    rows = dict(payload['rows'])
    assert rows['NOK % Δ (abs/rel)'].startswith('WARN: ')
    assert payload['summary_metrics']['nok_pct_discrepancy_warning'] is True


def test_build_histogram_table_data_includes_raw_rows_for_full_precision_tooltips():
    payload = build_histogram_table_data(
        {
            'minimum': 1.23456,
            'maximum': 3.0,
            'average': 2.0,
            'median': 2.0,
            'sigma': 0.1,
            'cp': 1.5555,
            'cpk': 1.2345,
            'sample_size': 10,
            'nok_count': 1,
            'nok_pct': 0.1,
        }
    )

    assert ('Min', 1.23456) in payload['raw_rows']
    assert payload['capability_rows']['Cpk']['raw_value'] == 1.2345
