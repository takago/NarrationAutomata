"""VLM追加調査の進捗イベントと既存UIへの配線を検査する．"""
import ast
import io
import json
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]

class ClarificationProgressTests(unittest.TestCase):
    def test_cli_emits_structured_event(self):
        source = ROOT / 'slide_lecture.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'emit_pointer_clarification')
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), fn], type_ignores=[])
        ns = {'json': json}
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), ns)
        stream = io.StringIO()
        with redirect_stdout(stream):
            ns['emit_pointer_clarification'](12, 'completed', requested=2, added_blocks=3, changed_sentences=1)
        raw = stream.getvalue().strip()
        self.assertTrue(raw.startswith('[POINTER_CLARIFICATION] '))
        self.assertEqual(json.loads(raw.split('] ', 1)[1])['changed_sentences'], 1)

    def test_direct_callback(self):
        source = ROOT / 'slide_lecture.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'emit_pointer_clarification')
        module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), fn], type_ignores=[])
        ns = {'json': json}
        exec(compile(ast.fix_missing_locations(module), str(source), 'exec'), ns)
        callback = Mock()
        client = Mock(_slide_pointer_event_callback=callback)
        ns['emit_pointer_clarification'](5, 'detecting', client=client, requested=2)
        callback.assert_called_once_with({'page': 5, 'phase': 'detecting', 'requested': 2})

    def test_app_routes_subprocess_and_individual_events(self):
        app = (ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("line.startswith('[POINTER_CLARIFICATION]')", app)
        self.assertIn('self.handle_pointer_clarification(event)', app)
        self.assertIn('client._slide_pointer_event_callback =', app)
        self.assertIn('位置変更：', app)

if __name__ == '__main__':
    unittest.main()
