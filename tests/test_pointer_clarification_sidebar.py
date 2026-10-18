"""追加調査がプロジェクト単位かつ既定OFFであることの回帰検査．"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PointerClarificationSettingsTests(unittest.TestCase):
    def test_default_off_in_generation(self):
        source = (ROOT / 'slide_lecture.py').read_text(encoding='utf-8')
        self.assertIn('cfg.get("pointer_vlm_clarification", False)', source)
        self.assertIn("proj_cfg.get('pointer_vlm_clarification', False) is True", source)

    def test_ui_has_project_settings_and_advanced_only(self):
        source = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("'曖昧なポインタ位置をVLMで追加調査する'", source)
        self.assertIn('self.advanced_sidebar_sections.append(vlm_card)', source)
        self.assertIn("_save_pointer_clarification_option('pointer_vlm_clarification'", source)
        self.assertNotIn('pointer_clarification_reasoning_effort', source)

    def test_reasoning_setting_inherits_main_model(self):
        source = (ROOT / 'slide_lecture.py').read_text(encoding='utf-8')
        self.assertGreaterEqual(source.count('cfg.get("reasoning_effort", "none")'), 2)
        self.assertNotIn('pointer_clarification_reasoning_effort', source)
        ast.parse(source)
