"""Regression tests for refinement registry and terminal-state helpers."""
import tempfile
import unittest
from pathlib import Path
from validation import refine_job


class ContentView:
    pass


class TimeView:
    pass


class RefineJobTests(unittest.TestCase):
    def test_registry_filters_refinement_type(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            worker = TimeView()
            refine_job.register('guest', project, worker)
            try:
                self.assertIs(refine_job.running_as('guest', project, TimeView), worker)
                self.assertIsNone(refine_job.running_as('guest', project, ContentView))
                self.assertIsNone(refine_job.running_as('guest', None, TimeView))
            finally:
                refine_job.unregister('guest', project, worker)
            self.assertIsNone(refine_job.running('guest', project))

    def test_finalize_preserves_terminal_error_and_message(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            for prior, cancelled, expected in (
                ('running', False, 'completed'),
                ('running', True, 'cancelled'),
                ('failed', False, 'failed'),
                ('cancelled', False, 'cancelled'),
            ):
                refine_job.write(project, 'content', state=prior, message='前回の状態')
                result = refine_job.finish_content(project, cancelled=cancelled)
                self.assertEqual(result['state'], expected)
                self.assertEqual(refine_job.read(project, 'content')['message'], '前回の状態')


if __name__ == '__main__':
    unittest.main()
