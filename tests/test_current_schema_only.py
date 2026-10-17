"""Ensure obsolete data formats are not silently accepted."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CurrentSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.source)

    def test_password_no_plaintext_branch(self):
        fn = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'verify_password')
        body = ast.get_source_segment(self.source, fn)
        self.assertNotIn('password == stored_hash', body)
        self.assertIn("if not stored_hash.startswith('pbkdf2:sha256:'):", body)

    def test_no_legacy_tts_success_override(self):
        self.assertNotIn("'legacy': False", self.source)
        self.assertNotIn("item['legacy']", self.source)

    def test_source_fallback_removed(self):
        fn = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == 'block_source')
        body = ast.get_source_segment(self.source, fn)
        self.assertNotIn('image_subpart', body)

if __name__ == '__main__':
    unittest.main()
