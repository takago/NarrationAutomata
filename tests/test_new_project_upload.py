"""Protect PDF upload against project-selection-only state leaking in."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class NewProjectUploadTests(unittest.TestCase):
    def test_upload_does_not_reference_time_refine_internal(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SlideNarratorApp")
        upload = next(n for n in app.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "load_pdf")
        self.assertFalse(any(isinstance(n, ast.Name) and n.id == "time_refine_internal" for n in ast.walk(upload)))

    def test_project_switch_keeps_internal_mode(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SlideNarratorApp")
        switch = next(n for n in app.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "select_existing_project")
        self.assertTrue(any(a.arg == "time_refine_internal" for a in switch.args.kwonlyargs))
        self.assertTrue(any(isinstance(n, ast.Name) and n.id == "time_refine_internal" for n in ast.walk(switch)))

if __name__ == "__main__":
    unittest.main()
