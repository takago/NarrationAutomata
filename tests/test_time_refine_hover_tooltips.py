"""Regression checks for slide-preview tooltips in time-refine charts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TestTimeRefineHoverTooltips(unittest.TestCase):
    def test_chart_helpers_exist(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        self.assertIn('def _time_refine_file_url', source)
        self.assertIn('def _time_refine_tooltip_formatter', source)
        self.assertIn('def _time_refine_bar_chart_options', source)
        self.assertIn('def _time_refine_ratio_chart_options', source)

    def test_tooltip_formatter_includes_slide_preview_and_metrics(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        self.assertIn("'<img src=\"' + images[page]", source)
        self.assertIn("短縮前：", source)
        self.assertIn("短縮後：", source)
        self.assertIn("短縮後／短縮前：", source)

    def test_refresh_uses_chart_helpers_with_image_urls(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        self.assertIn("image_urls[str(page)] = _time_refine_file_url(image_path)", source)
        self.assertIn("_time_refine_bar_chart_options(rows, slide_labels", source)
        self.assertIn("_time_refine_ratio_chart_options(rows, slide_labels", source)

    def test_time_tooltips_match_statistics_style(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("'backgroundColor': '#1f2937', 'borderColor': '#475569'"), 2)
        self.assertEqual(source.count("'axisPointer': {'type': 'shadow'}"), 2)
        self.assertEqual(source.count("'confine': True, 'enterable': False"), 2)


if __name__ == '__main__':
    unittest.main()


class TestTooltipJavaScriptBinding(unittest.TestCase):
    def test_chart_formatters_use_nicegui_js_binding(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("':formatter': _time_refine_tooltip_formatter(image_urls, rows)"), 2)
        self.assertNotIn("'formatter': _time_refine_tooltip_formatter(image_urls, rows)", source)
