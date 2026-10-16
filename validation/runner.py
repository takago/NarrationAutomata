"""UI-independent orchestration of the existing automatic narration refinement.

The caller owns the execution lock, job lifecycle and cancellation handling.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime
from typing import Any, Callable

from nicegui import run
from statistics_store import run_with_statistics
from slide_lecture import make_client, generate_single_explanation
from .core import rule_check, individual_check, overall_check, synthesis_check, correct, regeneration_valid
from .store import digest, save, log

STAGE_NAMES = {
    'rules': 'ルールによる全体検査',
    'individual': 'LLMによるスライド別検査',
    'overall': 'LLMによる全体検査',
}

async def run_auto_refiner(owner: Any, stages, max_rounds: int, atomic_writer: Callable,
                           report: Callable, notify_change: Callable) -> dict:
    """Refine saved narration. No UI, lock acquisition or job finalization here.

    Returns the persisted validation state. Cancellation is read from owner,
    retaining the same behavior as the original view worker.
    """
    project = owner.paths.root
    pages = sorted(int(p.stem) for p in owner.paths.explanations_dir.glob('[0-9]*.txt')
                   if p.stem.isdigit() and int(p.stem) in set(owner.active_pages))
    history = []
    state = {'findings': [], 'stages': {}, 'completed': False,
             'auto_refiner': {'max_rounds': max_rounds, 'rounds': 0, 'history': history}}
    save(project, state)
    notify_change()
    client = None
    total = max_rounds * sum(len(pages) if stage != 'overall' else (len(pages)+7)//8+1 for stage in stages)
    done = 0
    previous_failures = set()
    for turn in range(1, max_rounds + 1):
        if owner.cancellation_requested:
            break
        modified = False
        round_findings = []
        round_errors = []
        detected = []
        state['auto_refiner']['rounds'] = turn
        for stage in stages:
            if owner.cancellation_requested:
                break
            report(f'オートリファイナー {turn}/{max_rounds}周：{STAGE_NAMES[stage]}',
                         progress=done/max(total, 1), stage='validation-'+stage)
            issues = []
            if stage == 'rules':
                for page in pages:
                    if owner.cancellation_requested: break
                    text = owner.paths.explanation(page).read_text(encoding='utf-8')
                    issues.extend(rule_check(text, page))
                    done += 1
                    await asyncio.sleep(0)
            elif stage == 'individual':
                client = client or await run.io_bound(make_client, owner.cfg['llm'])
                for page in pages:
                    if owner.cancellation_requested: break
                    text = owner.paths.explanation(page).read_text(encoding='utf-8')
                    try:
                        found = await run.io_bound(
                            run_with_statistics, project/'statistics.jsonl', page,
                            individual_check, client, owner.cfg['llm'], page, text,
                            owner.paths.page_image(page), rule_check(text, page))
                        issues.extend(found)
                    except Exception as exc:
                        round_errors.append(dict(page=page, stage=stage, kind='check_error',
                                                 description=f'検査エラー：{exc}', evidence=''))
                        log(project, f'オートリファイナー 個別検査 #{page} ERROR {exc}')
                    done += 1
                    report(f'{turn}/{max_rounds}周 個別検査 #{page}', page=page,
                                 index=done, total=total, progress=done/max(total, 1))
            else:
                client = client or await run.io_bound(make_client, owner.cfg['llm'])
                summaries = []
                for start in range(0, len(pages), 8):
                    if owner.cancellation_requested: break
                    part = pages[max(0, start-2):start+8]
                    texts = [(p, owner.paths.explanation(p).read_text(encoding='utf-8')) for p in part]
                    try:
                        found, summary = await run.io_bound(
                            run_with_statistics, project/'statistics.jsonl', None,
                            overall_check, client, owner.cfg['llm'], texts)
                        issues.extend(found)
                        if summary:
                            summaries.append((part[0], part[-1], summary))
                    except Exception as exc:
                        round_errors.append(dict(page=part[0], stage=stage, kind='check_error',
                                                 description=f'全体検査エラー：{exc}', evidence=''))
                        log(project, f'オートリファイナー 全体検査 ERROR {exc}')
                    done += 1
                if summaries and not owner.cancellation_requested:
                    try:
                        issues.extend(await run.io_bound(
                            run_with_statistics, project/'statistics.jsonl', None,
                            synthesis_check, client, owner.cfg['llm'], summaries, pages))
                    except Exception as exc:
                        round_errors.append(dict(page=pages[0], stage=stage, kind='check_error',
                                                 description=f'総合検査エラー：{exc}', evidence=''))
                        log(project, f'オートリファイナー 総合検査 ERROR {exc}')
                done += 1
            detected.extend(dict(f, stage=stage) for f in issues)
            grouped = OrderedDict()
            for issue in issues:
                page = int(issue['page'])
                if page in pages:
                    grouped.setdefault(page, []).append(dict(issue, stage=stage))
            for page, findings in grouped.items():
                if owner.cancellation_requested:
                    break
                path = owner.paths.explanation(page)
                before = path.read_text(encoding='utf-8')
                signature = (stage, page, digest(before))
                row = {'round': turn, 'page': page, 'stage': stage,
                       'issues': [x.get('description', '') for x in findings],
                       'action': '再生成' if stage == 'rules' else '自動校正',
                       'status': '未解決', 'before': before, 'after': before}
                history.append(row)
                if signature in previous_failures:
                    row['status'] = '前回と同じ原稿・問題のため再試行を省略'
                    round_findings.extend(findings)
                    continue
                try:
                    if stage == 'rules':
                        client = client or await run.io_bound(make_client, owner.cfg['llm'])
                        candidate = await run.io_bound(
                            run_with_statistics, project/'statistics.jsonl', page,
                            generate_single_explanation, client=client, cfg=owner.cfg['llm'],
                            pdf=owner.pdf, images=owner.images,
                            out_dir=owner.paths.explanations_dir, page=page,
                            active_pages=owner.active_pages, mode=owner.mode_code,
                            lang=owner.lang_code, persist=False)
                    else:
                        candidate = await run.io_bound(
                            run_with_statistics, project/'statistics.jsonl', page,
                            correct, client, owner.cfg['llm'], page, before, findings)
                    if not regeneration_valid(candidate):
                        raise ValueError('空文または特殊トークンを含むため採用できません')
                    if candidate.strip() == before.strip():
                        row['status'] = '原稿に変化なし'
                        previous_failures.add(signature)
                        round_findings.extend(findings)
                        continue
                    candidate = candidate.rstrip() + '\n'
                    # Only adopt if the on-disk source has not changed since inspection.
                    if path.read_text(encoding='utf-8') != before:
                        raise RuntimeError('検査後に原稿が変更されました')
                    atomic_writer(path, candidate)
                    owner.paths.cleanup_downstream(page, include_alignment=True)
                    row['after'] = candidate
                    row['status'] = '修正・保存済み（次周で再検査）'
                    modified = True
                except Exception as exc:
                    row['status'] = f'失敗：{exc}'
                    previous_failures.add(signature)
                    round_findings.extend(findings)
                    log(project, f'オートリファイナー #{page} {stage} ERROR {exc}')
                state['auto_refiner']['history'] = history
                save(project, state)
            state['stages'][stage] = {'count': len(issues), 'completed': not owner.cancellation_requested,
                                       'at': datetime.now().isoformat(timespec='seconds')}
        # A complete final pass is needed after the last changes to establish resolution.
        if not owner.cancellation_requested and modified and turn == max_rounds:
            report('最終修正の確認検査を実施中', stage='validation')
            round_findings = await verify_final(owner, stages, pages, project, client, round_errors)
        elif not modified or owner.cancellation_requested:
            round_findings = detected + round_errors
        state['findings'] = attach_hash(round_findings, owner)
        save(project, state)
        notify_change()
        if not modified:
            break
    state['completed'] = not owner.cancellation_requested
    if owner.cancellation_requested:
        state['completed'] = False
    save(project, state)
    return state

def attach_hash(findings, owner):
    return [dict(f, hash=digest(owner.paths.explanation(int(f['page'])).read_text(encoding='utf-8')))
            for f in findings if owner.paths.explanation(int(f['page'])).exists()]

async def verify_final(owner, stages, pages, project, client, errors):
    """Read-only final verification; no implicit adoption after the final round."""
    found = list(errors)
    for stage in stages:
        if owner.cancellation_requested: break
        if stage == 'rules':
            for page in pages:
                found.extend(dict(f, stage=stage) for f in rule_check(
                    owner.paths.explanation(page).read_text(encoding='utf-8'), page))
        elif stage == 'individual':
            client = client or await run.io_bound(make_client, owner.cfg['llm'])
            for page in pages:
                if owner.cancellation_requested: break
                txt = owner.paths.explanation(page).read_text(encoding='utf-8')
                try:
                    result = await run.io_bound(run_with_statistics, project/'statistics.jsonl', page,
                        individual_check, client, owner.cfg['llm'], page, txt,
                        owner.paths.page_image(page), rule_check(txt, page))
                    found.extend(dict(f, stage=stage) for f in result)
                except Exception as exc:
                    found.append(dict(page=page, stage=stage, kind='check_error',
                                      description=f'検査エラー：{exc}', evidence=''))
        else:
            client = client or await run.io_bound(make_client, owner.cfg['llm'])
            summaries = []
            for start in range(0, len(pages), 8):
                if owner.cancellation_requested: break
                part = pages[max(0, start-2):start+8]
                texts = [(p, owner.paths.explanation(p).read_text(encoding='utf-8')) for p in part]
                try:
                    result, summary = await run.io_bound(run_with_statistics, project/'statistics.jsonl',
                        None, overall_check, client, owner.cfg['llm'], texts)
                    found.extend(dict(f, stage=stage) for f in result)
                    if summary: summaries.append((part[0], part[-1], summary))
                except Exception as exc:
                    found.append(dict(page=part[0], stage=stage, kind='check_error',
                                      description=f'全体検査エラー：{exc}', evidence=''))
            if summaries and not owner.cancellation_requested:
                try:
                    result = await run.io_bound(run_with_statistics, project/'statistics.jsonl',
                        None, synthesis_check, client, owner.cfg['llm'], summaries, pages)
                    found.extend(dict(f, stage=stage) for f in result)
                except Exception as exc:
                    found.append(dict(page=pages[0], stage=stage, kind='check_error',
                                      description=f'総合検査エラー：{exc}', evidence=''))
    return found

