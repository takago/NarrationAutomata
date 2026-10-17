"""Voice-separated audio paths and verified synthesis cache signatures."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path


def signature(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def voice_directory(audio_root: Path, tts_cfg: dict) -> Path:
    model = str(tts_cfg.get('model') or 'unknown')
    voice = str(tts_cfg.get('voice') or 'unknown')
    readable = re.sub(r'[^A-Za-z0-9_.-]+', '_', model + '_' + voice).strip('._')[:75] or 'voice'
    # Keep a stable suffix to avoid sanitization collisions and unsafe folder names.
    identity = signature({'model': model, 'voice': voice, 'base_url': tts_cfg.get('base_url', '')})[:10]
    return audio_root / f'{readable}_{identity}'


def audio_path(audio_root: Path, page: int, tts_cfg: dict) -> Path:
    return voice_directory(audio_root, tts_cfg) / f'{page:03d}.mp3'


def metadata_path(media: Path) -> Path:
    return media.with_suffix(media.suffix + '.cache.json')


def cache_matches(media: Path, digest: str) -> bool:
    if not media.is_file() or media.stat().st_size == 0:
        return False
    try:
        return json.loads(metadata_path(media).read_text(encoding='utf-8')).get('signature') == digest
    except (OSError, ValueError, TypeError):
        return False


def save_signature(media: Path, digest: str) -> None:
    target = metadata_path(media)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.tmp')
    temp.write_text(json.dumps({'signature': digest}), encoding='utf-8')
    temp.replace(target)


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open('rb') as inp:
        for chunk in iter(lambda: inp.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def tts_signature(text_path: Path, tts_cfg: dict, filter_config_path: Path, lang: str, project_dir: Path) -> str:
    """Cheap conservative check before LLM-based reading conversion.

    Hash dictionary files to notice edits even if raw narration is unchanged.
    """
    project_json = project_dir / 'project.json'
    try:
        raw_project = json.loads(project_json.read_text(encoding='utf-8'))
        project_dictionary = raw_project.get('tts_dictionary', {})
    except (OSError, ValueError, TypeError, AttributeError):
        project_dictionary = {}
    # Include all small project yaml dictionary candidates used by deployments.
    dictionaries = {str(p.relative_to(project_dir)): file_digest(p)
                    for p in project_dir.glob('*.yaml') if 'yomi' in p.name.lower() or 'tts' in p.name.lower()}
    return signature({'raw': file_digest(text_path), 'tts': tts_cfg,
                      'filter': file_digest(filter_config_path), 'project_dictionaries': dictionaries, 'project_dictionary': project_dictionary,
                      'lang': lang, 'cache_version': 2})
