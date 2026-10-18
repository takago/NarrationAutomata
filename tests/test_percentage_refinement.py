"""No-video percentage refinement and retained time pipeline checks."""
import ast
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

class PercentageRefineTests(unittest.TestCase):
    def test_naming_rules(self):
        tree = ast.parse((ROOT / 'validation/time_ui.py').read_text(encoding='utf-8'))
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'refined_project_name')
        import re
        namespace = {'re': re}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<name>', 'exec'), namespace)
        naming = namespace['refined_project_name']
        self.assertEqual(naming('Lecture', target_percent=80), 'Lecture_RF80p')
        self.assertEqual(naming('Lecture_RF20m', target_percent=60), 'Lecture_RF60p')
        self.assertEqual(naming('Lecture_RF80p', target_minutes=20), 'Lecture_RF20m')
    def test_both_modes_follow_checkbox_for_pipeline_handoff(self):
        text = (ROOT / 'validation/time_ui.py').read_text(encoding='utf-8')
        self.assertIn("if not auto_create_video:\n                    new_cfg['time_refine']['state'] = 'completed'", text)
        self.assertIn("                    handoff_to_pipeline = True", text)
        self.assertIn("if handoff_to_pipeline:", text)
    def test_result_graphs_unchanged(self):
        text = (ROOT / 'validation/time_ui.py').read_text(encoding='utf-8')
        self.assertIn("_time_refine_ratio_chart_options(rows, slide_labels, relative, image_urls)", text)
    def test_refiner_chart_and_help_removed(self):
        text = (ROOT / 'validation/ui.py').read_text(encoding='utf-8')
        self.assertNotIn('修正されたスライドの原稿文字数（変更前後）', text)
        app = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertNotIn('結果は「統計」ではなく', app)
