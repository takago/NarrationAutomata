"""Check shared cleanup without importing optional NiceGUI runtime dependencies."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'validation' / 'ui.py').read_text(encoding='utf-8')


class ContentWorkerFinalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = ast.parse(SOURCE)
        view = next(n for n in root.body if isinstance(n, ast.ClassDef) and n.name == 'ValidationView')
        cls.methods = {n.name: n for n in view.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_both_workers_call_shared_cleanup_in_finally(self):
        for name in ('_worker', '_bulk_correct_worker'):
            with self.subTest(name=name):
                worker = self.methods[name]
                finalizers = [n for n in ast.walk(worker) if isinstance(n, ast.Try) and n.finalbody]
                self.assertTrue(any(
                    isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                    and isinstance(s.value.func, ast.Attribute)
                    and s.value.func.attr == '_finish_content_worker'
                    for node in finalizers for s in node.finalbody))

    def test_common_cleanup_keeps_all_six_actions_in_order(self):
        helper = self.methods['_finish_content_worker']
        body = ast.get_source_segment(SOURCE, helper)
        expected = (
            'self.busy = False',
            'refine_job.finish_content(',
            'refine_job.unregister(',
            'self._running_project = None',
            'owner._finalize_cancel_request()',
            'owner._complete_background_job()',
        )
        offsets = [body.index(item) for item in expected]
        self.assertEqual(offsets, sorted(offsets))

    def test_ui_refreshes_remain_distinct(self):
        for worker_name, refresh in (('_worker', '_safe_render_results'), ('_bulk_correct_worker', 'refresh')):
            with self.subTest(worker=worker_name):
                body = ast.get_source_segment(SOURCE, self.methods[worker_name])
                self.assertIn('self._finish_content_worker(project)', body)
                self.assertIn(f'self.{refresh}()', body)


if __name__ == '__main__':
    unittest.main()
