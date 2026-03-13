import unittest

from modules import ui_theme_tokens


class TestUiThemeTokens(unittest.TestCase):
    def test_dark_theme_core_tokens_match_spec(self):
        self.assertEqual(ui_theme_tokens.COLOR_BACKGROUND_APP, '#121417')
        self.assertEqual(ui_theme_tokens.COLOR_BACKGROUND_PANEL, '#1B1F24')
        self.assertEqual(ui_theme_tokens.COLOR_BACKGROUND_PANEL_MUTED, '#232933')
        self.assertEqual(ui_theme_tokens.COLOR_BACKGROUND_PANEL_ELEVATED, '#2A3140')
        self.assertEqual(ui_theme_tokens.COLOR_BACKGROUND_INPUT, '#20262F')
        self.assertEqual(ui_theme_tokens.COLOR_BORDER_DEFAULT, '#364152')
        self.assertEqual(ui_theme_tokens.COLOR_BORDER_STRONG, '#4B5565')
        self.assertEqual(ui_theme_tokens.COLOR_TEXT_PRIMARY, '#F3F4F6')
        self.assertEqual(ui_theme_tokens.COLOR_TEXT_SECONDARY, '#D1D5DB')
        self.assertEqual(ui_theme_tokens.COLOR_TEXT_MUTED, '#9CA3AF')
        self.assertEqual(ui_theme_tokens.COLOR_ACCENT_PRIMARY, '#3B82F6')
        self.assertEqual(ui_theme_tokens.COLOR_ACCENT_HOVER, '#2563EB')
        self.assertEqual(ui_theme_tokens.COLOR_ACCENT_PRESSED, '#1D4ED8')
        self.assertEqual(ui_theme_tokens.COLOR_ACCENT_SUBTLE, '#1E3A8A33')
        self.assertEqual(ui_theme_tokens.COLOR_STATUS_SUCCESS, '#22C55E')
        self.assertEqual(ui_theme_tokens.COLOR_STATUS_WARNING, '#F59E0B')
        self.assertEqual(ui_theme_tokens.COLOR_STATUS_DANGER, '#EF4444')
        self.assertEqual(ui_theme_tokens.COLOR_STATUS_INFO, '#38BDF8')
        self.assertEqual(ui_theme_tokens.COLOR_FOCUS_RING, '#93C5FD')

    def test_helper_text_is_readable_on_dark_surfaces(self):
        self.assertEqual(ui_theme_tokens.COLOR_TEXT_HELPER, '#9CA3AF')

    def test_legacy_aliases_map_to_graphite_states(self):
        self.assertEqual(ui_theme_tokens.COLOR_SURFACE_HOVER, ui_theme_tokens.COLOR_BACKGROUND_PANEL_ELEVATED)
        self.assertEqual(ui_theme_tokens.COLOR_SURFACE_ACTIVE, ui_theme_tokens.COLOR_ACCENT_SUBTLE)

    def test_panel_style_is_static_container_style(self):
        panel_css = ui_theme_tokens.panel_style(card=True)
        self.assertIn('QFrame {', panel_css)
        self.assertNotIn(':hover', panel_css)
        self.assertNotIn(':pressed', panel_css)

    def test_button_and_input_styles_use_blue_accent_hierarchy(self):
        button_css = ui_theme_tokens.button_style('primary')
        self.assertIn(ui_theme_tokens.COLOR_ACCENT_PRIMARY, button_css)
        self.assertIn(ui_theme_tokens.COLOR_ACCENT_HOVER, button_css)
        self.assertIn(ui_theme_tokens.COLOR_ACCENT_PRESSED, button_css)

        input_css = ui_theme_tokens.input_style()
        self.assertIn(f"border: 1px solid {ui_theme_tokens.COLOR_ACCENT_PRIMARY};", input_css)
        self.assertIn(f"border: 2px solid {ui_theme_tokens.COLOR_FOCUS_RING};", input_css)

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

    def test_selected_row_background_override_softens_aggressive_highlight(self):
        self.assertEqual(ui_theme_tokens.selected_row_background_override('#112233'), '#3B6B9B')

    def test_selected_row_background_override_fallback_is_less_aggressive(self):
        self.assertEqual(ui_theme_tokens.selected_row_background_override(None), '#5E88AD')


if __name__ == '__main__':
    unittest.main()
