"""Regression checks for mutually exclusive refinement controls."""
import ast
from pathlib import Path
import unittest
from types import SimpleNamespace


SOURCE = Path(__file__).resolve().parents[1] / 'validation' / 'time_ui.py'
TREE = ast.parse(SOURCE.read_text(encoding='utf-8'))
VIEW = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'TimeRefineView')
METHOD = next(n for n in VIEW.body if isinstance(n, ast.FunctionDef) and n.name == '_other_job_running')


class TestTimeControlsVisibility(unittest.TestCase):
    def evaluate(self, *, owner_processing=False, locked=False, worker=None, own=None):
        class TimeRefineView:
            pass
        registry = SimpleNamespace(
            running=lambda username, project: worker,
            running_as=lambda username, project, kind: own,
        )
        namespace = {'refine_job': registry, 'TimeRefineView': TimeRefineView}
        method = ast.fix_missing_locations(ast.FunctionDef(
            name=METHOD.name, args=METHOD.args, body=METHOD.body,
            decorator_list=[], returns=METHOD.returns, type_comment=None))
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        view = SimpleNamespace(
            owner=SimpleNamespace(paths=SimpleNamespace(root=Path('/tmp/project')),
                                  username='test', processing=owner_processing),
            lock=SimpleNamespace(is_locked=lambda: locked),
        )
        return namespace[METHOD.name](view)

    def test_pipeline_hides_inputs(self):
        self.assertTrue(self.evaluate(owner_processing=True))

    def test_content_refiner_hides_inputs_even_during_unlocked_transition(self):
        self.assertTrue(self.evaluate(worker=object(), locked=False))

    def test_time_refiner_retains_stop_control(self):
        own = object()
        self.assertFalse(self.evaluate(worker=own, own=own, locked=True))

    def test_idle_shows_inputs(self):
        self.assertFalse(self.evaluate())

    def test_visibility_branch_covers_entire_configuration(self):
        refresh = next(n for n in VIEW.body if isinstance(n, ast.FunctionDef) and n.name == 'refresh')
        conditions = [n for n in ast.walk(refresh) if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
                      and n.test.attr == '_shown_other_job']
        self.assertEqual(len(conditions), 1)
        self.assertIn('self.target_input = ui.slider', ast.get_source_segment(SOURCE.read_text(encoding='utf-8'), refresh))


if __name__ == '__main__':
    unittest.main()
