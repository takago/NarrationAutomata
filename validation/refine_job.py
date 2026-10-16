"""Project-local refinement progress and live server-side task references."""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ACTIVE: dict[tuple[str, str], Any] = {}

def key(username: str, project: Path) -> tuple[str, str]:
    return (username, str(Path(project).resolve()))

def register(username: str, project: Path, view: Any) -> None:
    ACTIVE[key(username, project)] = view

def unregister(username: str, project: Path, view: Any) -> None:
    k = key(username, project)
    if ACTIVE.get(k) is view:
        ACTIVE.pop(k, None)

def running(username: str, project: Path):
    return ACTIVE.get(key(username, project))

def read(project: Path, kind: str) -> dict:
    try:
        value = json.loads((Path(project) / 'validation' / f'{kind}_job.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def write(project: Path, kind: str, **updates) -> dict:
    path = Path(project) / 'validation' / f'{kind}_job.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    value = read(project, kind)
    value.update(updates)
    value['updated_at'] = datetime.now().isoformat(timespec='seconds')
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)
    return value
