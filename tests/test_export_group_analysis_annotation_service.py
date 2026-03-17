import unittest

from modules.export_group_analysis_annotation_service import build_violin_group_annotation_payload


class TestExportGroupAnalysisAnnotationService(unittest.TestCase):
    def test_build_violin_group_annotation_payload_shape_and_sigma_modes(self):
        values = [[1.0, 1.2, 1.4], [2.0], []]
        positions = [0, 1, 2]

        two_sided = build_violin_group_annotation_payload(
            values,
            positions,
            show_sigma=True,
            one_sided_sigma_mode=False,
        )
        one_sided = build_violin_group_annotation_payload(
            values,
            positions,
            show_sigma=True,
            one_sided_sigma_mode=True,
        )

        self.assertEqual(len(two_sided), 2)
        self.assertEqual(two_sided[0]['position'], 0)
        self.assertAlmostEqual(two_sided[0]['mean'], 1.2)
        self.assertTrue(two_sided[0]['show_sigma_segment'])
        self.assertFalse(two_sided[1]['show_sigma_segment'])
        self.assertLess(two_sided[0]['sigma_start'], two_sided[0]['mean'])
        self.assertEqual(one_sided[0]['sigma_start'], one_sided[0]['mean'])


if __name__ == '__main__':
    unittest.main()
