"""実際の App メソッドを抽出して起動拒否と正常起動を確認する回帰テスト．
本体ファイルを変更せず，サーバもLLMも起動しない．
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))
app_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SlideNarratorApp')
methods = [n for n in app_cls.body if isinstance(n, ast.FunctionDef) and n.name in ('_start_background_job', 'start_time_refine_pipeline')]
assert len(methods) == 2
notifier = Mock()
tasks = SimpleNamespace(create=Mock(return_value=object()))
namespace = {'safe_notify': notifier, 'background_tasks': tasks}
exec(compile(ast.Module(body=methods, type_ignores=[]), '<real-app-methods>', 'exec'), namespace)

class HandoffRejectionTests(unittest.TestCase):
    def setUp(self):
        notifier.reset_mock()
        tasks.create.reset_mock(return_value=True)
        self.app = SimpleNamespace(_project_switching=False, current_task=None,
                                   _run_time_refine_pipeline=lambda: 'worker')
        self.app._start_background_job = lambda *a, **kw: namespace['_start_background_job'](self.app, *a, **kw)

    def test_normal_handoff_schedules_job(self):
        result = namespace['start_time_refine_pipeline'](self.app)
        self.assertTrue(result)
        tasks.create.assert_called_once()
        self.assertIsNotNone(self.app.current_task)

    def test_project_switch_rejects_handoff_silently_to_caller(self):
        self.app._project_switching = True
        result = namespace['start_time_refine_pipeline'](self.app)
        self.assertFalse(result)
        tasks.create.assert_not_called()
        notifier.assert_called_once()

    def test_running_task_rejects_handoff_silently_to_caller(self):
        self.app.current_task = SimpleNamespace(done=lambda: False)
        result = namespace['start_time_refine_pipeline'](self.app)
        self.assertFalse(result)
        tasks.create.assert_not_called()
        notifier.assert_called_once()

    def test_finished_task_allows_handoff(self):
        self.app.current_task = SimpleNamespace(done=lambda: True)
        namespace['start_time_refine_pipeline'](self.app)
        tasks.create.assert_called_once()

if __name__ == '__main__':
    unittest.main()
