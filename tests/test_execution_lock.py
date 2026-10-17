"""app.pyの互換ロックをサーバを立ち上げずに検証する．"""
import ast
import asyncio
from contextvars import ContextVar
from pathlib import Path
import unittest
from typing import Any
from job_manager import JobManager, JobState

source = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
lock_class = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == 'ExecutionLockManager')
namespace = {'asyncio': asyncio, 'ContextVar': ContextVar, 'JobManager': JobManager,
             'JobState': JobState, 'Any': Any}
exec(compile(ast.Module(body=[lock_class], type_ignores=[]), '<execution-lock>', 'exec'), namespace)
ExecutionLockManager = namespace['ExecutionLockManager']


class ExecutionLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_cancel_and_release(self):
        lock = ExecutionLockManager()
        self.assertTrue(await lock.acquire('guest', 'pipeline'))
        job_id = lock.job_id
        self.assertFalse(await lock.acquire('admin', 'refine'))
        self.assertTrue(lock.request_cancel(job_id))
        self.assertTrue(lock.jobs.cancellation_requested(job_id))
        self.assertTrue(lock.release(state=JobState.CANCELLED))
        self.assertFalse(lock.is_locked())
        self.assertFalse(lock.release())

    async def test_old_task_cannot_release_new_job(self):
        lock = ExecutionLockManager()
        old_done = asyncio.Event()
        new_started = asyncio.Event()
        results = []

        async def old_worker():
            self.assertTrue(await lock.acquire('guest', 'pipeline'))
            first = lock.job_id
            self.assertTrue(lock.release())
            old_done.set()
            await new_started.wait()
            results.append(lock.release())
            results.append(lock.request_cancel(first))

        async def new_worker():
            await old_done.wait()
            self.assertTrue(await lock.acquire('admin', 'refine'))
            new_started.set()
            await asyncio.sleep(0)
            await old_task
            self.assertTrue(lock.is_locked())
            self.assertEqual(lock.current_user, 'admin')
            self.assertFalse(any(results))
            self.assertTrue(lock.release())

        old_task = asyncio.create_task(old_worker())
        await asyncio.gather(old_task, new_worker())

    async def test_non_owner_task_cannot_release(self):
        lock = ExecutionLockManager()
        self.assertTrue(await lock.acquire('guest', 'pipeline'))
        async def other():
            # ContextVarの継承を無効にして別セッションを再現する
            lock._task_job_id.set(None)
            return lock.release()
        self.assertFalse(await asyncio.create_task(other()))
        self.assertTrue(lock.is_locked())
        self.assertTrue(lock.release())


    async def test_cancel_old_job_does_not_cancel_replacement(self):
        lock = ExecutionLockManager()
        self.assertTrue(await lock.acquire('guest', 'パイプライン (video)'))
        old = lock.job_id
        self.assertTrue(lock.request_cancel(old))
        self.assertTrue(lock.release(state=JobState.CANCELLED))
        self.assertTrue(await lock.acquire('guest', 'ナレーション品質検査'))
        new = lock.job_id
        self.assertNotEqual(old, new)
        self.assertFalse(lock.request_cancel(old))
        self.assertFalse(lock.jobs.cancellation_requested(new))
        self.assertFalse(lock.release(expected_job_id=old))
        self.assertTrue(lock.is_locked())
        self.assertTrue(lock.release())

    async def test_other_task_cannot_finish_even_with_expected_id(self):
        lock = ExecutionLockManager()
        self.assertTrue(await lock.acquire('guest', 'pipeline'))
        job_id = lock.job_id
        async def intruder():
            return lock.release(expected_job_id=job_id)
        self.assertFalse(await asyncio.create_task(intruder()))
        self.assertTrue(lock.is_locked())
        self.assertTrue(lock.release())


if __name__ == '__main__':
    unittest.main()
