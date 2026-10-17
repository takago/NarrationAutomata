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
        self.assertIn("options = _time_refine_bar_chart_options", source)
        self.assertIn("ratio_options = _time_refine_ratio_chart_options", source)


if __name__ == '__main__':
    unittest.main()
