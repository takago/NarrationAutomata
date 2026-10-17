"""Regression guards for the time-refinement sidebar integration."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TimeRefineSidebarTests(unittest.TestCase):
    def test_time_progress_persists_explicit_page(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        view = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'TimeRefineView')
        progress = next(node for node in view.body if isinstance(node, ast.FunctionDef) and node.name == '_progress')
        self.assertIn('page', [arg.arg for arg in progress.args.kwonlyargs])
        self.assertIn('page=page', ast.get_source_segment(source, progress))
        self.assertIn('fraction=index / len(pages), page=page', source)

    def test_sidebar_uses_page_for_both_refinement_kinds(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("self._set_sidebar_slide_preview(state.get('page'), project=project)", source)

    def test_time_refinement_hides_validation_controls(self):
        source = (ROOT / 'validation' / 'ui.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        view = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ValidationView')
        method = next(node for node in view.body if isinstance(node, ast.FunctionDef) and node.name == '_pipeline_controls_hidden')
        body = ast.get_source_segment(source, method)
        self.assertIn('time_refine_running', body)
        self.assertIn('return time_refine_running or', body)


if __name__ == '__main__':
    unittest.main()
