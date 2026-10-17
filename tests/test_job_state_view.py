"""UI表示のために実行状態を変更しないことを確認する．"""
import unittest
from job_manager import JobManager
from job_state_view import resolve_job_display, resolve_terminal_state
from job_manager import JobState


class JobStateViewTests(unittest.TestCase):
    def test_idle_without_saved_status(self):
        state = resolve_job_display(username='guest', active_job=None,
                                    owner_status=None, own_status=None)
        self.assertFalse(state.globally_busy)
        self.assertEqual(state.status, {})

    def test_stale_running_does_not_modify_saved_data(self):
        saved = {'state': 'running', 'message': '旧ジョブ'}
        state = resolve_job_display(username='guest', active_job=None,
                                    owner_status=None, own_status=saved)
        self.assertEqual(state.status['state'], 'failed')
        self.assertEqual(state.own_status['state'], 'running')
        self.assertEqual(saved['state'], 'running')

    def test_owner_and_viewer_have_distinct_states(self):
        jobs = JobManager()
        active = jobs.try_start('guest', 'pipeline')
        owner = {'state': 'running', 'progress': 0.7}
        viewer = {'state': 'completed', 'progress': 1}
        state = resolve_job_display(username='admin', active_job=active,
                                    owner_status=owner, own_status=viewer)
        self.assertTrue(state.globally_busy)
        self.assertFalse(state.owner_is_self)
        self.assertEqual(state.job_id, active.job_id)
        self.assertEqual(state.status['progress'], 0.7)
        self.assertEqual(state.own_status['progress'], 1)

    def test_reconnected_owner_does_not_take_job_ownership(self):
        active = JobManager().try_start('guest', 'refine')
        saved = {'state': 'running', 'stage': ''}
        state = resolve_job_display(username='guest', active_job=active,
                                    owner_status=saved, own_status=saved,
                                    task_name='内容リファイン')
        self.assertTrue(state.owner_is_self)
        self.assertEqual(state.status['stage'], '内容リファイン')
        self.assertEqual(saved['stage'], '')


class TerminalStateTests(unittest.TestCase):
    def test_refiner_ignores_stale_pipeline_failure(self):
        self.assertEqual(resolve_terminal_state(task_name='ナレーション品質検査',
                         cancel_requested=False, manager_cancel_requested=False,
                         persisted_state='failed'), JobState.COMPLETED)

    def test_pipeline_failure_is_preserved(self):
        self.assertEqual(resolve_terminal_state(task_name='パイプライン (video)',
                         cancel_requested=False, manager_cancel_requested=False,
                         persisted_state='failed'), JobState.FAILED)

    def test_manager_cancellation_takes_priority(self):
        self.assertEqual(resolve_terminal_state(task_name='ナレーション品質検査',
                         cancel_requested=False, manager_cancel_requested=True,
                         persisted_state='completed'), JobState.CANCELLED)

    def test_individual_slide_cancelled_status(self):
        self.assertEqual(resolve_terminal_state(task_name='スライド 3 音声合成',
                         cancel_requested=False, manager_cancel_requested=False,
                         persisted_state='cancelled'), JobState.CANCELLED)


if __name__ == '__main__':
    unittest.main()
