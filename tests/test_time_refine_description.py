"""Guard the time-refinement UI's project-copy and video-generation guidance."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'validation' / 'time_ui.py').read_text(encoding='utf-8')


class TestTimeRefineDescription(unittest.TestCase):
    def test_common_description_explains_copy_and_both_modes(self):
        cls = next(node for node in ast.parse(SOURCE).body
                   if isinstance(node, ast.ClassDef) and node.name == 'TimeRefineView')
        build = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'build')
        body = ast.get_source_segment(SOURCE, build)
        self.assertIn('元のプロジェクトを残し，新しいプロジェクトを作成して調整します．', body)
        self.assertIn('後続工程の自動実行はチェックボックスで選べます．', body)
        self.assertIn('動画がない場合は文字数の割合', body)

    def test_button_name_and_no_redundant_dynamic_message(self):
        self.assertIn("ui.button('新しいプロジェクトで調整を開始'", SOURCE)
        self.assertNotIn('self.mode_description.text =', SOURCE)


if __name__ == '__main__':
    unittest.main()
