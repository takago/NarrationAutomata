"""Failure injection for refiner finalization, without a NiceGUI server."""
import ast
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
parsed = ast.parse((ROOT / 'validation' / 'ui.py').read_text(encoding='utf-8'))
cls = next(n for n in parsed.body if isinstance(n, ast.ClassDef) and n.name == 'ValidationView')
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_finish_content_worker')
namespace = {
    'refine_job': SimpleNamespace(finish_content=Mock(), unregister=Mock()),
    'LOGGER': logging.getLogger(__name__),
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name='Finalizer', bases=[], keywords=[],
    body=[method], decorator_list=[])], type_ignores=[])), '<finalizer>', 'exec'), namespace)


class FinalizationSafetyTests(unittest.TestCase):
    def setUp(self):
        namespace['refine_job'].finish_content.reset_mock(side_effect=True)
        namespace['refine_job'].unregister.reset_mock(side_effect=True)

    def test_state_save_failure_does_not_strand_lock(self):
        namespace['refine_job'].finish_content.side_effect = OSError('disk failure')
        self._assert_unlocks()

    def test_unregister_failure_does_not_strand_lock(self):
        namespace['refine_job'].unregister.side_effect = RuntimeError('registry failure')
        self._assert_unlocks()

    def test_cancel_state_failure_does_not_strand_lock(self):
        self._assert_unlocks(cancel_failure=True)

    def _assert_unlocks(self, cancel_failure=False):
        owner = SimpleNamespace(username='guest', cancellation_requested=False,
            _finalize_cancel_request=Mock(side_effect=OSError('cancel state') if cancel_failure else None),
            _complete_background_job=Mock())
        view = namespace['Finalizer']()
        view.owner = owner
        view.busy = True
        view._running_project = '/tmp/demo'
        view._finish_content_worker('/tmp/demo')
        self.assertFalse(view.busy)
        self.assertIsNone(view._running_project)
        owner._complete_background_job.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
