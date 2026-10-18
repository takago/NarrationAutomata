"""Guard the removal of legacy automatic content-refinement markers."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RemovedAutoRefinerTests(unittest.TestCase):
    def test_legacy_marker_and_mode_are_absent(self):
        for filename in ('validation/refine_job.py', 'validation/store.py', 'validation/ui.py'):
            source = (ROOT / filename).read_text(encoding='utf-8')
            self.assertNotIn('PipelineContentRefine', source)
        self.assertNotIn("MODES=", (ROOT / 'validation/store.py').read_text(encoding='utf-8'))

    def test_content_view_keeps_active_job_and_processing_guards(self):
        source = (ROOT / 'validation/ui.py').read_text(encoding='utf-8')
        cls = next(node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == 'ValidationView')
        funcs = {node.name: ast.get_source_segment(source, node) for node in cls.body if isinstance(node, ast.FunctionDef)}
        self.assertIn('refine_job.running(', funcs['_pipeline_controls_hidden'])
        self.assertIn('self.owner.processing', funcs['_pipeline_controls_hidden'])
        self.assertIn('not self.busy', funcs['_pipeline_controls_hidden'])
        self.assertIn('isinstance(live, ValidationView)', funcs['restore_progress'])

    def test_live_registry_remains_intact(self):
        source = (ROOT / 'validation/refine_job.py').read_text(encoding='utf-8')
        for name in ('ACTIVE', 'register', 'unregister', 'running', 'running_as', 'finish_content'):
            self.assertIn(name, source)


if __name__ == '__main__':
    unittest.main()
