"""The time-refinement log must be scoped to the currently selected project."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestTimeRefineProjectLog(unittest.TestCase):
    def test_empty_snapshot_clears_previous_log_and_progress(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        view = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TimeRefineView')
        method = next(n for n in view.body if isinstance(n, ast.FunctionDef) and n.name == 'restore_progress')
        branches = [n for n in ast.walk(method) if isinstance(n, ast.If)
                    and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not)
                    and isinstance(n.test.operand, ast.Name) and n.test.operand.id == 'snapshot']
        self.assertEqual(len(branches), 1)
        branch = ast.get_source_segment(source, branches[0])
        for required in ('self.step_log_lines = []', "self.step_log.text = ''",
                         'self.progress_panel.visible = False', 'self.progress_bar.value = 0', 'return'):
            self.assertIn(required, branch)

    def test_snapshot_is_read_from_current_project(self):
        source = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
        self.assertIn('project = self.owner.paths.root', source)
        self.assertIn("snapshot = refine_job.read(project, 'time')", source)

if __name__ == '__main__':
    unittest.main()
