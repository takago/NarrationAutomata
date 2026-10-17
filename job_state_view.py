"""実行状態と保存状態からUI向けの読み取り専用情報を組み立てる．

ここではファイルの読み書き，ジョブの開始・終了，UI操作を一切行わない．
保存済みの running は実行の証拠ではないため，実行管理側を正とする．
"""
from dataclasses import dataclass

from job_manager import JobState
from typing import Any, Mapping


@dataclass(frozen=True)
class JobDisplaySnapshot:
    globally_busy: bool
    owner_name: str
    owner_is_self: bool
    job_id: str | None
    status: dict[str, Any]
    own_status: dict[str, Any]


def resolve_job_display(*, username: str, active_job: Any,
                        owner_status: Mapping[str, Any] | None,
                        own_status: Mapping[str, Any] | None,
                        task_name: str | None = None) -> JobDisplaySnapshot:
    """状態ファイルに running が残っても，実行中の表示は管理側だけで判断する．

    active_job は JobManager.current() の変更不能な JobSnapshot，または None．
    status のコピーを返し，呼び出し元のJSONデータを変更しない．
    """
    own = dict(own_status or {})
    if active_job is None:
        shown = dict(own)
        if shown.get('state') == 'running':
            shown.update(state='failed', message='実行中状態を確認できません（サーバ再起動等の可能性があります）')
        return JobDisplaySnapshot(False, '', False, None, shown, own)
    owner_name = active_job.username
    shown = dict(owner_status or {})
    shown['stage'] = shown.get('stage') or task_name or active_job.task_name or '処理中'
    return JobDisplaySnapshot(True, owner_name, owner_name == username,
                              active_job.job_id, shown, own)


def resolve_terminal_state(*, task_name: str | None, cancel_requested: bool,
                           manager_cancel_requested: bool,
                           persisted_state: str | None) -> JobState:
    """リファイナーは通常パイプラインの古い保存状態を引き継がない．"""
    if cancel_requested or manager_cancel_requested:
        return JobState.CANCELLED
    # 個別生成・通常パイプラインのみ共通のユーザー別ジョブ状態を保存する．
    if (task_name or '').startswith(('パイプライン (', 'スライド ')):
        if persisted_state == 'cancelled':
            return JobState.CANCELLED
        if persisted_state == 'failed':
            return JobState.FAILED
    return JobState.COMPLETED
