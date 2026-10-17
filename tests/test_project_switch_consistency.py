"""Prevent regressions in asynchronous project switching safeguards."""
from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[1] / 'app.py'


class ProjectSwitchConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP.read_text(encoding='utf-8')

    def test_switch_is_serialized(self):
        self.assertIn('self._project_switch_lock = asyncio.Lock()', self.source)
        self.assertIn('async with self._project_switch_lock:', self.source)

    def test_images_are_loaded_before_activating_project(self):
        section = self.source.split('async def _select_existing_project_impl(', 1)[1].split('def request_delete_project(', 1)[0]
        self.assertLess(section.index('new_images = await run.io_bound(ensure_page_images'), section.index('self.pdf = target_pdf'))

    def test_pipeline_start_rejected_while_switching(self):
        section = self.source.split('def _start_background_job(', 1)[1].split('def _finalize_cancel_request(', 1)[0]
        self.assertIn('if self._project_switching:', section)

    def test_time_worker_still_skips_browser_repainting(self):
        section = self.source.split('async def select_existing_project(', 1)[1].split('async def _select_existing_project_impl(', 1)[0]
        self.assertIn('if not time_refine_internal:', section)


if __name__ == '__main__':
    unittest.main()
