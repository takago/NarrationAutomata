"""Structural regression checks for the mutually exclusive controls."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def method_source(relative_path, class_name, method_name):
    source = (ROOT / relative_path).read_text(encoding='utf-8')
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method_name)
    return ast.get_source_segment(source, node)


class TestControlsSimplification(unittest.TestCase):
    def test_time_controls_hidden_for_other_jobs(self):
        src = method_source('validation/time_ui.py', 'TimeRefineView', 'refresh')
        self.assertIn('elif self._shown_other_job:', src)
        self.assertIn('if self.owner.read_only:', src)
        self.assertNotIn('if self.busy or self.owner.read_only:', src)
        self.assertIn('if not can_start:', src)

    def test_content_controls_hidden_for_other_jobs(self):
        src = method_source('validation/ui.py', 'ValidationView', 'refresh')
        self.assertIn('if self._shown_pipeline:', src)
        self.assertIn('elif self.busy:', src)
        self.assertIn('else:', src)

    def test_refiner_start_does_not_toggle_a_hidden_button(self):
        src = method_source('validation/ui.py', 'ValidationView', 'start')
        self.assertNotIn('self._start_button.disable()', src)

    def test_refiner_finish_does_not_enable_a_stale_button(self):
        src = method_source('validation/ui.py', 'ValidationView', '_worker')
        self.assertNotIn('self._start_button.enable()', src)


if __name__ == '__main__':
    unittest.main()
