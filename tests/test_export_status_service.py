import unittest

from modules.export_status_service import (
    build_measurement_status_label,
    clamp_progress,
    compute_stage_progress,
    format_elapsed_or_eta,
)


class TestExportStatusService(unittest.TestCase):
    def test_clamp_progress_bounds_values(self):
        self.assertEqual(clamp_progress(-3), 0)
        self.assertEqual(clamp_progress(49.6), 50)
        self.assertEqual(clamp_progress(104), 100)

    def test_compute_stage_progress_scales_fraction(self):
        ranges = {'stage': (10, 30)}
        self.assertEqual(compute_stage_progress(ranges, 'stage', fraction=0.0), 10)
        self.assertEqual(compute_stage_progress(ranges, 'stage', fraction=0.5), 20)
        self.assertEqual(compute_stage_progress(ranges, 'stage', fraction=1.0), 30)

    def test_format_elapsed_or_eta_formats_minutes_and_hours(self):
        self.assertEqual(format_elapsed_or_eta(61), '1:01')
        self.assertEqual(format_elapsed_or_eta(3661), '1:01:01')

    def test_build_measurement_status_label_uses_eta_placeholder_early(self):
        label = build_measurement_status_label(
            ref_index=1,
            total_references=3,
            completed_header_units=2,
            total_header_units=10,
            elapsed_seconds=1.0,
        )

        self.assertEqual(label.split('\n')[2], 'ETA --')

    def test_build_measurement_status_label_includes_elapsed_and_eta_when_stable(self):
        label = build_measurement_status_label(
            ref_index=2,
            total_references=3,
            completed_header_units=5,
            total_header_units=10,
            elapsed_seconds=10.0,
        )

        lines = label.split('\n')
        self.assertEqual(lines[0], 'Building measurement sheets...')
        self.assertIn('Ref 2/3', lines[1])
        self.assertIn('Headers remaining 5/10', lines[1])
        self.assertEqual(lines[2], '0:10 elapsed, ETA 0:10')


if __name__ == '__main__':
    unittest.main()
