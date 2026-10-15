"""Project-local persistent findings, settings, revision history and log."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

STAGES=('rules','individual','overall')
MODES=('report','confirm','auto')

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

