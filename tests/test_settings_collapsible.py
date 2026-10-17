"""設定タブの折りたたみ配置を維持するための静的回帰テスト．"""
from pathlib import Path
import unittest

APP = Path(__file__).resolve().parents[1] / 'app.py'

class SettingsCollapsibleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP.read_text(encoding='utf-8')

    def test_sections_closed_by_default(self):
        for title in ('LLM / VLM', '日本語 TTS', '英語 TTS', 'PDF・ビデオ', 'ヨミ変換・辞書'):
            self.assertIn(f"ui.expansion('{title}'", self.source)
            self.assertIn(f"ui.expansion('{title}'", self.source)
        self.assertGreaterEqual(self.source.count('value=False'), 5)

    def test_save_stays_in_settings(self):
        region = self.source.split('    def refresh_settings(self)', 1)[1].split('    # --- ユーザー管理タブ', 1)[0]
        self.assertIn("on_click=save_main_config", region)
        self.assertIn("self._build_dict_editor()", region)

if __name__ == '__main__':
    unittest.main()
