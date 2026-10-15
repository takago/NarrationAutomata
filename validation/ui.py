"""User-driven quality checks and a single, save-gated narration editor."""
from __future__ import annotations

import asyncio
import difflib
import html
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from nicegui import ui, run
from statistics_store import run_with_statistics
from slide_lecture import make_client, generate_single_explanation
from .core import rule_check, individual_check, overall_check, synthesis_check, correct, regeneration_valid
from .store import STAGES, digest, load, log, save

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


class ValidationView:
    def __init__(self, controller: Any, lock: Any, atomic_writer: Any):
        self.owner = controller
        self.execution_lock = lock
        self.atomic_writer = atomic_writer
        self.busy = False
        self.controls = None
        self.progress = None
        self.bar = None
        self.results = None
        self.selection = {s: s == 'rules' for s in STAGES}
        self._project_key = None
        self._drafts: dict[int, str] = {}
        self._originals: dict[int, str] = {}
        self._open_page = None
        self._progress_value = 0.0
        self._start_button = None
        self._edit_status = None
        self._edit_bar = None
        self._diff_panels: dict[int, tuple[Any, Any]] = {}
        self._diff_tasks: dict[int, asyncio.Task] = {}

    def build(self):
        ui.label('🔎 ナレーション品質検査').classes('text-h5')
        ui.label('検査は原稿を変更しません．指摘を確認して編集し，保存した場合だけ原稿に反映します．').classes('text-caption text-slate-400')
        ui.add_css('''
            .validation-narration-editor .q-field__control { min-height: 300px; height: 300px; }
            .validation-narration-editor textarea { line-height: 1.55; }
            .validation-narration-diff > div { height: 300px; max-height: 300px; overflow-y: auto; line-height: 1.55; }
        ''')
        self.controls = ui.column().classes('w-full gap-3')
        self.progress = ui.label('検査待機中').classes('text-sm text-slate-400')
        self.bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
        self._edit_status = ui.label('').classes('text-sm text-slate-400')
        self._edit_bar = ui.linear_progress(value=0, show_value=False).classes('w-full')
        self._edit_bar.set_visibility(False)
        self.results = ui.column().classes('w-full gap-2')
        self.refresh()

    def refresh(self):
        project = self.owner.paths.root if self.owner.paths else None
        key = str(project) if project else None
        if key != self._project_key:
            self._project_key = key
            self._drafts.clear()
            self._originals.clear()
            self._cancel_diff_tasks()
            self._open_page = None
        if self.controls is None:
            return
        self.controls.clear()
        with self.controls:
            if project is None:
                ui.label('プロジェクトを選択してください．')
                self.results.clear()
                return
            for stage in STAGES:
                with ui.row().classes('w-full items-center gap-3'):
                    ui.checkbox(STAGE_NAMES[stage], value=self.selection[stage],
                                on_change=lambda e, s=stage: self.selection.__setitem__(s, bool(e.value)))
                    ui.label(STAGE_DESCRIPTIONS[stage]).classes('text-xs text-slate-400')
            self._start_button = ui.button('検査を開始', icon='play_arrow', on_click=self.start).props('outline').bind_enabled_from(self, 'busy', backward=lambda value: not value)
            ui.label('実行時に前回の検査結果をすべて破棄します．検査中は閲覧のみ可能です．').classes('text-caption text-slate-400')
        self.render_results()

    def _pages(self):
        if not self.owner.paths:
            return []
        return sorted(int(p.stem) for p in self.owner.paths.explanations_dir.glob('[0-9]*.txt') if p.stem.isdigit())

    def _status(self, text, *, page=None, index=None, total=None, progress=None, stage='validation'):
        self.progress.text = text
        if progress is not None:
            self._progress_value = min(1.0, max(0.0, progress))
            self.bar.value = self._progress_value
        self.owner.update_job_status('running', stage=stage, message=text,
                                     current_page=page, current_index=index,
                                     total_count=total, progress=self._progress_value)

    def start(self):
        if self.busy or self.owner.processing:
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
        self.busy = True  # タスクの起動を待たずにボタンを無効化する
        if self._start_button is not None:
            self._start_button.disable()
        asyncio.create_task(self._worker(stages))

    async def _worker(self, stages):
        owner = self.owner
        if not await self.execution_lock.acquire(owner.username, 'ナレーション品質検査', owner):
            self.busy = False
            if self._start_button is not None:
                self._start_button.enable()
            ui.notify('ほかのユーザの処理が実行中です．', type='warning')
            return
        self.busy = True
        owner.set_processing(True)
        owner.current_task = asyncio.current_task()
        project = owner.paths.root
        pages = self._pages()
        self._drafts.clear()
        self._originals.clear()
        self._cancel_diff_tasks()
        self._open_page = None
        state = {'findings': [], 'stages': {}, 'completed': False}
        save(project, state)
        self.render_results()
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
                self.render_results()

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
                                owner.paths.page_image(page), rule_check(text, page))
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
                            issues, summary = await run.io_bound(
                                run_with_statistics, project/'statistics.jsonl', None,
                                overall_check, client, owner.cfg['llm'], texts)
                            record(issues, stage)
                            if summary:
                                summaries.append((part[0], part[-1], summary))
                        except Exception as exc:
                            log(project, f'全体検査 {part[0]}-{part[-1]} ERROR {exc}')
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
            self.progress.text = message
            owner.update_job_status('cancelled' if owner.cancellation_requested else 'completed',
                                    stage='validation',message=message,
                                    progress=None if owner.cancellation_requested else 1.0)
            log(project, message)
        except asyncio.CancelledError:
            self.progress.text = '検査を中断しました（途中結果）．'
            owner.update_job_status('cancelled', stage='validation', message=self.progress.text)
        except Exception as exc:
            self.progress.text = f'品質検査エラー：{exc}'
            owner.update_job_status('failed', stage='validation', message=self.progress.text)
            log(project, f'ERROR {type(exc).__name__}: {exc}')
            ui.notify(self.progress.text, type='negative')
        finally:
            self.busy = False
            if self._start_button is not None:
                self._start_button.enable()
            owner._finalize_cancel_request()
            owner._complete_background_job()
            self.render_results()

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
        with self.results:
            ui.label(f'検出された問題：残り {len(grouped)} スライド').classes('text-subtitle1 font-medium')
            if not grouped:
                ui.label('検査結果はありません．').classes('text-slate-400')
            for page, issues in grouped.items():
                with ui.expansion(group=f'validation-{id(self)}', value=page == self._open_page).classes('w-full border rounded') as panel:
                    with panel.add_slot('header'):
                        with ui.column().classes('gap-1'):
                            ui.label(f'スライド #{page} ・ {len(issues)}件の指摘').classes('font-semibold')
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
                                if self.busy:
                                    area.props('readonly')
                            with ui.column().classes('flex-1 min-w-[320px] gap-2'):
                                diff_label = ui.label('検査時点の原稿との差分（赤：削除，緑：追加）').classes('text-xs text-slate-400')
                                diff_panel = ui.html('').classes('w-full text-sm validation-narration-diff')
                                self._diff_panels[page] = (diff_label, diff_panel)
                                self._update_diff(page)
                        with ui.row().classes('w-full justify-end gap-2 flex-wrap'):
                            for title, cb, icon in (
                                ('再生成',lambda p=page,a=area:self._edit_llm(p,a,True),'refresh'),
                                ('自動校正',lambda p=page,a=area:self._edit_llm(p,a,False),'auto_fix_high'),
                                ('元に戻す',lambda p=page,a=area:self._reset(p,a),'undo'),
                                ('保存',lambda p=page,a=area:self._save_page(p,a),'save')):
                                ui.button(title, icon=icon, on_click=cb).props('dense outline' if title!='保存' else 'dense color=primary').classes('min-w-[112px]').bind_enabled_from(self,'busy',backward=lambda busy:not busy)
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
        area.value=self._originals[page]
        self._drafts[page]=self._originals[page]
        self._update_diff(page)

    async def _edit_llm(self,page,area,regenerate):
        owner=self.owner
        if self.busy or owner.processing or not owner.write_access_allowed(): return
        if not await self.execution_lock.acquire(owner.username,'品質検査ナレーション編集',owner):
            ui.notify('ほかの処理が実行中です．',type='warning');return
        self.busy=True
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
            self._edit_bar.value = 0
            self._edit_bar.set_visibility(False)
            self._edit_status.text = ''
            owner._finalize_cancel_request()
            owner._complete_background_job()
            self.render_results()

    def _save_page(self,page,area):
        owner=self.owner
        if self.busy or owner.processing or not owner.write_access_allowed():return
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
