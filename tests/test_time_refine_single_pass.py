"""Regression checks for single-pass time refinement."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'validation' / 'time_ui.py'

class SinglePassTests(unittest.TestCase):
    def test_no_obsolete_outer_cycle(self):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                             and node.target.id == 'cycle' for node in ast.walk(tree)))

    def test_single_result_schema(self):
        source = SOURCE.read_text(encoding='utf-8')
        self.assertIn("'result': None", source)
        self.assertIn("['time_refine']['result'] =", source)
        self.assertIn("metadata.get('result')", source)
        self.assertNotIn("metadata.get('rounds'", source)

if __name__ == '__main__':
    unittest.main()
