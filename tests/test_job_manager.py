"""独立ジョブ管理基盤の回帰テスト．"""
import unittest
from dataclasses import FrozenInstanceError
from job_manager import JobManager, JobState


class JobManagerTests(unittest.TestCase):
    def test_start_and_finish(self):
        manager = JobManager()
        job = manager.try_start('guest', 'pipeline')
        self.assertIsNotNone(job)
        self.assertEqual(job.state, JobState.RUNNING)
        self.assertEqual(manager.current(), job)
        self.assertTrue(manager.finish(job.job_id, JobState.COMPLETED))
        self.assertIsNone(manager.current())
        self.assertFalse(manager.is_running())

    def test_exclusive_and_stale_finish(self):
        manager = JobManager()
        first = manager.try_start('guest', 'pipeline')
        self.assertIsNone(manager.try_start('admin', 'refine'))
        self.assertFalse(manager.finish('wrong-job', JobState.CANCELLED))
        self.assertTrue(manager.is_running())
        self.assertTrue(manager.finish(first.job_id, JobState.CANCELLED))
        second = manager.try_start('admin', 'refine')
        self.assertNotEqual(first.job_id, second.job_id)
        self.assertFalse(manager.finish(first.job_id, JobState.FAILED))
        self.assertEqual(manager.current().job_id, second.job_id)

    def test_cancel_is_scoped_to_current_job(self):
        manager = JobManager()
        first = manager.try_start('guest', 'pipeline')
        self.assertFalse(manager.request_cancel('wrong-job'))
        self.assertTrue(manager.request_cancel(first.job_id))
        self.assertTrue(manager.cancellation_requested(first.job_id))
        self.assertTrue(manager.current().cancellation_requested)
        manager.finish(first.job_id, JobState.CANCELLED)
        second = manager.try_start('guest', 'refine')
        self.assertFalse(manager.request_cancel(first.job_id))
        self.assertFalse(manager.cancellation_requested(second.job_id))

    def test_invalid_finish_and_duplicate_finish(self):
        manager = JobManager()
        job = manager.try_start('guest', 'pipeline')
        with self.assertRaises(ValueError):
            manager.finish(job.job_id, JobState.RUNNING)
        self.assertTrue(manager.is_running())
        self.assertTrue(manager.finish(job.job_id, JobState.FAILED))
        self.assertFalse(manager.finish(job.job_id, JobState.FAILED))

    def test_validation_and_immutable_snapshot(self):
        manager = JobManager()
        with self.assertRaises(ValueError):
            manager.try_start('', 'pipeline')
        with self.assertRaises(ValueError):
            manager.try_start('guest', '')
        job = manager.try_start('guest', 'pipeline')
        with self.assertRaises(FrozenInstanceError):
            job.task_name = 'changed'


if __name__ == '__main__':
    unittest.main()
