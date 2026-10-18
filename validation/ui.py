"""User-driven quality checks and a single, save-gated narration editor."""
from __future__ import annotations

import asyncio
import traceback
import difflib
import html
import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from nicegui import ui, run, background_tasks
from statistics_store import run_with_statistics
from slide_lecture import make_client, generate_single_explanation
from .core import rule_check, individual_check, overall_check, synthesis_check, correct, regeneration_valid
from .store import STAGES, digest, load, log, save, load_guidance, save_guidance
from . import refine_job

LOGGER = logging.getLogger(__name__)

STAGE_DESCRIPTIONS = {
    'rules': '思考タグ・特殊トークン・空文などの形式異常を全スライドから検出',
    'individual': 'スライドごとに文章の自然さ・説明内容とスライド画像の整合性を確認',
    'overall': '複数スライドにまたがる説明の重複・矛盾・用語の不統一を確認',
}

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


class ValidationView:
    def __init__(self, controller: Any, lock: Any, atomic_writer: Any):
        self.owner = controller
        self.execution_lock = lock
        self.atomic_writer = atomic_writer
        self.busy = False
        self.controls = None
        self.progress = None
        self.running_spinner = None
        self.bar = None
        self.results = None
        self.selection = {s: True for s in STAGES}
        self._project_key = None
        self.user_guidance = ""
        self._guidance_snapshot = ""
        self._running_project = None
        self._last_status = None
        self._drafts: dict[int, str] = {}
        self._originals: dict[int, str] = {}
        self._open_page = None
        self._progress_value = 0.0
        self._start_button = None
        self._edit_status = None
        self._edit_bar = None
        self._diff_panels: dict[int, tuple[Any, Any]] = {}
        self._diff_tasks: dict[int, asyncio.Task] = {}
        self._shown_busy = None
        self._shown_pipeline = None

    def build(self):
        ui.label('リファイナー').classes('text-h5')
        ui.label('検査結果を確認し，必要な箇所を個別に修正・保存できます．残った指摘は一括で自動校正・保存できます．検査は手動で開始します．').classes('text-caption text-slate-400')
        ui.add_css('''
            .validation-narration-editor .q-field__control { min-height: 300px; height: 300px; }
            .validation-narration-editor textarea { line-height: 1.55; }
            .validation-narration-diff > div { height: 300px; max-height: 300px; overflow-y: auto; line-height: 1.55; }
        ''')
        self.controls = ui.column().classes('w-full gap-3')
        with ui.row().classes('items-center gap-2'):
            self.running_spinner = ui.spinner(size='sm')
            self.running_spinner.visible = False
            self.progress = ui.label('検査待機中').classes('text-sm text-slate-400')
        self.bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
        self._edit_status = ui.label('').classes('text-sm text-slate-400')
        self._edit_bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
        self._edit_bar.set_visibility(False)
        self.results = ui.column().classes('w-full gap-2')
        self.refresh()

    def _on_guidance_change(self, event):
        if self._actions_locked():
            return
        project = self.owner.paths.root if self.owner.paths else None
        if project is None:
            return
        self.user_guidance = str(event.value or '')
        save_guidance(project, self.user_guidance)

    def _actions_locked(self) -> bool:
        project = self.owner.paths.root if self.owner.paths else None
        return (self.busy or self.owner.processing or self.execution_lock.is_locked()
                or (project is not None and refine_job.running(self.owner.username, project) is not None))

    def _pipeline_controls_hidden(self) -> bool:
        """Hide editing/inspection controls while the generation pipeline is active.

        The validation worker itself uses owner.processing as well, so keep
        the manual validation cancellation control available in that case.
        """
        project = self.owner.paths.root if self.owner.paths else None
        worker = refine_job.running(self.owner.username, project) if project else None
        # Time refinement owns the project while it is shortening narration.
        # Treat it like the pipeline: hide validation/editing buttons even
        # during phases when it temporarily releases the execution lock.
        time_refine_running = worker is not None and hasattr(worker, '_target_project')
        return time_refine_running or (bool(self.owner.processing) and not self.busy)

    def _sync_controls_on_state_change(self):
        """Synchronize manual controls with the pipeline and live jobs."""
        if self.controls is None or getattr(self.controls, 'is_deleted', False):
            return
        project = self.owner.paths.root if self.owner.paths else None
        self.restore_progress()
        hidden = self._pipeline_controls_hidden()
        if self.busy != self._shown_busy or hidden != self._shown_pipeline:
            self.refresh()

    def refresh(self):
        project = self.owner.paths.root if self.owner.paths else None
        key = str(project) if project else None
        if key != self._project_key:
            self._project_key = key
            self.user_guidance = load_guidance(project) if project else ""
            self._drafts.clear()
            self._originals.clear()
            self._cancel_diff_tasks()
            self._open_page = None
        if self.controls is None:
            return
        # Determine the live state *before* rebuilding the controls.
        self.restore_progress()
        self._shown_busy = self.busy
        self._shown_pipeline = self._pipeline_controls_hidden()
        self.controls.clear()
        self._start_button = None
        with self.controls:
            if project is None:
                ui.label('プロジェクトを選択してください．')
                self.results.clear()
                return
            if self._shown_pipeline:
                ui.label('生成処理中のため，操作ボタンは非表示です．検査結果は閲覧できます．').classes('text-caption text-slate-400')
            elif self.busy:
                ui.label('リファイナー実行中').classes('text-blue-300 font-bold text-sm')
                ui.button('リファイナーを中断', icon='stop', on_click=self.owner.request_cancel).props('outline color=negative')
            else:
                ui.label('追加指示（任意）').classes('text-sm font-bold')
                ui.label('ビデオを見て気付いた点や改善方針を入力してください．LLMは内容を確認し，妥当な指摘だけを採用します．').classes('text-xs text-slate-400')
                ui.textarea(placeholder='例：スライド12の「アドレス空間」は「仮想アドレス空間」と表現する方が適切か確認してください．',
                            value=self.user_guidance,
                            on_change=self._on_guidance_change).props('outlined autogrow').classes('w-full')
                ui.label('入力内容はプロジェクト別に自動保存されます．空欄なら従来どおりの検査です．').classes('text-xs text-slate-400')
                ui.separator()
                for stage in STAGES:
                    with ui.row().classes('w-full items-center gap-3'):
                        ui.checkbox(STAGE_NAMES[stage], value=self.selection[stage],
                                    on_change=lambda e, s=stage: self.selection.__setitem__(s, bool(e.value)))
                        ui.label(STAGE_DESCRIPTIONS[stage]).classes('text-xs text-slate-400')
                self._start_button = ui.button('検査を開始', icon='play_arrow', on_click=self.start).props('outline')
                self._start_button.set_enabled(not self._actions_locked())
                ui.label('実行時に前回の検査結果をすべて破棄します．検査中は閲覧のみ可能です．').classes('text-caption text-slate-400')
        self.restore_progress()
        self.render_results()

    def restore_progress(self):
        project = self.owner.paths.root if self.owner.paths else None
        if project is None or self.progress is None:
            return
        snapshot = refine_job.read(project, "content")
        live = refine_job.running(self.owner.username, project)
        self.busy = isinstance(live, ValidationView) or (self._running_project == project and self.busy)
        if self.running_spinner is not None:
            self.running_spinner.visible = self.busy
        if snapshot:
            self.progress.text = snapshot.get("message", "検査待機中")
            self._progress_value = snapshot.get("progress") or 0.0
            self.bar.value = self._progress_value
        if self._start_button is not None:
            self._start_button.set_enabled(not self._actions_locked())

    def _safe_render_results(self):
        try:
            if self.results is not None and not getattr(self.results, "is_deleted", False):
                self.render_results()
        except Exception:
            pass  # A detached client must never interrupt a server worker.

    def _pages(self):
        if not self.owner.paths:
            return []
        # 検査するのは，ビデオ化対象として選択されたスライドのみ．
        # 原稿がまだ存在しないページは従来どおり対象外とする．
        active = set(self.owner.active_pages)
        return sorted(
            int(p.stem)
            for p in self.owner.paths.explanations_dir.glob('[0-9]*.txt')
            if p.stem.isdigit() and int(p.stem) in active
        )

    def _status(self, text, *, page=None, index=None, total=None, progress=None, stage='validation'):
        try:
            if self.progress is not None and not getattr(self.progress, "is_deleted", False):
                self.progress.text = text
        except Exception:
            pass
        if progress is not None:
            self._progress_value = min(1.0, max(0.0, progress))
            try:
                if self.bar is not None and not getattr(self.bar, "is_deleted", False):
                    self.bar.value = self._progress_value
            except Exception:
                pass
        if self._running_project is not None:
            refine_job.write(self._running_project, "content", state="running", message=text, progress=self._progress_value, stage=stage, page=page)
        # index/total are inspection work units, not slide numbers.
        # Keep them for the inspection progress bar, but report actual slide
        # counts to the shared sidebar status display.
        pages = self._pages()
        slide_index = pages.index(page) + 1 if page in pages else None
        self.owner.update_job_status('running', stage=stage, message=text,
                                     current_page=page, current_index=slide_index,
                                     total_count=len(pages), progress=self._progress_value)

    def start(self):
        if self._actions_locked():
            ui.notify('ほかの処理が実行中です．', type='warning')
            return
        if not self.owner.write_access_allowed():
            return
        stages = tuple(s for s in STAGES if self.selection[s])
        if not stages:
            ui.notify('少なくとも1つの検査を選択してください．', type='warning')
            return
        if not self._pages():
            ui.notify('保存済みナレーションがありません．', type='warning')
            return
        if any(self._drafts.get(p) != t for p, t in self._originals.items()):
            ui.notify('未保存の編集があります．先に保存するか「元に戻す」を押してください．', type='warning')
            return
        self._guidance_snapshot = self.user_guidance
        self.busy = True  # タスクの起動を待たずにボタンを無効化する
        self._running_project = self.owner.paths.root
        refine_job.register(self.owner.username, self._running_project, self)
        refine_job.write(self._running_project, "content", state="running", message="検査を開始しています", progress=0.0)
        self.owner.current_task = background_tasks.create(
            self._worker(stages),
            name="content-refine")
        self.refresh()

    async def _worker(self, stages):
        owner = self.owner
        if not await self.execution_lock.acquire(owner.username, 'ナレーション品質検査', owner):
            self.busy = False
            refine_job.write(self._running_project, 'content', state='failed', message='ほかのユーザの処理が実行中です．')
            refine_job.unregister(owner.username, self._running_project, self)
            self._running_project = None
            return
        self.busy = True
        # 前の生成工程の中断要求を新しいジョブへ持ち越さない．
        owner.cancellation_requested = False
        owner.set_processing(True)
        owner.current_task = asyncio.current_task()
        owner.update_job_status('running', stage='validation',
                                message='リファイナー：検査を開始しています',
                                cancellation_requested=False, progress=0.0,
                                current_page=None, current_index=None,
                                total_count=None, llm_metrics=None, tts_metrics=None)
        project = owner.paths.root
        pages = self._pages()
        self._drafts.clear()
        self._originals.clear()
        self._cancel_diff_tasks()
        self._open_page = None
        state = {'findings': [], 'stages': {}, 'completed': False}
        save(project, state)
        self._safe_render_results()
        total_units = sum(len(pages) if s != 'overall' else (len(pages)+7)//8+1 for s in stages)
        done = 0
        seen = set()
        client = None

        def update_progress(stage, label, page=None):
            self._status(f'{STAGE_NAMES[stage]}：{label} （{done}/{total_units}）',
                         page=page, index=done, total=total_units,
                         progress=done/max(total_units, 1), stage='validation-'+stage)

        def record(issues, stage):
            changed = False
            for issue in issues:
                page = int(issue['page'])
                if page not in pages:
                    continue
                key = (page, stage, issue.get('kind'), issue.get('description'), issue.get('evidence'))
                if key in seen:
                    continue
                seen.add(key)
                result = dict(issue, stage=stage,
                              hash=digest(owner.paths.explanation(page).read_text(encoding='utf-8')))
                state['findings'].append(result)
                changed = True
            if changed:
                save(project, state)
                self._safe_render_results()

        try:
            for stage in stages:
                if owner.cancellation_requested:
                    break
                update_progress(stage, '開始')
                if stage == 'rules':
                    for page in pages:
                        if owner.cancellation_requested: break
                        text = owner.paths.explanation(page).read_text(encoding='utf-8')
                        record(rule_check(text, page), stage)
                        done += 1
                        update_progress(stage, f'スライド #{page}', page)
                        await asyncio.sleep(0)
                elif stage == 'individual':
                    client = client or await run.io_bound(make_client, owner.cfg['llm'])
                    for page in pages:
                        if owner.cancellation_requested: break
                        text = owner.paths.explanation(page).read_text(encoding='utf-8')
                        try:
                            issues = await run.io_bound(
                                run_with_statistics, project/'statistics.jsonl', page,
                                individual_check, client, owner.cfg['llm'], page, text,
                                owner.paths.page_image(page), rule_check(text, page), self._guidance_snapshot)
                            record(issues, stage)
                        except Exception as exc:
                            log(project, f'個別検査 #{page} ERROR {exc}')
                            record([dict(page=page, kind='check_error', description=f'検査エラー：{exc}', evidence='')], stage)
                        done += 1
                        update_progress(stage, f'スライド #{page}', page)
                else:
                    client = client or await run.io_bound(make_client, owner.cfg['llm'])
                    summaries = []
                    for start in range(0, len(pages), 8):
                        if owner.cancellation_requested: break
                        part = pages[max(0, start-2):start+8]
                        texts = [(p, owner.paths.explanation(p).read_text(encoding='utf-8')) for p in part]
                        try:
                            overall_result = await run.io_bound(
                                run_with_statistics, project/'statistics.jsonl', None,
                                overall_check, client, owner.cfg['llm'], texts, self._guidance_snapshot)
                            issues, summary = checked_overall_result(overall_result, part)
                            record(issues, stage)
                            if summary:
                                summaries.append((part[0], part[-1], summary))
                        except Exception as exc:
                            log(project, f'全体検査 {part[0]}-{part[-1]} ERROR {exc}\n{traceback.format_exc()}')
                            record([dict(page=part[0], kind='check_error', description=f'検査エラー：{exc}', evidence='')], stage)
                        done += 1
                        update_progress(stage, f'スライド #{part[0]}〜#{part[-1]}')
                    if summaries and not owner.cancellation_requested:
                        try:
                            issues = await run.io_bound(
                                run_with_statistics, project/'statistics.jsonl', None,
                                synthesis_check, client, owner.cfg['llm'], summaries, pages)
                            record(issues, stage)
                        except Exception as exc:
                            log(project, f'全体総合検査 ERROR {exc}')
                            record([dict(page=pages[0],kind='check_error',description=f'総合検査エラー：{exc}', evidence='')],stage)
                    done += 1
                    update_progress(stage, '全体総合評価')
                state['stages'][stage] = {'count':sum(f['stage']==stage for f in state['findings']),
                                           'completed':not owner.cancellation_requested,
                                           'at':datetime.now().isoformat(timespec='seconds')}
                save(project, state)
            state['completed'] = not owner.cancellation_requested
            save(project, state)
            message = '検査を中断しました（途中結果）．' if owner.cancellation_requested else f'検査終了：{len(set(f["page"] for f in state["findings"]))}スライドに指摘があります．'
            self._status(message, progress=1.0 if not owner.cancellation_requested else None)
            owner.update_job_status('cancelled' if owner.cancellation_requested else 'completed',
                                    stage='validation',message=message,
                                    progress=None if owner.cancellation_requested else 1.0)
            log(project, message)
        except asyncio.CancelledError:
            self._status('検査を中断しました（途中結果）．')
            owner.update_job_status('cancelled', stage='validation', message=self.progress.text)
        except Exception as exc:
            self._status(f'品質検査エラー：{exc}')
            refine_job.write(project, 'content', state='failed')
            owner.update_job_status('failed', stage='validation', message=self.progress.text)
            log(project, f'ERROR {type(exc).__name__}: {exc}')
            try:
                ui.notify(self.progress.text, type='negative')
            except Exception:
                pass
        finally:
            self._finish_content_worker(project)
            self._safe_render_results()

    def _finish_content_worker(self, project):
        """Shared finalization for inspection and bulk correction workers.

        Keep each caller's UI refresh separate: the inspection renders results,
        whereas bulk correction refreshes the whole view.
        """
        owner = self.owner
        self.busy = False
        # 永続化・登録解除の失敗は後続の解放処理を妨げない．
        try:
            refine_job.finish_content(project, cancelled=owner.cancellation_requested)
        except Exception:
            LOGGER.exception('リファイナーの終了状態保存に失敗しました')
        try:
            refine_job.unregister(owner.username, project, self)
        except Exception:
            LOGGER.exception('リファイナーの登録解除に失敗しました')
        self._running_project = None
        try:
            owner._finalize_cancel_request()
        except Exception:
            LOGGER.exception('リファイナーの中断状態確定に失敗しました')
        finally:
            owner._complete_background_job()

    async def _bulk_correct_worker(self, project, tasks):
        """Correct unresolved, unchanged drafts; persist each successful page once."""
        owner = self.owner
        if not await self.execution_lock.acquire(owner.username, '残りの一括自動校正', owner):
            self.busy = False
            refine_job.write(project, 'content', state='failed', message='ほかのユーザの処理が実行中です．')
            refine_job.unregister(owner.username, project, self)
            self._running_project = None
            self.refresh()
            return
        # 前の生成工程の中断要求を新しいジョブへ持ち越さない．
        owner.cancellation_requested = False
        owner.set_processing(True)
        owner.current_task = asyncio.current_task()
        owner.update_job_status('running', stage='validation-bulk',
                                message='リファイナー：一括自動校正を開始しています',
                                cancellation_requested=False, progress=0.0,
                                current_page=None, current_index=None,
                                total_count=len(tasks), llm_metrics=None, tts_metrics=None)
        success = 0
        failed = 0
        skipped = 0
        try:
            client = await run.io_bound(make_client, owner.cfg['llm'])
            for index, (page, expected, issues) in enumerate(tasks, 1):
                if owner.cancellation_requested:
                    break
                self._status(f'一括自動校正・保存：スライド #{page}（{index}/{len(tasks)}）',
                             page=page, progress=(index-1)/len(tasks), stage='validation-bulk')
                path = owner.paths.explanation(page)
                try:
                    if not path.exists() or path.read_text(encoding='utf-8') != expected:
                        skipped += 1
                        log(project, f'一括校正 #{page} SKIP 原稿が変更されています')
                        continue
                    candidate = await run.io_bound(
                        run_with_statistics, project/'statistics.jsonl', page,
                        correct, client, owner.cfg['llm'], page, expected, issues)
                    if not regeneration_valid(candidate):
                        raise ValueError('生成された原稿が空か，特殊トークンを含みます')
                    if not candidate.strip() or candidate.strip() == expected.strip():
                        skipped += 1
                        log(project, f'一括校正 #{page} SKIP 原稿に変更なし')
                        continue
                    if path.read_text(encoding='utf-8') != expected:
                        skipped += 1
                        log(project, f'一括校正 #{page} SKIP 校正中に原稿が変更されました')
                        continue
                    candidate = candidate.rstrip() + '\n'
                    self.atomic_writer(path, candidate)
                    owner.paths.cleanup_downstream(page, include_alignment=True)
                    # Reload rather than using a stale snapshot: only remove findings
                    # for a successfully saved page, leaving all other issues intact.
                    state = load(project)
                    state['findings'] = [f for f in state.get('findings', [])
                                         if int(f['page']) != page]
                    save(project, state)
                    self._drafts.pop(page, None)
                    self._originals.pop(page, None)
                    log(project, f'一括校正 #{page} 修正・保存済み')
                    success += 1
                except Exception as exc:
                    failed += 1
                    log(project, f'一括校正 #{page} ERROR {exc}\n{traceback.format_exc()}')
                self._safe_render_results()
            message = (f'一括校正終了：保存 {success}件 ／ 変更なし・対象外 {skipped}件 ／ '
                       f'失敗 {failed}件' + ('（中断）' if owner.cancellation_requested else ''))
            self._status(message, progress=None if owner.cancellation_requested else 1.0,
                         stage='validation-bulk')
            owner.update_job_status('cancelled' if owner.cancellation_requested else 'completed',
                                    stage='validation-bulk', message=message)
            log(project, message)
        except asyncio.CancelledError:
            self._status('一括自動校正を中断しました．', stage='validation-bulk')
        except Exception as exc:
            self._status(f'一括校正エラー：{exc}', stage='validation-bulk')
            refine_job.write(project, 'content', state='failed')
            log(project, f'一括校正 ERROR {exc}\n{traceback.format_exc()}')
        finally:
            self._finish_content_worker(project)
            self.refresh()

    def start_bulk_correct(self):
        """Use the last inspection findings without rerunning checks."""
        owner = self.owner
        if self._actions_locked():
            ui.notify('ほかの処理が実行中です．', type='warning')
            return
        if not owner.write_access_allowed() or not owner.paths:
            return
        project = owner.paths.root
        state = load(project)
        grouped = OrderedDict()
        for issue in state.get('findings', []):
            if issue.get('stage') not in ('individual', 'overall') or issue.get('kind') == 'check_error':
                continue
            grouped.setdefault(int(issue['page']), []).append(issue)
        tasks = []
        for page, issues in grouped.items():
            path = owner.paths.explanation(page)
            if not path.exists():
                continue
            current = path.read_text(encoding='utf-8')
            # Never discard a draft, even when its editor is currently collapsed.
            if page in self._drafts and self._drafts[page] != self._originals.get(page, current):
                continue
            # A previous correction invalidates an earlier inspection.
            if any(f.get('hash') and f['hash'] != digest(current) for f in issues):
                continue
            tasks.append((page, current, issues))
        if not tasks:
            ui.notify('一括校正できる未解決の指摘がありません．未保存の編集や検査エラーは対象外です．', type='warning')
            return
        self.busy = True
        self._running_project = project
        refine_job.register(owner.username, project, self)
        refine_job.write(project, 'content', state='running', message='一括自動校正を開始します', progress=0.0)
        owner.current_task = background_tasks.create(self._bulk_correct_worker(project, tasks), name='validation-bulk-correct')
        self.refresh()

    def render_results(self):
        if self.results is None:
            return
        self._cancel_diff_tasks()
        self._diff_panels.clear()
        self.results.clear()
        if not self.owner.paths:
            return
        state = load(self.owner.paths.root)
        grouped: OrderedDict[int, list[dict]] = OrderedDict()
        for issue in state.get('findings', []):
            grouped.setdefault(int(issue['page']), []).append(issue)
        check_errors = [f for f in state.get('findings', []) if f.get('kind') == 'check_error']
        manual_rule_pages = {int(f['page']) for f in state.get('findings', []) if f.get('stage') == 'rules'}
        error_pages = {int(f['page']) for f in check_errors} | manual_rule_pages
        with self.results:
            if check_errors or manual_rule_pages:
                with ui.card().classes('w-full border-2 border-red-500 bg-red-50 dark:bg-red-950'):
                    ui.label(f'要確認：検査エラー {len(check_errors)}件').classes('font-bold text-red-700 dark:text-red-200')
                    if manual_rule_pages:
                        ui.label(f'ルール検査による要手動修正：{len(manual_rule_pages)}スライド（自動再生成しません）').classes('font-bold text-amber-600')
                    ui.label('赤く表示されたスライドの詳細を確認してください．検査エラーは原稿の誤りとは限らず，通信・LLM応答などが原因の場合があります．').classes('text-sm')
                    for f in check_errors:
                        ui.label(f'#{f.get("page", "?")}・{STAGE_NAMES.get(f.get("stage"), f.get("stage", "?"))}：{f.get("description", "検査失敗")}').classes('text-sm text-red-700 dark:text-red-200')
            ui.label(f'検出された問題：残り {len(grouped)} スライド').classes('text-subtitle1 font-medium')
            if grouped and not self.busy and not self._pipeline_controls_hidden():
                ui.button('残りを一括で自動校正・保存', icon='auto_fix_high',
                          on_click=self.start_bulk_correct).props('outline color=primary').bind_enabled_from(
                              self, 'busy', backward=lambda busy: not busy and not self._actions_locked())
                ui.label('未解決のLLM指摘のみを対象にします．未保存の編集，検査エラー，ルール検査だけの指摘は対象外です．校正後の自動再検査は行いません．').classes('text-xs text-slate-400')
            if grouped:
                ui.label('以下のスライドには未解決の指摘があります．内容を確認し，必要な処置を行ってください．').classes('text-sm text-amber-700 dark:text-amber-300')
            if not grouped:
                ui.label('検査結果はありません．').classes('text-slate-400')
            for page, issues in sorted(grouped.items(), key=lambda entry: (entry[0] not in error_pages, entry[0])):
                with ui.expansion(group=f'validation-{id(self)}', value=page == self._open_page or (self._open_page is None and page in error_pages)).classes('w-full border-2 border-red-500 rounded' if page in error_pages else 'w-full border rounded') as panel:
                    with panel.add_slot('header'):
                        with ui.column().classes('gap-1'):
                            ui.label(f'スライド #{page} ・ {len(issues)}件の指摘' + (' ・ ルール検査：手動修正が必要' if page in manual_rule_pages else ' ・ 検査／修正エラー' if page in error_pages else '')).classes('font-semibold text-red-600 dark:text-red-300' if page in error_pages else 'font-semibold')
                            for issue in issues:
                                ui.label(f'{STAGE_NAMES.get(issue["stage"],issue["stage"])}：{issue.get("description", "")}').classes('text-xs text-slate-500')
                    panel.on_value_change(lambda e,p=page: self._remember_open(p, e.value))
                    for issue in issues:
                        if issue.get('evidence'):
                            ui.label('根拠：'+str(issue['evidence'])).classes('text-caption text-slate-400')
                    path = self.owner.paths.explanation(page)
                    current = path.read_text(encoding='utf-8') if path.exists() else ''
                    if page not in self._originals:
                        self._originals[page] = current
                        self._drafts[page] = current
                    # Matched columns and a shared action row; keep the editor as the only input.
                    with ui.column().classes('w-full gap-2'):
                        with ui.row().classes('w-full gap-3 items-start flex-wrap'):
                            with ui.column().classes('flex-1 min-w-[320px] gap-2'):
                                ui.label('ナレーション編集').classes('text-xs text-slate-400')
                                area = ui.textarea(value=self._drafts[page]).props('outlined rows=12').classes('w-full validation-narration-editor')
                                area.on('update:model-value', lambda e,p=page: self._draft_changed(p, e.args))
                                if self._actions_locked():
                                    area.props('readonly')
                            with ui.column().classes('flex-1 min-w-[320px] gap-2'):
                                diff_label = ui.label('検査時点の原稿との差分（赤：削除，緑：追加）').classes('text-xs text-slate-400')
                                diff_panel = ui.html('').classes('w-full text-sm validation-narration-diff')
                                self._diff_panels[page] = (diff_label, diff_panel)
                                self._update_diff(page)
                        if not self._pipeline_controls_hidden():
                          with ui.row().classes('w-full justify-end gap-2 flex-wrap'):
                            for title, cb, icon in (
                                ('再生成',lambda p=page,a=area:self._edit_llm(p,a,True),'refresh'),
                                ('自動校正',lambda p=page,a=area:self._edit_llm(p,a,False),'auto_fix_high'),
                                ('元に戻す',lambda p=page,a=area:self._reset(p,a),'undo'),
                                ('保存',lambda p=page,a=area:self._save_page(p,a),'save')):
                                ui.button(title, icon=icon, on_click=cb).props('dense outline' if title!='保存' else 'dense color=primary').classes('min-w-[112px]').bind_enabled_from(self,'busy',backward=lambda busy:not busy and not self._actions_locked())
            with ui.expansion('検査ログ',icon='article').classes('w-full'):
                logfile=self.owner.paths.root/'validation'/'validation.log'
                if logfile.exists():
                    ui.textarea(value='\n'.join(logfile.read_text(encoding='utf-8').splitlines()[-120:])).props('readonly outlined').classes('w-full')

    @staticmethod
    def _diff_markup(before: str, after: str) -> str:
        """Escape LLM text; highlight only changed spans in the latest draft update."""
        matcher = difflib.SequenceMatcher(None, before, after, autojunk=len(before) + len(after) > 4000)
        chunks = []
        for operation, i, j, k, m in matcher.get_opcodes():
            if operation == 'equal':
                chunks.append(html.escape(after[k:m]))
            else:
                if operation in ('replace', 'delete'):
                    chunks.append('<del style="background:#fee2e2;color:#991b1b">' + html.escape(before[i:j]) + '</del>')
                if operation in ('replace', 'insert'):
                    chunks.append('<ins style="background:#dcfce7;color:#166534">' + html.escape(after[k:m]) + '</ins>')
        return '<div style="white-space:pre-wrap;overflow-wrap:anywhere;height:300px;max-height:300px;overflow-y:auto;padding:10px;border:1px solid #9ca3af;border-radius:6px">' + ''.join(chunks) + '</div>'

    def _cancel_diff_tasks(self):
        for task in self._diff_tasks.values():
            task.cancel()
        self._diff_tasks.clear()

    def _draft_changed(self, page: int, value: str):
        if self._actions_locked():
            return
        if not isinstance(value, str):
            return
        self._drafts[page] = value
        prior = self._diff_tasks.pop(page, None)
        if prior:
            prior.cancel()
        self._diff_tasks[page] = asyncio.create_task(self._update_diff_delayed(page))

    async def _update_diff_delayed(self, page: int):
        try:
            await asyncio.sleep(0.45)
            self._update_diff(page)
        except asyncio.CancelledError:
            pass
        finally:
            if self._diff_tasks.get(page) is asyncio.current_task():
                self._diff_tasks.pop(page, None)

    def _update_diff(self, page: int):
        widgets = self._diff_panels.get(page)
        if widgets is None:
            return
        label, panel = widgets
        original = self._originals.get(page, '')
        draft = self._drafts.get(page, original)
        changed = original != draft
        label.set_visibility(changed)
        panel.set_visibility(changed)
        if changed:
            panel.content = self._diff_markup(original, draft)

    def _remember_open(self,page, opened):
        if opened:
            self._open_page = page
        elif self._open_page == page:
            self._open_page = None

    def _reset(self,page,area):
        if self._actions_locked():
            return
        area.value=self._originals[page]
        self._drafts[page]=self._originals[page]
        self._update_diff(page)

    async def _edit_llm(self,page,area,regenerate):
        owner=self.owner
        if self._actions_locked() or not owner.write_access_allowed(): return
        if not await self.execution_lock.acquire(owner.username,'品質検査ナレーション編集',owner):
            ui.notify('ほかの処理が実行中です．',type='warning');return
        self.busy=True
        owner.cancellation_requested = False
        owner.set_processing(True)
        owner.current_task=asyncio.current_task()
        label = '再生成' if regenerate else '自動校正'
        self._edit_status.text = f'スライド #{page}：{label}中…'
        self._edit_bar.value = None  # 完了率不明のLLM処理は不定進捗
        self._edit_bar.set_visibility(True)
        owner.update_job_status('running', stage='validation-edit', message=self._edit_status.text, current_page=page)
        before = area.value
        try:
            client=await run.io_bound(make_client,owner.cfg['llm'])
            project=owner.paths.root
            if regenerate:
                response=await run.io_bound(run_with_statistics,project/'statistics.jsonl',page,
                    generate_single_explanation,client=client,cfg=owner.cfg['llm'],pdf=owner.pdf,
                    images=owner.images,out_dir=owner.paths.explanations_dir,page=page,
                    active_pages=owner.active_pages,mode=owner.mode_code,lang=owner.lang_code,persist=False)
            else:
                issues=[x for x in load(project).get('findings',[]) if x['page']==page]
                response=await run.io_bound(run_with_statistics,project/'statistics.jsonl',page,
                    correct,client,owner.cfg['llm'],page,area.value,issues)
            if not regeneration_valid(response):
                raise ValueError('生成された原稿に特殊トークンが含まれているか，内容が空です．')
            area.value=response
            self._drafts[page]=response
            self._update_diff(page)
            ui.notify('下書きを更新しました．「保存」までは原稿には反映されません．',type='positive')
        except Exception as exc:
            log(owner.paths.root,f'編集 #{page} ERROR {exc}')
            ui.notify(f'生成・校正に失敗しました：{exc}',type='negative')
        finally:
            self.busy=False
            try:
                self._edit_bar.value = 0
                self._edit_bar.set_visibility(False)
                self._edit_status.text = ''
            except Exception:
                LOGGER.exception('ナレーション編集の終了UI更新に失敗しました')
            try:
                owner._finalize_cancel_request()
            except Exception:
                LOGGER.exception('ナレーション編集の中断状態確定に失敗しました')
            finally:
                owner._complete_background_job()
            self._safe_render_results()

    def _save_page(self,page,area):
        owner=self.owner
        if self._actions_locked() or not owner.write_access_allowed():return
        path=owner.paths.explanation(page)
        if not path.exists():
            ui.notify('ナレーションファイルがありません．',type='warning');return
        current=path.read_text(encoding='utf-8')
        original=self._originals.get(page,current)
        if current!=original:
            ui.notify('別の処理で原稿が変更されています．保存せず検査し直してください．',type='warning');return
        candidate=area.value
        if not candidate.strip():
            ui.notify('空のナレーションは保存できません．',type='warning');return
        if current!=candidate:
            self.atomic_writer(path,candidate.rstrip()+'\n')
            owner.paths.cleanup_downstream(page,include_alignment=True)
        state=load(owner.paths.root)
        state['findings']=[f for f in state.get('findings',[]) if int(f['page'])!=page]
        save(owner.paths.root,state)
        self._drafts.pop(page,None)
        self._originals.pop(page,None)
        self._diff_panels.pop(page,None)
        self._open_page=None
        log(owner.paths.root,f'#{page} 保存・問題一覧から除外')
        self.render_results()
        ui.notify(f'スライド #{page} を保存しました．',type='positive')
