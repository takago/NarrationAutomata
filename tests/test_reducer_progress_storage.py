"""Regression checks: only destination stores reducer progress after cloning."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'validation' / 'time_ui.py').read_text(encoding='utf-8')
TREE = ast.parse(SOURCE)
VIEW = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'TimeRefineView')


class ReducerProgressStorageTests(unittest.TestCase):
    def test_persist_tracks_only_current_destination(self):
        method = next(n for n in VIEW.body if isinstance(n, ast.FunctionDef) and n.name == '_persist')
        function = ast.Module(body=[method], type_ignores=[])
        namespace = {'refine_job': SimpleNamespace(write=Mock())}
        exec(compile(ast.fix_missing_locations(function), '<reducer-persist>', 'exec'), namespace)
        view = SimpleNamespace(_source_project=Path('/source'), _target_project=None)
        namespace['_persist'](view, state='running')
        namespace['refine_job'].write.assert_called_once_with(Path('/source'), 'time', state='running')
        namespace['refine_job'].write.reset_mock()
        view._target_project = Path('/target')
        namespace['_persist'](view, page=4, title='slide progress')
        namespace['refine_job'].write.assert_called_once_with(Path('/target'), 'time', page=4, title='slide progress')

    def test_copy_discards_source_snapshot_before_writing_target(self):
        start = SOURCE.index("(new_paths.root / 'validation' / 'time_job.json').unlink(missing_ok=True)")
        reg = SOURCE.index('refine_job.register(owner.username, self._target_project, self)', start)
        persist = SOURCE.index("self._persist(state='running', mode=mode, target_project_id=project_id", reg)
        self.assertLess(start, reg)
        self.assertLess(reg, persist)

    def test_source_only_keeps_reference_after_clone(self):
        self.assertIn("refine_job.write(self._source_project, 'time',", SOURCE)
        self.assertIn("state='transferred', target_project_id=project_id,", SOURCE)
        self.assertIn("message='', log=[], stop_requested=False)", SOURCE)


if __name__ == '__main__':
    unittest.main()
