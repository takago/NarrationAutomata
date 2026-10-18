"""Project-local persistent findings, settings, revision history and log."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

STAGES=('rules','individual','overall')

def digest(text:str)->str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def directory(project:Path)->Path:
    return project/'validation'

def load(project:Path)->dict:
    path=directory(project)/'results.json'
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data,dict):return data
    except (OSError,ValueError):pass
    return {'findings':[], 'stages':{}, 'completed':False}

def save(project:Path,data:dict)->None:
    root=directory(project);root.mkdir(parents=True,exist_ok=True)
    target=root/'results.json';tmp=root/f'.results.{uuid4().hex}.tmp'
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,target)

def log(project:Path,message:str)->None:
    root=directory(project);root.mkdir(parents=True,exist_ok=True)
    with (root/'validation.log').open('a',encoding='utf-8') as f:
        f.write(f'[{datetime.now().isoformat(timespec="seconds")}] {message}\n')



def load_guidance(project: Path) -> str:
    """Keep user instructions independent from disposable inspection findings."""
    try:
        value = json.loads((directory(project) / 'settings.json').read_text(encoding='utf-8'))
        return str(value.get('user_guidance', '')) if isinstance(value, dict) else ''
    except (OSError, ValueError, TypeError):
        return ''


def save_guidance(project: Path, guidance: str) -> None:
    root = directory(project)
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'settings.json'
    temporary = root / f'.settings.{uuid4().hex}.tmp'
    temporary.write_text(json.dumps({'user_guidance': guidance}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, target)
