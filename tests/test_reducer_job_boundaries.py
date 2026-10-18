"""リデューサーとジョブ境界の静的回帰検査．アプリ起動やLLM/API呼出は不要．

本ファイルは動作保証ではなく，重要な制御境界がコード上に存在するかを検証する．
既知の設計上の懸念は別途調査報告に記載する．
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def method(path, classname, name):
    module = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == classname)
    return next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)

def calls(node, attribute):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attribute]

class ReducerJobBoundaries(unittest.TestCase):
    def test_start_refuses_existing_global_job(self):
        source = ast.unparse(method('validation/time_ui.py', 'TimeRefineView', 'start'))
        self.assertIn('self.lock.is_locked()', source)
        self.assertIn('self.owner.processing', source)
        self.assertIn('self.owner.set_time_refine_project_lock(True)', source)

    def test_revision_lock_precedes_copy(self):
        """準備段階から排他ロックを取得することを確認する．"""
        source = ast.unparse(method('validation/time_ui.py', 'TimeRefineView', '_worker_with_ui_slot'))
        self.assertLess(source.index('self.lock.acquire('), source.index('shutil.copytree'))
        self.assertLess(source.index('self.lock.acquire('), source.index('owner.select_existing_project('))

    def test_revision_release_in_finally(self):
        node = method('validation/time_ui.py', 'TimeRefineView', '_worker_with_ui_slot')
        self.assertTrue(any(isinstance(n, ast.Try) and any(c.func.attr == 'release' for c in calls(ast.Module(body=n.finalbody, type_ignores=[]), 'release')) for n in ast.walk(node)))

    def test_cancel_persists_cancelled(self):
        source = ast.unparse(method('validation/time_ui.py', 'TimeRefineView', '_worker_with_ui_slot'))
        self.assertIn("['time_refine']['state'] = 'cancelled'", source)
        self.assertIn("self._persist(state='cancelled')", source)

    def test_pipeline_handoff_occurs_after_cleanup(self):
        node = method('validation/time_ui.py', 'TimeRefineView', '_worker_with_ui_slot')
        finalizers = [n for n in ast.walk(node) if isinstance(n, ast.Try) and any('start_time_refine_pipeline' in ast.unparse(s) for s in n.finalbody)]
        self.assertEqual(len(finalizers), 1)
        source = ast.unparse(finalizers[0].finalbody)
        self.assertLess(source.index('refine_job.unregister'), source.index('owner.start_time_refine_pipeline()'))
        self.assertLess(source.index('self.busy = False'), source.index('owner.start_time_refine_pipeline()'))

    def test_handoff_rejection_is_persisted(self):
        source = ast.unparse(method('validation/time_ui.py', 'TimeRefineView', '_worker_with_ui_slot'))
        self.assertIn('started = owner.start_time_refine_pipeline()', source)
        self.assertIn('if not started:', source)
        self.assertIn("cfg['time_refine']['state'] = 'failed'", source)
        self.assertIn("self._persist(state='failed'", source)

    def test_lock_released_before_handoff(self):
        source = ast.unparse(method('validation/time_ui.py', 'TimeRefineView', '_worker_with_ui_slot'))
        self.assertLess(source.rindex('self.lock.release()'), source.rindex('owner.start_time_refine_pipeline()'))

    def test_pipeline_result_updates_terminal_state(self):
        source = ast.unparse(method('app.py', 'App', '_run_time_refine_pipeline')) if False else (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("meta['state'] = 'completed'", source)
        self.assertIn("config['time_refine']['state'] = 'failed'", source)
        self.assertIn("config['time_refine']['state'] = 'cancelled'", source)

if __name__ == '__main__':
    unittest.main()

# 実ジョブロックの競合テスト（プロジェクトのコピーやLLM実行はモックしない）
import asyncio
from test_execution_lock import ExecutionLockManager
from job_manager import JobState

class ReducerLockTransitions(unittest.IsolatedAsyncioTestCase):
    async def test_other_job_can_enter_before_reducer_revision_lock(self):
        lock = ExecutionLockManager()
        # コピー段階ではロック未取得という現行設計をシミュレートする．
        entered = asyncio.Event()
        resume = asyncio.Event()
        async def other_pipeline():
            self.assertTrue(await lock.acquire('user_b', '通常パイプライン'))
            entered.set()
            await resume.wait()
            self.assertTrue(lock.release())
        task = asyncio.create_task(other_pipeline())
        await entered.wait()
        self.assertFalse(await lock.acquire('user_a', 'リデューサー（原稿短縮）'))
        resume.set()
        await task
        self.assertFalse(lock.is_locked())

    async def test_revision_to_pipeline_handoff_does_not_keep_old_cancel(self):
        lock = ExecutionLockManager()
        self.assertTrue(await lock.acquire('user_a', 'リデューサー（原稿短縮）'))
        previous_id = lock.job_id
        self.assertTrue(lock.request_cancel(previous_id))
        self.assertTrue(lock.release(state=JobState.CANCELLED))
        self.assertTrue(await lock.acquire('user_a', '通常パイプライン'))
        new_id = lock.job_id
        self.assertNotEqual(previous_id, new_id)
        self.assertFalse(lock.jobs.cancellation_requested(new_id))
        self.assertFalse(lock.request_cancel(previous_id))
        self.assertTrue(lock.release())
