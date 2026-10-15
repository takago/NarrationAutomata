"""Run with: python -m unittest discover -s tests -v

Core tests use an isolated slide_lecture stub so the logic can also be checked
without installing NiceGUI, torch, or OpenAI.
"""
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

if 'slide_lecture' not in sys.modules:
    stub=types.ModuleType('slide_lecture')
    stub.image_data_url=lambda path:'data:image/png;base64,AA=='
    stub.reasoning_extra_kwargs=lambda effort:{}
    stub.stream_chat=lambda *args,**kwargs:None
    sys.modules['slide_lecture']=stub

from validation.core import rule_check, _parse_json, _normalize
from validation.store import load,save,digest

class QualityValidationTests(unittest.TestCase):
    def test_rule_token(self):
        issues=rule_check('hello </think> world',12)
        self.assertEqual(issues[0]['kind'],'token')
        self.assertEqual(issues[0]['page'],12)
    def test_empty(self):
        self.assertEqual(rule_check('   ',1)[0]['kind'],'empty')
    def test_normal(self):
        self.assertEqual(rule_check('This is a normal narration.',3),[])
    def test_json(self):
        self.assertEqual(_parse_json('```json\n{"issues":[]}\n```')['issues'],[])
        with self.assertRaises(ValueError):_parse_json('not json')
    def test_normalize_rejects_other_pages(self):
        self.assertEqual(_normalize([{'page':99,'description':'x'}],[1,2],1),[])
    def test_project_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=load(root)
            self.assertEqual(state['findings'],[])
            state['findings']=[{'page':12,'kind':'token'}]
            save(root,state)
            self.assertEqual(load(root)['findings'][0]['page'],12)
            save(root,{'findings':[], 'stages':{}, 'completed':False})
            self.assertEqual(load(root)['findings'],[])
            self.assertNotEqual(digest('a'),digest('b'))

if __name__=='__main__':unittest.main()

class ReasoningLeakTests(unittest.TestCase):
    def test_reject_open_and_close_tags(self):
        from validation.core import _reasoning_leak
        for marker in ('<think>', '</think>'):
            with self.subTest(marker=marker):
                self.assertTrue(_reasoning_leak('説明 ' + marker, '元原稿', None, {}))
                self.assertTrue(_reasoning_leak('説明 ' + marker, '説明 ' + marker, None, {}))

    def test_clean_output_accepted_even_if_original_has_tag(self):
        from validation.core import _reasoning_leak
        self.assertFalse(_reasoning_leak('修正後の原稿', '元原稿 </think>', None, {}))

    def test_retry_then_success(self):
        from unittest.mock import patch
        from validation.core import correct
        responses = iter(['<think>混入', '</think>混入', '正常な修正原稿'])
        with patch('validation.core._ask', side_effect=lambda *a, **k: next(responses)) as asker:
            self.assertEqual(correct(None, {}, 3, '旧原稿', [{'kind': 'token'}]), '正常な修正原稿')
            self.assertEqual(asker.call_count, 3)

    def test_three_retries_then_reject_with_last_response(self):
        from unittest.mock import patch
        from validation.core import correct, CorrectionReasoningLeak
        responses = ['<think>一回目', '</think>二回目', '<think>三回目']
        with patch('validation.core._ask', side_effect=responses) as asker:
            with self.assertRaises(CorrectionReasoningLeak) as ctx:
                correct(None, {}, 3, '旧原稿', [{'kind':'token'}])
            self.assertEqual(asker.call_count, 3)
            self.assertEqual(ctx.exception.rejected, '<think>三回目')

if __name__ == '__main__':
    unittest.main()


class RegenerationValidationTests(unittest.TestCase):
    def test_regenerate_tags_and_empty(self):
        from validation.core import needs_regeneration, regeneration_valid
        self.assertTrue(needs_regeneration(rule_check('ABC </think> DEF', 2)))
        self.assertTrue(needs_regeneration(rule_check('   ', 2)))
        self.assertFalse(needs_regeneration(rule_check('```json\n{}\n```', 2)))
        self.assertFalse(regeneration_valid('検討 <think> 出力'))
        self.assertFalse(regeneration_valid('prefix <|im_end|> suffix'))
        self.assertFalse(regeneration_valid('   '))
        self.assertTrue(regeneration_valid('読み上げ可能な本文です．'))
