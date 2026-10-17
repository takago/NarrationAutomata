"""Basic regression guards for the shared header help dialog."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HelpDialogTests(unittest.TestCase):
    def test_help_is_part_of_build_and_button_opens_it(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SlideNarratorApp')
        build = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'build')
        body = ast.get_source_segment(source, build)
        self.assertIn('with ui.dialog() as help_dialog:', body)
        self.assertIn("on_click=help_dialog.open", body)
        self.assertIn("on_click=help_dialog.close", body)
        self.assertIn("'ログアウト'", body)

    def test_guide_covers_actual_pipeline_behavior(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn('短縮後の新しいプロジェクトで④を実行します', source)
        self.assertIn('不足している②・③も必要に応じて実行され', source)
        self.assertIn('目標再生時間を指定してください', source)


if __name__ == '__main__':
    unittest.main()
