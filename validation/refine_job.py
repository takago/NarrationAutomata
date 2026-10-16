"""Project-local refinement progress and live server-side task references."""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ACTIVE: dict[tuple[str, str], Any] = {}


class PipelineContentRefine:
    """Marker for an automatic content refinement owned by the pipeline."""


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


def running_as(username: str, project: Path | None, view_type: type):
    """Return a live refinement only if it belongs to the requested view type.

    A single project registry is shared by content and time refinement.
    Never treat another kind of refinement as the current view's worker.
    """
    if project is None:
        return None
    view = running(username, project)
    return view if isinstance(view, view_type) else None


def finish_content(project: Path, *, cancelled: bool) -> dict:
    """Finalize content refinement while preserving an earlier failure/cancel.

    The final message and the preexisting terminal status are intentionally
    retained, exactly as in the two original content-worker finally blocks.
    """
    snapshot = read(project, 'content')
    state = snapshot.get('state', 'running')
    if state not in ('failed', 'cancelled'):
        state = 'cancelled' if cancelled else 'completed'
    return write(project, 'content', state=state, message=snapshot.get('message', ''))
