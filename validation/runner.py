"""UI-independent orchestration of the existing automatic narration refinement.

The caller owns the execution lock, job lifecycle and cancellation handling.
"""
from __future__ import annotations

import asyncio
import traceback
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

def checked_overall_result(value, part):
    """Validate the worker response before unpacking (including cancelled workers)."""
    if value is None:
        raise RuntimeError(
            f'スライド #{part[0]}〜#{part[-1]}：全体検査の実行結果が返されませんでした'
            '（非同期処理の中断または実行基盤の問題の可能性）')
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError(f'全体検査の戻り値が不正です（型：{type(value).__name__}）')
    issues, summary = value
    if not isinstance(issues, list) or not isinstance(summary, str):
        raise TypeError('全体検査の戻り値の型が不正です（指摘一覧／要約）')
    return issues, summary


async def run_auto_refiner(owner: Any, stages, atomic_writer: Callable,
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
             'auto_refiner': {'history': history}}
    save(project, state)
    notify_change()
    client = None
    total = sum(len(pages) if stage != 'overall' else (len(pages)+7)//8+1 for stage in stages)
    done = 0
    previous_failures = set()
    modified = False
    round_findings = []
    round_errors = []
    detected = []
    for stage in stages:
        if owner.cancellation_requested:
            break
        report(f'初回検査：{STAGE_NAMES[stage]}',
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
                report(f'初回検査：{STAGE_NAMES[stage]}（#{page}）', page=page,
                             index=done, total=total, progress=done/max(total, 1))
        else:
            client = client or await run.io_bound(make_client, owner.cfg['llm'])
            summaries = []
            for start in range(0, len(pages), 8):
                if owner.cancellation_requested: break
                part = pages[max(0, start-2):start+8]
                report(f'初回検査：{STAGE_NAMES[stage]}（#{part[0]}〜#{part[-1]}）',
                       page=part[0], stage='validation-'+stage)
                texts = [(p, owner.paths.explanation(p).read_text(encoding='utf-8')) for p in part]
                try:
                    overall_result = await run.io_bound(
                        run_with_statistics, project/'statistics.jsonl', None,
                        overall_check, client, owner.cfg['llm'], texts)
                    found, summary = checked_overall_result(overall_result, part)
                    issues.extend(found)
                    if summary:
                        summaries.append((part[0], part[-1], summary))
                except Exception as exc:
                    round_errors.append(dict(page=part[0], stage=stage, kind='check_error',
                                             description=f'全体検査エラー：{exc}', evidence=''))
                    log(project, f'オートリファイナー 全体検査 ERROR {exc}\n{traceback.format_exc()}')
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
        if not owner.cancellation_requested:
            report(f'自動修正：{STAGE_NAMES[stage]}', stage='validation-'+stage)
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
            row = {'page': page, 'stage': stage,
                   'issues': [x.get('description', '') for x in findings],
                   'action': '手動修正' if stage == 'rules' else '自動校正',
                   'status': '未解決', 'before': before, 'after': before}
            history.append(row)
            if stage == 'rules':
                row['status'] = '要手動修正（自動再生成しません）'
                round_findings.extend(findings)
                save(project, state)
                continue
            if signature in previous_failures:
                row['status'] = '前回と同じ原稿・問題のため再試行を省略'
                round_findings.extend(findings)
                continue
            try:
                report(f'自動修正：{STAGE_NAMES[stage]}（#{page}）',
                       page=page, stage='validation-'+stage)
                client = client or await run.io_bound(make_client, owner.cfg['llm'])
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
                row['status'] = '修正・保存済み'
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
    if not owner.cancellation_requested:
        report('最終確認：検査を開始', stage='validation')
        round_findings = await verify_final(owner, stages, pages, project, client, round_errors, report)
    else:
        round_findings = detected + round_errors
    state['findings'] = attach_hash(round_findings, owner)
    save(project, state)
    notify_change()
    state['completed'] = not owner.cancellation_requested
    if owner.cancellation_requested:
        state['completed'] = False
    save(project, state)
    return state

def attach_hash(findings, owner):
    return [dict(f, hash=digest(owner.paths.explanation(int(f['page'])).read_text(encoding='utf-8')))
            for f in findings if owner.paths.explanation(int(f['page'])).exists()]

async def verify_final(owner, stages, pages, project, client, errors, report=None):
    """Read-only final verification; no implicit adoption after the final round."""
    found = list(errors)
    for stage in stages:
        if owner.cancellation_requested: break
        if report is not None:
            report(f'最終確認：{STAGE_NAMES[stage]}', stage='validation-'+stage)
        if stage == 'rules':
            for page in pages:
                if owner.cancellation_requested: break
                found.extend(dict(f, stage=stage) for f in rule_check(
                    owner.paths.explanation(page).read_text(encoding='utf-8'), page))
        elif stage == 'individual':
            client = client or await run.io_bound(make_client, owner.cfg['llm'])
            for page in pages:
                if owner.cancellation_requested: break
                if report is not None:
                    report(f'最終確認：{STAGE_NAMES[stage]}（#{page}）', page=page,
                           stage='validation-'+stage)
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
                if report is not None:
                    report(f'最終確認：{STAGE_NAMES[stage]}（#{part[0]}〜#{part[-1]}）',
                           page=part[0], stage='validation-'+stage)
                texts = [(p, owner.paths.explanation(p).read_text(encoding='utf-8')) for p in part]
                try:
                    overall_result = await run.io_bound(run_with_statistics, project/'statistics.jsonl',
                        None, overall_check, client, owner.cfg['llm'], texts)
                    result, summary = checked_overall_result(overall_result, part)
                    found.extend(dict(f, stage=stage) for f in result)
                    if summary: summaries.append((part[0], part[-1], summary))
                except Exception as exc:
                    log(project, f'最終確認 全体検査 ERROR {exc}\n{traceback.format_exc()}')
                    found.append(dict(page=part[0], stage=stage, kind='check_error',
                                      description=f'全体検査エラー：{exc}', evidence=''))
            if summaries and not owner.cancellation_requested:
                if report is not None:
                    report('最終確認：LLMによる全体検査（総合検査）',
                           stage='validation-overall')
                try:
                    result = await run.io_bound(run_with_statistics, project/'statistics.jsonl',
                        None, synthesis_check, client, owner.cfg['llm'], summaries, pages)
                    found.extend(dict(f, stage=stage) for f in result)
                except Exception as exc:
                    found.append(dict(page=pages[0], stage=stage, kind='check_error',
                                      description=f'総合検査エラー：{exc}', evidence=''))
    return found



def unresolved_fix_failures(state: dict, paths: Any) -> list[dict]:
    """Return only repair failures for the *current* narration content.

    A failed attempt from an earlier round does not remain an unresolved error
    after a subsequent correction has changed the narration on disk.
    """
    unresolved = []
    for row in (state.get('auto_refiner') or {}).get('history', []):
        if not str(row.get('status', '')).startswith('失敗：'):
            continue
        try:
            page = int(row['page'])
            path = paths.explanation(page)
            if path.exists() and path.read_text(encoding='utf-8') == row.get('before'):
                unresolved.append(row)
        except (ValueError, TypeError, KeyError, OSError):
            continue
    return unresolved
