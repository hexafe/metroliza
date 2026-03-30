import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

import pandas as pd

from modules.characteristic_alias_service import (
    ensure_characteristic_alias_schema,
    resolve_characteristic_alias,
    upsert_characteristic_alias,
)
from modules.group_analysis_service import (
    _resolve_canonical_metric_aliases,
    build_group_analysis_payload,
    build_metric_insights,
    build_pairwise_rows,
    classify_spec_status,
    classify_metric_spec_status,
    compute_capability_payload,
    get_spec_status_label,
    normalize_metric_identity,
    normalize_spec_limits,
    evaluate_group_analysis_readiness,
    resolve_group_analysis_scope,
)


class TestGroupAnalysisService(unittest.TestCase):
    def test_resolve_canonical_metric_aliases_matches_row_wise_behavior(self):
        frame = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-2', None, 'REF-1'],
            }
        )
        canonical_metric_series = pd.Series(['DIA - X', 'DIA - X', 'DIA - X', ''], index=frame.index)

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='GLOBAL DIA',
                scope_type='global',
            )
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='REF1 DIA',
                scope_type='reference',
                scope_value='REF-1',
            )

            expected = canonical_metric_series.fillna('').astype(str).str.strip().copy()
            reference_series = frame['REFERENCE'].fillna('').astype(str).str.strip()
            for row_index, metric_name in expected.items():
                if not metric_name:
                    continue
                reference_value = reference_series.get(row_index) or None
                expected.at[row_index] = resolve_characteristic_alias(metric_name, reference_value, db_path)

            actual = _resolve_canonical_metric_aliases(
                frame,
                canonical_metric_series,
                alias_db_path=db_path,
            )

        self.assertEqual(actual.tolist(), expected.tolist())

    def test_resolve_canonical_metric_aliases_without_reference_column_preserves_blank_metrics(self):
        frame = pd.DataFrame({'GROUP': ['A', 'A', 'B']})
        canonical_metric_series = pd.Series(['', 'DIA - X', '   '], index=frame.index)

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='GLOBAL DIA',
                scope_type='global',
            )

            resolved = _resolve_canonical_metric_aliases(
                frame,
                canonical_metric_series,
                alias_db_path=db_path,
            )

        self.assertEqual(resolved.tolist(), ['', 'GLOBAL DIA', ''])

    def test_build_payload_resolves_reference_scoped_metric_aliases(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-1', 'REF-1', 'REF-1'],
                'HEADER - AX': ['DIA - X'] * 4,
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.2, 9.8, 9.9],
                'LSL': [9.0] * 4,
                'NOMINAL': [10.0] * 4,
                'USL': [11.0] * 4,
            }
        )

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='DIAMETER - X',
                scope_type='reference',
                scope_value='REF-1',
            )

            payload = build_group_analysis_payload(
                grouped_df,
                requested_scope='single_reference',
                analysis_level='light',
                alias_db_path=db_path,
            )

        self.assertEqual(payload['metric_rows'][0]['metric'], 'DIAMETER - X')

    def test_build_payload_prefers_reference_alias_over_global_alias(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-1', 'REF-1', 'REF-1'],
                'HEADER - AX': ['DIA - X'] * 4,
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.2, 9.8, 9.9],
                'LSL': [9.0] * 4,
                'NOMINAL': [10.0] * 4,
                'USL': [11.0] * 4,
            }
        )

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='GLOBAL DIA',
                scope_type='global',
            )
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='REF DIA',
                scope_type='reference',
                scope_value='REF-1',
            )

            payload = build_group_analysis_payload(
                grouped_df,
                requested_scope='single_reference',
                analysis_level='light',
                alias_db_path=db_path,
            )

        self.assertEqual(payload['metric_rows'][0]['metric'], 'REF DIA')

    def test_build_payload_multi_reference_applies_reference_specific_aliases_per_reference(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1', 'REF-1', 'REF-2', 'REF-2'],
                'HEADER - AX': ['DIA - X'] * 4,
                'GROUP': ['A', 'B', 'A', 'B'],
                'MEAS': [10.0, 10.1, 9.9, 10.2],
                'LSL': [9.0] * 4,
                'NOMINAL': [10.0] * 4,
                'USL': [11.0] * 4,
            }
        )

        with TemporaryDirectory() as tmpdir:
            db_path = f'{tmpdir}/aliases.sqlite'
            ensure_characteristic_alias_schema(db_path)
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='GLOBAL DIA',
                scope_type='global',
            )
            upsert_characteristic_alias(
                db_path,
                alias_name='DIA - X',
                canonical_name='REF1 DIA',
                scope_type='reference',
                scope_value='REF-1',
            )

            payload = build_group_analysis_payload(
                grouped_df,
                requested_scope='multi_reference',
                analysis_level='light',
                alias_db_path=db_path,
            )

        metric_names = sorted(row['metric'] for row in payload['metric_rows'])
        self.assertEqual(metric_names, ['REF-1 :: REF1 DIA', 'REF-2 :: GLOBAL DIA'])


    def test_build_payload_keeps_metric_identity_when_no_alias_mapping_exists(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-2', 'REF-2', 'REF-2', 'REF-2'],
                'HEADER - AX': ['CYL - Y'] * 4,
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [5.0, 5.1, 5.2, 5.3],
                'LSL': [4.0] * 4,
                'NOMINAL': [5.0] * 4,
                'USL': [6.0] * 4,
            }
        )

        payload = build_group_analysis_payload(
            grouped_df,
            requested_scope='single_reference',
            analysis_level='light',
            alias_db_path=None,
        )

        self.assertEqual(payload['metric_rows'][0]['metric'], 'CYL - Y')

    @patch('modules.group_analysis_service.compute_pairwise_rows')
    def test_build_pairwise_rows_emits_difference_and_standardized_comment(self, mock_compute_pairwise_rows):
        mock_compute_pairwise_rows.return_value = [
            {
                'group_a': 'A',
                'group_b': 'B',
                'adjusted_p_value': 0.012345,
                'effect_size': 0.81234,
                'p_value': 0.01,
                'test_used': 'welch_t',
                'significant': True,
            },
            {
                'group_a': 'A',
                'group_b': 'C',
                'adjusted_p_value': 0.456789,
                'effect_size': 0.12345,
                'p_value': 0.4,
                'test_used': 'welch_t',
                'significant': False,
            },
            {
                'group_a': 'B',
                'group_b': 'C',
                'adjusted_p_value': None,
                'effect_size': None,
                'p_value': None,
                'test_used': 'welch_t',
                'significant': True,
            },
        ]

        rows = build_pairwise_rows(
            'M1',
            {'A': [10.0, 10.1, 10.2, 10.3, 10.4], 'B': [9.7, 9.8, 9.9, 10.0, 10.1], 'C': [9.9, 10.0, 10.1, 10.2, 10.3]},
            pairwise_eligible=True,
        )

        self.assertEqual(rows[0]['difference'], 'YES')
        self.assertEqual(rows[0]['comment'], 'DIFFERENCE')
        self.assertEqual(rows[0]['adjusted_p_value'], 0.0123)
        self.assertEqual(rows[0]['effect_size'], 0.812)
        self.assertEqual(rows[1]['difference'], 'NO')
        self.assertEqual(rows[1]['comment'], 'NO DIFFERENCE')
        self.assertEqual(rows[1]['adjusted_p_value'], 0.4568)
        self.assertEqual(rows[1]['effect_size'], 0.123)
        self.assertEqual(rows[2]['difference'], 'YES')
        self.assertEqual(rows[2]['comment'], 'DIFFERENCE')
        self.assertNotIn('significant', rows[0])

    @patch('modules.group_analysis_service.compute_pairwise_rows')
    def test_build_pairwise_rows_rounds_delta_mean_to_three_decimals(self, mock_compute_pairwise_rows):
        mock_compute_pairwise_rows.return_value = [
            {
                'group_a': 'A',
                'group_b': 'B',
                'adjusted_p_value': 0.5,
                'effect_size': 0.2,
                'p_value': 0.5,
                'test_used': 'welch_t',
                'significant': False,
            }
        ]

        rows = build_pairwise_rows(
            'M1',
            {'A': [1.0], 'B': [2.0 / 3.0]},
            pairwise_eligible=True,
        )

        self.assertEqual(rows[0]['delta_mean'], 0.333)

    @patch('modules.group_analysis_service.compute_pairwise_rows')
    def test_build_pairwise_rows_marks_descriptive_only_when_pairwise_is_ineligible(self, mock_compute_pairwise_rows):
        mock_compute_pairwise_rows.return_value = [
            {
                'group_a': 'A',
                'group_b': 'B',
                'adjusted_p_value': 0.012345,
                'effect_size': 0.81234,
                'p_value': 0.01,
                'test_used': 'welch_t',
                'significant': True,
            }
        ]

        rows = build_pairwise_rows('M1', {'A': [10.0], 'B': [9.0]}, pairwise_eligible=False)

        self.assertEqual(rows[0]['difference'], 'NO')
        self.assertEqual(rows[0]['comment'], 'DESCRIPTIVE ONLY')


    def test_build_group_flags_use_spec_threshold_vocabulary(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 20,
                'HEADER - AX': ['M1'] * 20,
                'GROUP': ['A'] * 4 + ['B'] * 12 + ['C'] * 4,
                'MEAS': [10.0 + 0.01 * i for i in range(20)],
                'LSL': [9.0] * 20,
                'NOMINAL': [10.0] * 20,
                'USL': [11.0] * 20,
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')
        metric = payload['metric_rows'][0]
        self.assertTrue(all('LOW N' in row['flags'] for row in metric['descriptive_stats'] if row['group'] in {'A', 'C'}))
        self.assertTrue(any('SEVERELY IMBALANCED N' in row['flags'] for row in metric['descriptive_stats']))

    def test_pairwise_flags_include_spec_question_for_spec_mismatch_light(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 10,
                'HEADER - AX': ['M1'] * 10,
                'GROUP': ['A'] * 5 + ['B'] * 5,
                'MEAS': [10.0, 10.1, 9.9, 10.2, 9.8, 9.4, 9.5, 9.6, 9.7, 9.8],
                'LSL': [9.0] * 10,
                'NOMINAL': [10.0] * 5 + [10.2] * 5,
                'USL': [11.0] * 10,
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['spec_status'], 'NOM_MISMATCH')
        self.assertEqual(len(metric['pairwise_rows']), 0)
        self.assertTrue(all('SPEC?' in row['flags'] for row in metric['descriptive_stats']))
    def test_build_payload_adds_distribution_summary_fields(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 12,
                'HEADER - AX': ['M1'] * 12,
                'GROUP': ['A'] * 6 + ['B'] * 6,
                'MEAS': [10.0, 10.1, 10.2, 9.9, 10.0, 10.3, 9.0, 9.2, 9.1, 9.3, 9.4, 9.1],
                'LSL': [8.0] * 12,
                'NOMINAL': [10.0] * 12,
                'USL': [12.0] * 12,
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')

        metric = payload['metric_rows'][0]
        self.assertIn('distribution_difference', metric)
        self.assertIn('comment / verdict', metric['distribution_difference'])
        self.assertTrue(all('best_fit_model' in row for row in metric['descriptive_stats']))
        self.assertTrue(all('fit_quality' in row for row in metric['descriptive_stats']))
        self.assertTrue(all('distribution_shape_caution' in row for row in metric['descriptive_stats']))
        self.assertTrue(all(row['distribution_shape_caution'] != 'AD p-value estimated via KS proxy; set monte_carlo_gof_samples>0 for bootstrap.' for row in metric['descriptive_stats']))
        self.assertTrue(all('test_rationale' in row for row in metric['pairwise_rows']))


    def test_auto_scope_resolution_uses_reference_cardinality(self):
        self.assertEqual(resolve_group_analysis_scope('auto', 1), 'single_reference')
        self.assertEqual(resolve_group_analysis_scope('auto', 2), 'multi_reference')

    def test_forced_scope_mismatch_returns_canonical_skip_reason(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R2'],
                'GROUP': ['A', 'B'],
                'MEAS': [1.0, 2.0],
                'HEADER': ['M1', 'M1'],
            }
        )

        result = evaluate_group_analysis_readiness(grouped_df, requested_scope='single_reference')

        self.assertFalse(result['runnable'])
        self.assertEqual(result['skip_reason']['code'], 'forced_single_reference_scope_mismatch')
        self.assertEqual(
            result['skip_reason']['message'],
            'Single-reference group analysis skipped: grouped rows span multiple references.',
        )

    def test_forced_multi_reference_scope_mismatch_returns_canonical_skip_reason(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1'],
                'GROUP': ['A', 'B'],
                'MEAS': [1.0, 2.0],
                'HEADER': ['M1', 'M1'],
            }
        )

        result = evaluate_group_analysis_readiness(grouped_df, requested_scope='multi_reference')

        self.assertFalse(result['runnable'])
        self.assertEqual(result['skip_reason']['code'], 'forced_multi_reference_scope_mismatch')
        self.assertEqual(
            result['skip_reason']['message'],
            'Multi-reference group analysis skipped: grouped rows span only one reference.',
        )

    def test_metric_identity_includes_reference_for_multi_scope(self):
        self.assertEqual(
            normalize_metric_identity('DIA - X', 'REF-A', scope='multi_reference'),
            'REF-A :: DIA - X',
        )
        self.assertEqual(normalize_metric_identity('DIA - X', 'REF-A', scope='single_reference'), 'DIA - X')


    def test_get_spec_status_label_maps_internal_codes_to_user_facing_values(self):
        self.assertEqual(get_spec_status_label('EXACT_MATCH'), 'Exact match')
        self.assertEqual(get_spec_status_label('LIMIT_MISMATCH'), 'Limits differ')
        self.assertEqual(get_spec_status_label('NOM_MISMATCH'), 'Nominal differs')
        self.assertEqual(get_spec_status_label('INVALID_SPEC'), 'Spec missing / Invalid spec.')
        self.assertEqual(get_spec_status_label(None), 'Spec missing / Invalid spec.')

    def test_spec_normalization_and_status_classification(self):
        spec = normalize_spec_limits('1.23456', 2, '3.4567')
        self.assertEqual(spec, {'lsl': 1.235, 'nominal': 2.0, 'usl': 3.457})
        self.assertIsInstance(spec['lsl'], float)
        self.assertEqual(classify_spec_status(spec), 'EXACT_MATCH')
        self.assertEqual(classify_spec_status({'lsl': None, 'nominal': None, 'usl': None}), 'INVALID_SPEC')
        self.assertEqual(classify_spec_status({'lsl': 1.0, 'nominal': None, 'usl': 3.0}), 'INVALID_SPEC')

    def test_spec_status_comparison_uses_numeric_3_decimal_normalization(self):
        metric_rows_df = pd.DataFrame(
            {
                'LSL': [1.0004, 1.00049],
                'NOMINAL': [2.0004, 2.00049],
                'USL': [3.0004, 3.00049],
            }
        )

        status, canonical = classify_metric_spec_status(
            metric_rows_df,
            {'lsl': 'LSL', 'nominal': 'NOMINAL', 'usl': 'USL'},
        )

        self.assertEqual(status, 'EXACT_MATCH')
        self.assertEqual(canonical, {'lsl': 1.0, 'nominal': 2.0, 'usl': 3.0})
        self.assertTrue(all(isinstance(value, float) for value in canonical.values()))

    def test_classify_metric_spec_status_detects_mismatch_types(self):
        metric_rows_df = pd.DataFrame(
            {
                'LSL': [1.0, 1.0],
                'NOMINAL': [2.0, 2.2],
                'USL': [3.0, 3.0],
            }
        )
        status, _ = classify_metric_spec_status(
            metric_rows_df,
            {'lsl': 'LSL', 'nominal': 'NOMINAL', 'usl': 'USL'},
        )
        self.assertEqual(status, 'NOM_MISMATCH')

        metric_rows_df['NOMINAL'] = [2.0, 2.0]
        metric_rows_df['USL'] = [3.0, 3.1]
        status, _ = classify_metric_spec_status(
            metric_rows_df,
            {'lsl': 'LSL', 'nominal': 'NOMINAL', 'usl': 'USL'},
        )
        self.assertEqual(status, 'LIMIT_MISMATCH')

    def test_classify_metric_spec_status_matches_legacy_outputs_for_mixed_validity_rows(self):
        def legacy_classify(metric_rows_df, spec_columns):
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

        fixture_frames = [
            pd.DataFrame({'LSL': [1, 1], 'NOMINAL': [2, 2], 'USL': [3, 3]}),
            pd.DataFrame({'LSL': [1, 1], 'NOMINAL': [2, 2.1], 'USL': [3, 3]}),
            pd.DataFrame({'LSL': [1, 1.1], 'NOMINAL': [2, 2], 'USL': [3, 3.1]}),
            pd.DataFrame({'LSL': [1, 'bad'], 'NOMINAL': [2, 2], 'USL': [3, 3]}),
            pd.DataFrame({'LSL': [4, 4], 'NOMINAL': [2, 2], 'USL': [3, 3]}),
            pd.DataFrame({'LSL': [1.00049, 1.0004], 'NOMINAL': [2.00049, 2.0004], 'USL': [3.00049, 3.0004]}),
            pd.DataFrame({'LSL': ['1.5', '1.5'], 'NOMINAL': ['1.4', '1.5'], 'USL': ['1.7', '1.7']}),
        ]
        spec_columns = {'lsl': 'LSL', 'nominal': 'NOMINAL', 'usl': 'USL'}

        for fixture in fixture_frames:
            with self.subTest(frame=fixture.to_dict(orient='list')):
                legacy_status, legacy_canonical = legacy_classify(fixture, spec_columns)
                status, canonical = classify_metric_spec_status(fixture, spec_columns)
                self.assertEqual(status, legacy_status)
                self.assertEqual(canonical, legacy_canonical)

    def test_capability_payload_marks_not_applicable_without_valid_spec(self):
        payload = compute_capability_payload([1.0, 1.1, 1.2], {'lsl': None, 'nominal': None, 'usl': None})
        self.assertEqual(payload['status'], 'not_applicable')
        self.assertIsNone(payload['cp'])
        self.assertIsNone(payload['capability'])
        self.assertIsNone(payload['cpk'])

    def test_capability_payload_bilateral_mode_returns_cp_and_cpk(self):
        payload = compute_capability_payload([9.9, 10.0, 10.1, 10.2], {'lsl': 9.0, 'nominal': 10.0, 'usl': 11.0})

        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['capability_mode'], 'bilateral')
        self.assertEqual(payload['capability_type'], 'Cpk')
        self.assertIsNotNone(payload['cp'])
        self.assertIsNotNone(payload['capability'])
        self.assertIsNotNone(payload['cpk'])
        self.assertIsInstance(payload['capability_ci']['cp'], dict)
        self.assertIsInstance(payload['capability_ci']['cpk'], dict)

    def test_capability_payload_upper_only_mode_returns_cpk_plus(self):
        payload = compute_capability_payload([9.9, 10.0, 10.1, 10.2], {'lsl': None, 'nominal': 10.0, 'usl': 11.0})

        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['capability_mode'], 'upper_only')
        self.assertEqual(payload['capability_type'], 'Cpk+')
        self.assertIsNone(payload['cp'])
        self.assertIsNotNone(payload['capability'])
        self.assertEqual(payload['capability'], payload['cpk'])
        self.assertIsNone(payload['capability_ci']['cp'])
        self.assertIsInstance(payload['capability_ci']['cpk'], dict)

    def test_capability_payload_lower_only_mode_returns_cpk_minus(self):
        payload = compute_capability_payload([9.9, 10.0, 10.1, 10.2], {'lsl': 9.0, 'nominal': 10.0, 'usl': None})

        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['capability_mode'], 'lower_only')
        self.assertEqual(payload['capability_type'], 'Cpk-')
        self.assertIsNone(payload['cp'])
        self.assertIsNotNone(payload['capability'])
        self.assertEqual(payload['capability'], payload['cpk'])

    def test_capability_payload_forces_not_applicable_for_non_positive_sigma(self):
        payload = compute_capability_payload([1.0, 1.0, 1.0], {'lsl': 0.0, 'nominal': 1.0, 'usl': 2.0})

        self.assertEqual(payload['status'], 'not_applicable')
        self.assertEqual(payload['capability_mode'], 'bilateral')
        self.assertIsNone(payload['cp'])
        self.assertIsNone(payload['capability'])
        self.assertIsNone(payload['cpk'])

    def test_capability_payload_forces_not_applicable_for_invalid_limit_order(self):
        payload = compute_capability_payload([1.0, 1.1, 1.2], {'lsl': 3.0, 'nominal': 2.0, 'usl': 1.0})

        self.assertEqual(payload['status'], 'not_applicable')
        self.assertEqual(payload['capability_mode'], 'bilateral')
        self.assertIsNone(payload['cp'])
        self.assertIsNone(payload['capability'])
        self.assertIsNone(payload['cpk'])

    def test_build_payload_includes_descriptive_pairwise_and_diagnostics(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R1'],
                'HEADER - AX': ['M1', 'M1', 'M1', 'M1'],
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.2, 9.7, 9.6],
                'LSL': [9.0, 9.0, 9.0, 9.0],
                'NOMINAL': [10.0, 10.0, 10.0, 10.0],
                'USL': [11.0, 11.0, 11.0, 11.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['effective_scope'], 'single_reference')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['metric'], 'M1')
        self.assertEqual(metric['spec_status'], 'EXACT_MATCH')
        self.assertEqual(len(metric['descriptive_stats']), 2)
        self.assertEqual(len(metric['pairwise_rows']), 1)
        self.assertIn('comparability_summary', metric)
        self.assertGreaterEqual(len(metric.get('insights', [])), 1)
        self.assertIn('median', metric['descriptive_stats'][0])
        self.assertIn('iqr', metric['descriptive_stats'][0])
        self.assertIn('flags', metric['descriptive_stats'][0])
        self.assertIn('capability_ci', metric['descriptive_stats'][0])
        self.assertIn('delta_mean', metric['pairwise_rows'][0])
        self.assertIn('difference', metric['pairwise_rows'][0])
        self.assertIn('comment', metric['pairwise_rows'][0])
        self.assertNotIn('significant', metric['pairwise_rows'][0])
        self.assertAlmostEqual(metric['descriptive_stats'][0]['mean'], round(metric['descriptive_stats'][0]['mean'], 3))
        self.assertAlmostEqual(
            metric['pairwise_rows'][0]['effect_size'],
            round(metric['pairwise_rows'][0]['effect_size'], 3),
        )
        self.assertAlmostEqual(
            metric['pairwise_rows'][0]['adjusted_p_value'],
            round(metric['pairwise_rows'][0]['adjusted_p_value'], 4),
        )
        self.assertEqual(payload['diagnostics']['metric_count'], 1)
        self.assertEqual(payload['diagnostics']['status_counts']['EXACT_MATCH'], 1)
        self.assertEqual(payload['diagnostics']['requested_level'], 'light')
        self.assertEqual(payload['diagnostics']['execution_status'], 'ran')
        self.assertEqual(payload['diagnostics']['group_count'], 2)
        self.assertEqual(payload['diagnostics']['warning_summary']['count'], 0)
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['applies'], False)
        self.assertEqual(payload['diagnostics']['unmatched_metrics_summary']['count'], 0)
        diagnostics_row = payload['diagnostics']['metric_diagnostics_rows'][0]
        self.assertEqual(diagnostics_row['spec_status_label'], 'Exact match')
        self.assertEqual(diagnostics_row['included_in_light'], 'YES')
        self.assertEqual(diagnostics_row['included_in_standard'], 'YES')
        self.assertIn('Analyzed', diagnostics_row['comment'])

    def test_standard_level_limit_mismatch_is_included_with_pairwise_and_capability_disabled(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['C-F2'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [10.0, 10.2, 10.1, 10.3, 9.7, 9.8, 9.9, 9.6],
                'LSL': [9.0] * 8,
                'NOMINAL': [10.0] * 8,
                'USL': [11.0] * 4 + [11.5] * 4,
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='standard')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['spec_status'], 'LIMIT_MISMATCH')
        self.assertTrue(metric['analysis_policy']['include_metric'])
        self.assertTrue(metric['analysis_policy']['allow_pairwise'])
        self.assertFalse(metric['analysis_policy']['allow_capability'])
        self.assertEqual(metric['spec_status_label'], 'Limits differ')
        self.assertEqual(metric['analysis_restriction_label'], 'Pairwise yes; capability off')
        self.assertTrue(metric['pairwise_allowed'])
        self.assertFalse(metric['capability_allowed'])
        self.assertGreater(len(metric['pairwise_rows']), 0)
        self.assertEqual(len(metric['descriptive_stats']), 2)
        self.assertTrue(all(row['cp'] is None for row in metric['descriptive_stats']))
        self.assertTrue(all(row['capability'] is None for row in metric['descriptive_stats']))
        self.assertEqual(metric['capability']['status'], 'not_applicable')
        self.assertIsNone(metric['capability']['cp'])
        self.assertIsNone(metric['capability']['capability'])
        diagnostics_row = payload['diagnostics']['metric_diagnostics_rows'][0]
        self.assertEqual(diagnostics_row['included_in_standard'], 'YES')
        self.assertIn('capability metrics are disabled', diagnostics_row['comment'])
        self.assertNotIn('Skipped in Standard', diagnostics_row['comment'])

    def test_standard_level_nominal_mismatch_remains_descriptive_only(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['M1'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [10.0, 10.2, 10.1, 10.3, 9.7, 9.8, 9.9, 9.6],
                'LSL': [9.0] * 8,
                'NOMINAL': [10.0] * 4 + [10.1] * 4,
                'USL': [11.0] * 8,
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='standard')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['spec_status'], 'NOM_MISMATCH')
        self.assertTrue(metric['analysis_policy']['include_metric'])
        self.assertFalse(metric['analysis_policy']['allow_pairwise'])
        self.assertFalse(metric['analysis_policy']['allow_capability'])
        self.assertEqual(metric['analysis_restriction_label'], 'Descriptive only')
        self.assertEqual(metric['pairwise_rows'], [])
        self.assertEqual(len(metric['descriptive_stats']), 2)
        diagnostics_row = payload['diagnostics']['metric_diagnostics_rows'][0]
        self.assertEqual(diagnostics_row['spec_status_label'], 'Nominal differs')
        self.assertEqual(diagnostics_row['included_in_light'], 'YES')
        self.assertEqual(diagnostics_row['included_in_standard'], 'YES')
        self.assertIn('Descriptive-only', diagnostics_row['comment'])


    def test_metric_index_helper_fields_reflect_analysis_restrictions(self):
        limit_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['C-F2'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [10.0, 10.2, 10.1, 10.3, 9.7, 9.8, 9.9, 9.6],
                'LSL': [9.0] * 8,
                'NOMINAL': [10.0] * 8,
                'USL': [11.0] * 4 + [11.5] * 4,
            }
        )
        nom_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['NOM-ONLY'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [5.0, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7],
                'LSL': [4.0] * 8,
                'NOMINAL': [5.0] * 4 + [5.2] * 4,
                'USL': [6.0] * 8,
            }
        )

        limit_metric = build_group_analysis_payload(limit_df, requested_scope='auto', analysis_level='standard')['metric_rows'][0]
        nom_metric = build_group_analysis_payload(nom_df, requested_scope='auto', analysis_level='standard')['metric_rows'][0]

        self.assertEqual(limit_metric['spec_status_label'], 'Limits differ')
        self.assertEqual(limit_metric['analysis_restriction_label'], 'Pairwise yes; capability off')
        self.assertEqual(nom_metric['spec_status_label'], 'Nominal differs')
        self.assertEqual(nom_metric['analysis_restriction_label'], 'Descriptive only')

    def test_diagnostics_comments_match_spec_policy_language(self):
        limit_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['LIMIT'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [10.0, 10.2, 10.1, 10.3, 9.7, 9.8, 9.9, 9.6],
                'LSL': [9.0] * 8,
                'NOMINAL': [10.0] * 8,
                'USL': [11.0] * 4 + [11.5] * 4,
            }
        )
        nom_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['NOM'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [5.0, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7],
                'LSL': [4.0] * 8,
                'NOMINAL': [5.0] * 4 + [5.2] * 4,
                'USL': [6.0] * 8,
            }
        )
        invalid_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['INVALID'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [3.0, 3.1, 3.2, 3.3, 2.8, 2.9, 3.0, 3.1],
                'LSL': [None] * 8,
                'NOMINAL': [None] * 8,
                'USL': [None] * 8,
            }
        )

        limit_comment = build_group_analysis_payload(limit_df, requested_scope='auto', analysis_level='standard')['metric_rows'][0]['diagnostics_comment']
        nom_comment = build_group_analysis_payload(nom_df, requested_scope='auto', analysis_level='standard')['metric_rows'][0]['diagnostics_comment']
        invalid_comment = build_group_analysis_payload(invalid_df, requested_scope='auto', analysis_level='standard')['metric_rows'][0]['diagnostics_comment']

        self.assertNotIn('Skipped in Standard', limit_comment)
        self.assertIn('pairwise comparison is allowed', limit_comment)
        self.assertIn('capability metrics are disabled', limit_comment)
        self.assertIn('Descriptive-only', nom_comment)
        self.assertIn('nominal differs across groups', nom_comment)
        self.assertIn('Descriptive-only', invalid_comment)
        self.assertIn('spec missing/invalid', invalid_comment)

    def test_standard_level_includes_histogram_skip_reason_for_included_metrics(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R1'],
                'HEADER - AX': ['M1', 'M1', 'M1', 'M1'],
                'GROUP': ['A', 'A', 'B', 'B'],
                'MEAS': [10.0, 10.2, 9.7, 9.6],
                'LSL': [9.0, 9.0, 9.0, 9.0],
                'NOMINAL': [10.0, 10.0, 10.0, 10.0],
                'USL': [11.0, 11.0, 11.0, 11.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='standard')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['analysis_level'], 'standard')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertFalse(metric['plot_eligibility']['violin']['eligible'])
        self.assertEqual(metric['plot_eligibility']['violin']['skip_reason'], 'low_group_samples')
        self.assertFalse(metric['plot_eligibility']['histogram']['eligible'])
        self.assertEqual(metric['plot_eligibility']['histogram']['skip_reason'], 'low_total_samples')
        self.assertIn('Histogram omitted', metric['diagnostics_comment'])
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['count'], 1)
        self.assertEqual(payload['diagnostics']['histogram_skip_summary']['reason_counts'], {'low_total_samples': 1})

    def test_diagnostics_include_warning_and_unmatched_reference_summaries(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R2', 'R2'],
                'HEADER - AX': ['M1', 'M1', 'M2', 'M1', 'M1'],
                'GROUP': ['A', 'B', 'A', 'A', 'B'],
                'MEAS': [10.0, 10.2, 9.5, 10.1, 10.3],
                'LSL': [9.0, 9.1, 9.0, 9.0, 9.0],
                'NOMINAL': [10.0, 10.0, 10.0, 10.0, 10.0],
                'USL': [11.0, 11.0, 11.0, 11.0, 11.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')
        diagnostics = payload['diagnostics']

        self.assertEqual(diagnostics['warning_summary']['count'], 3)
        self.assertEqual(len(diagnostics['warning_summary']['messages']), 2)
        self.assertEqual(diagnostics['warning_summary']['skip_reason_counts'], {'insufficient_groups': 1})
        self.assertEqual(diagnostics['unmatched_metrics_summary']['count'], 1)
        self.assertEqual(diagnostics['unmatched_metrics_summary']['metrics'][0]['metric'], 'M2')
        self.assertEqual(diagnostics['unmatched_metrics_summary']['metrics'][0]['missing_references'], ['R2'])
        self.assertTrue(any('M2' in str(row.get('metric')) for row in diagnostics['metric_diagnostics_rows']))


    def test_axis_metric_uses_canonical_identity_and_derived_spec_columns(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1', 'R1', 'R1', 'R1'],
                'HEADER': ['AA-C11', 'AA-C11', 'AA-C11', 'AA-C11'],
                'AX': ['TP', 'TP', 'TP', 'TP'],
                'GROUP': ['G1', 'G1', 'G2', 'G2'],
                'MEAS': [0.10, 0.12, 0.09, 0.11],
                'NOM': [0.0, 0.0, 0.0, 0.0],
                '+TOL': [0.5, 0.5, 0.5, 0.5],
                '-TOL': [0.0, 0.0, 0.0, 0.0],
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='standard')

        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(len(payload['metric_rows']), 1)
        metric = payload['metric_rows'][0]
        self.assertEqual(metric['metric'], 'AA-C11 - TP')
        self.assertEqual(metric['spec_status'], 'EXACT_MATCH')
        self.assertEqual(metric['spec_status_label'], 'Exact match')
        self.assertEqual(metric['spec'], {'lsl': 0.0, 'nominal': 0.0, 'usl': 0.5})

        diagnostics_row = payload['diagnostics']['metric_diagnostics_rows'][0]
        self.assertEqual(diagnostics_row['metric'], 'AA-C11 - TP')
        self.assertEqual(diagnostics_row['spec_status'], 'EXACT_MATCH')
        self.assertEqual(diagnostics_row['included_in_light'], 'YES')
        self.assertEqual(diagnostics_row['included_in_standard'], 'YES')

    def test_header_only_identity_would_merge_axes_but_canonical_identity_keeps_them_separate(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER': ['AA-C11'] * 8,
                'AX': ['TP', 'TP', 'TP', 'TP', 'SP', 'SP', 'SP', 'SP'],
                'GROUP': ['G1', 'G1', 'G2', 'G2', 'G1', 'G1', 'G2', 'G2'],
                'MEAS': [0.10, 0.11, 0.09, 0.12, 0.20, 0.22, 0.19, 0.21],
                'NOM': [0.0] * 8,
                '+TOL': [0.5, 0.5, 0.5, 0.5, 0.8, 0.8, 0.8, 0.8],
                '-TOL': [0.0] * 8,
            }
        )

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='standard')

        metric_names = sorted(row['metric'] for row in payload['metric_rows'])
        self.assertEqual(metric_names, ['AA-C11 - SP', 'AA-C11 - TP'])
        self.assertEqual(payload['diagnostics']['metric_count'], 2)
        self.assertEqual(payload['diagnostics']['status_counts']['EXACT_MATCH'], 2)


    def test_build_metric_insights_prioritizes_shape_with_three_line_cap(self):
        metric_row = {
            'spec_status': 'EXACT_MATCH',
            'analysis_restriction_label': 'Full analysis',
            'comparability_summary': {'status': 'EXACT_MATCH', 'interpretation_limits': 'none'},
            'descriptive_stats': [
                {'group': 'A', 'mean': 10.2},
                {'group': 'B', 'mean': 9.7},
            ],
            'pairwise_rows': [
                {'group_a': 'A', 'group_b': 'B', 'adjusted_p_value': 0.0009, 'comment': 'DIFFERENCE'},
            ],
            'distribution_difference': {'comment / verdict': 'Clear shape mismatch across groups.'},
            'analysis_policy': {'allow_pairwise': True},
        }

        insights = build_metric_insights(metric_row)

        self.assertEqual(len(insights), 3)
        self.assertEqual(insights[0], 'Status: Exact match; mode=Full analysis.')
        self.assertEqual(insights[1], 'Primary signal: A vs B is DIFFERENCE (adj p=0.0009).')
        self.assertEqual(insights[2], 'Shape signal: Clear shape mismatch across groups.')

    @patch('modules.group_analysis_service.compute_distribution_difference')
    @patch('modules.group_analysis_service.compute_pairwise_rows')
    def test_shape_only_metrics_surface_caution_status_takeaway_and_action(self, mock_compute_pairwise_rows, mock_distribution_difference):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['R1'] * 8,
                'HEADER - AX': ['M1'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [10.0, 10.1, 10.2, 10.0, 9.9, 10.0, 10.1, 9.9],
                'LSL': [9.0] * 8,
                'NOMINAL': [10.0] * 8,
                'USL': [11.0] * 8,
            }
        )
        mock_compute_pairwise_rows.return_value = []
        mock_distribution_difference.return_value = {
            'profile_rows': [],
            'pairwise_rows': [],
            'omnibus_row': {
                'Metric': 'M1',
                'Test used': 'Kolmogorov-Smirnov (2-sample)',
                'raw p-value': 0.004,
                'adjusted p-value': 0.004,
                'significant?': 'YES',
                'warning / assumptions': 'None',
                'comment / verdict': 'Clear shape mismatch across groups.',
            },
        }

        payload = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')

        metric = payload['metric_rows'][0]
        self.assertEqual(metric['index_status'], 'USE CAUTION')
        self.assertEqual(
            metric['recommended_action'],
            'Recommended action: review spread and consistency by group; averages may look similar, but the distribution pattern differs.',
        )
        self.assertEqual(
            metric['metric_takeaway'],
            'Clear shape mismatch across groups. Review spread and consistency by group.',
        )
        self.assertEqual(metric['insights'][2], 'Shape signal: Clear shape mismatch across groups.')

    def test_build_group_analysis_payload_cache_hits_preserve_payload_parity(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1'] * 8,
                'HEADER - AX': ['DIA - X'] * 8,
                'GROUP': ['A'] * 4 + ['B'] * 4,
                'MEAS': [10.0, 10.1, 10.2, 10.3, 9.7, 9.8, 9.9, 10.0],
                'LSL': [9.0] * 8,
                'NOMINAL': [10.0] * 8,
                'USL': [11.0] * 8,
            }
        )

        fit_result = {
            'status': 'ok',
            'fit_quality': {'label': 'good'},
            'gof_metrics': {'ad_pvalue': 0.2, 'ks_pvalue': 0.3, 'is_acceptable': True},
            'selected_model': {'display_name': 'Normal'},
            'inferred_support_mode': 'unbounded',
            'notes': ['Use fit quality as guidance only.'],
        }

        with patch('modules.distribution_shape_analysis.fit_measurement_distribution', return_value=fit_result) as mock_fit:
            first = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')
            second = build_group_analysis_payload(grouped_df, requested_scope='auto', analysis_level='light')

        self.assertEqual(first, second)
        self.assertEqual(mock_fit.call_count, 4)

    def test_build_group_analysis_payload_can_skip_distribution_fits_for_large_exports(self):
        grouped_df = pd.DataFrame(
            {
                'REFERENCE': ['REF-1'] * 120,
                'HEADER - AX': ['DIA - X'] * 120,
                'GROUP': ['A'] * 60 + ['B'] * 60,
                'MEAS': [10.0 + (i / 100.0) for i in range(60)] + [9.4 + (i / 100.0) for i in range(60)],
                'LSL': [9.0] * 120,
                'NOMINAL': [10.0] * 120,
                'USL': [11.0] * 120,
            }
        )

        payload = build_group_analysis_payload(
            grouped_df,
            requested_scope='auto',
            analysis_level='light',
            distribution_fit_policy={'mode': 'skip_large_exports', 'max_fit_samples_per_metric': 100},
        )

        metric = payload['metric_rows'][0]
        self.assertEqual(metric['descriptive_stats'][0]['best_fit_model'], 'Skipped by policy')
        self.assertEqual(metric['descriptive_stats'][0]['fit_quality'], 'not run')
        self.assertTrue(metric['distribution_pairwise_rows'])
        self.assertIsNotNone(metric['distribution_pairwise_rows'][0]['Wasserstein distance'])


if __name__ == '__main__':
    unittest.main()
