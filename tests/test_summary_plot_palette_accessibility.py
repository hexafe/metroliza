import unittest

from modules.summary_plot_palette import SUMMARY_PLOT_PALETTE, STATUS_ICON_PREFIX_BY_PALETTE


def _relative_luminance(color_hex):
    rgb = [int(color_hex[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]

    def _convert(channel):
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    r, g, b = (_convert(channel) for channel in rgb)
    return (0.2126 * r) + (0.7152 * g) + (0.0722 * b)


def _contrast_ratio(color_a, color_b):
    l1 = _relative_luminance(color_a)
    l2 = _relative_luminance(color_b)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


class TestSummaryPlotPaletteAccessibility(unittest.TestCase):
    def test_status_palette_pairs_meet_wcag_aa_contrast(self):
        status_keys = sorted({key[:-3] for key in SUMMARY_PLOT_PALETTE if key.endswith('_bg') and f"{key[:-3]}_text" in SUMMARY_PLOT_PALETTE})
        for key in status_keys:
            with self.subTest(palette_key=key):
                ratio = _contrast_ratio(SUMMARY_PLOT_PALETTE[f'{key}_bg'], SUMMARY_PLOT_PALETTE[f'{key}_text'])
                self.assertGreaterEqual(ratio, 4.5)

    def test_all_status_palettes_have_text_prefix_icons(self):
        required_palettes = {
            'quality_capable', 'quality_good', 'quality_marginal', 'quality_risk', 'quality_unknown',
            'fit_quality_high', 'fit_quality_medium', 'fit_quality_low',
            'normality_normal', 'normality_unknown', 'normality_not_normal',
        }
        self.assertTrue(required_palettes.issubset(set(STATUS_ICON_PREFIX_BY_PALETTE.keys())))


if __name__ == '__main__':
    unittest.main()
