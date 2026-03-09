import unittest

from modules import ui_theme_tokens


class TestUiThemeTokens(unittest.TestCase):
    def test_resolve_base_row_background_fallback_is_stable(self):
        self.assertEqual(ui_theme_tokens.resolve_base_row_background(None), '#FFFFFF')

    def test_themed_group_palette_is_stable_for_light_mode(self):
        palette = ui_theme_tokens.themed_group_palette(dark_mode=False)
        self.assertEqual(palette[:3], ['#FDE2E4', '#E2ECE9', '#E8E8FF'])

    def test_themed_group_palette_is_stable_for_dark_mode(self):
        palette = ui_theme_tokens.themed_group_palette(dark_mode=True)
        self.assertEqual(palette[:3], ['#B49C9E', '#9DA5A3', '#A1A1B5'])

    def test_generated_group_color_is_stable_across_modes(self):
        self.assertEqual(ui_theme_tokens.generate_group_color(8, dark_mode=False), '#EEDBD4')
        self.assertEqual(ui_theme_tokens.generate_group_color(8, dark_mode=True), '#A99892')


if __name__ == '__main__':
    unittest.main()
