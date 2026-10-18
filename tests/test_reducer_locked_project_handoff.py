"""Regression guards for the reducer's execution-lock-protected handoff."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')


class ReducerLockedHandoffTests(unittest.TestCase):
    def test_internal_handoff_is_scoped_to_running_registered_destination(self):
        section = SOURCE.split('async def _select_existing_project_impl(', 1)[1].split('def request_delete_project(', 1)[0]
        self.assertIn("target_pdfs = list(target_dir.glob('*.pdf'))", section)
        self.assertIn('ProjectPaths(target_pdfs[0]).root', section)
        self.assertIn('refine_job.running(self.username, target)', section)
        self.assertIn("refine_job.read(target, 'time')", section)
        self.assertIn('reducer_handoff = (time_refine_internal and', section)
        self.assertIn('GLOBAL_EXECUTION_LOCK.owner_app is self', section)
        self.assertIn('live_time is not None', section)
        self.assertIn("state.get('target_project_id') == project_id", section)
        self.assertIn('restoring_time_target or sidebar_live or reducer_handoff', section)

    def test_internal_switch_propagates_original_exception(self):
        section = SOURCE.split('async def _select_existing_project_impl(', 1)[1].split('def request_delete_project(', 1)[0]
        self.assertIn('except Exception as exc:\n            if time_refine_internal:', section)
        self.assertIn('if time_refine_internal:\n                # Do not mask the underlying reason with a generic handoff error.\n                raise', section)


if __name__ == '__main__':
    unittest.main()
