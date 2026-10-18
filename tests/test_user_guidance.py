"""Dependency-free checks for project-local guidance and LLM context wiring."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _store():
    spec = importlib.util.spec_from_file_location('guidance_store_test', ROOT / 'validation/store.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_guidance_survives_result_reset(tmp_path):
    store = _store()
    assert store.load_guidance(tmp_path) == ''
    store.save_guidance(tmp_path, 'スライド12の用語を確認')
    store.save(tmp_path, {'findings': [], 'stages': {}, 'completed': False})
    assert store.load_guidance(tmp_path) == 'スライド12の用語を確認'
    store.save_guidance(tmp_path, '')
    assert store.load_guidance(tmp_path) == ''


def test_guidance_is_passed_to_both_manual_checks():
    core = (ROOT / 'validation/core.py').read_text(encoding='utf-8')
    view = (ROOT / 'validation/ui.py').read_text(encoding='utf-8')
    assert 'hints: list[dict], user_guidance: str = ""' in core
    assert 'pages:list[tuple[int,str]], user_guidance: str = ""' in core
    assert '【最優先事項】' in core
    assert '参考情報' not in core
    assert '通常検査の「明らかな誤りのみ」という制限より優先' in core
    assert 'rule_check(text, page), self._guidance_snapshot)' in view
    assert "overall_check, client, owner.cfg['llm'], texts, self._guidance_snapshot)" in view


def test_ui_uses_project_storage_and_snapshot():
    view = (ROOT / 'validation/ui.py').read_text(encoding='utf-8')
    assert 'self.user_guidance = load_guidance(project)' in view
    assert 'save_guidance(project, self.user_guidance)' in view
    assert 'self._guidance_snapshot = self.user_guidance' in view
