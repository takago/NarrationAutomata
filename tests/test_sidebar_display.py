import unittest
from pathlib import Path
from sidebar_display import select_refinement_candidate, video_render_key

class SidebarDisplayTests(unittest.TestCase):
    def test_live_refinement_wins(self):
        stale = (0, 0, 'later', 'a', 'time', Path('/a'), {'state': 'running'})
        live = (1, 0, 'earlier', 'b', 'content', Path('/b'), {'state': 'running'})
        self.assertEqual(select_refinement_candidate([stale, live], pipeline_running=False), live)
    def test_stale_hidden_during_pipeline(self):
        stale = (0, 0, 'now', 'a', 'time', Path('/a'), {'state': 'running'})
        self.assertIsNone(select_refinement_candidate([stale], pipeline_running=True))
        self.assertEqual(select_refinement_candidate([stale], pipeline_running=False), stale)
    def test_no_candidates(self):
        self.assertIsNone(select_refinement_candidate([], pipeline_running=False))
    def test_video_key_distinguishes_project(self):
        self.assertNotEqual(video_render_key(Path('/a'), (1,2,3)),video_render_key(Path('/b'), (1,2,3)))
    def test_video_key_detects_missing_to_present(self):
        self.assertNotEqual(video_render_key(Path('/a'), None),video_render_key(Path('/a'), (1,2,3)))
