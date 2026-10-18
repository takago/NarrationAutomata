"""Ensure normal project switching updates refinement tabs without reopening them."""
import ast
import unittest
from pathlib import Path


class ProjectSwitchRefinementRefreshTests(unittest.TestCase):
    def test_switch_refreshes_both_refinement_views_after_outputs(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        root = ast.parse(source)
        method = next(
            item for klass in root.body if isinstance(klass, ast.ClassDef)
            for item in klass.body if isinstance(item, ast.AsyncFunctionDef)
            and item.name == '_select_existing_project_impl'
        )
        calls = [ast.unparse(node.func) for node in ast.walk(method) if isinstance(node, ast.Call)]
        self.assertIn('self._safe_view_update', calls)
        # Narrow to the success path and confirm tab-refresh hooks.
        segment = ast.get_source_segment(source, method)
        self.assertIn("self._safe_view_update(self.validation_view.refresh, 'プロジェクト切替後のリファイナー更新')", segment)
        self.assertIn("self._safe_view_update(self.time_refine_view.refresh, 'プロジェクト切替後のリデューサー更新')", segment)
        self.assertLess(segment.index('await self.refresh_all()'), segment.index('プロジェクト切替後のリデューサー更新'))


if __name__ == '__main__':
    unittest.main()
