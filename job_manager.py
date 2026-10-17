"""ジョブ実行管理の独立基盤（第1段階）．

現段階では既存UI・ジョブ実行処理から呼び出さない．次の段階で
既存の実行ロックと中断処理を順次移行するための準備モジュール．
永続化やUI通知は本モジュールの責務に含めない．
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Event, Lock
from typing import Optional
from uuid import uuid4


class JobState(str, Enum):
    RUNNING = 'running'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    FAILED = 'failed'


@dataclass(frozen=True)
class JobSnapshot:
    """UI等へ渡す変更不能な実行状態．"""
    job_id: str
    username: str
    task_name: str
    state: JobState
    cancellation_requested: bool


@dataclass
class _JobRuntime:
    job_id: str
    username: str
    task_name: str
    cancellation: Event = field(default_factory=Event)


class JobManager:
    """同時に1ジョブだけ実行し，ID一致によって操作を保護する．

    非待機のtry_startは排他取得に失敗するとNoneを返す．
    finishは現在のジョブIDが一致しない場合，何も変更しない．
    履歴やディスク永続化は呼び出し側で扱う．
    """

    def __init__(self) -> None:
        self._guard = Lock()
        self._active: Optional[_JobRuntime] = None

    def try_start(self, username: str, task_name: str) -> Optional[JobSnapshot]:
        if not username or not task_name:
            raise ValueError('usernameとtask_nameは必須です')
        with self._guard:
            if self._active is not None:
                return None
            self._active = _JobRuntime(uuid4().hex, username, task_name)
            return self._snapshot(self._active)

    def current(self) -> Optional[JobSnapshot]:
        with self._guard:
            return self._snapshot(self._active) if self._active else None

    def is_running(self) -> bool:
        with self._guard:
            return self._active is not None

    def request_cancel(self, job_id: str) -> bool:
        with self._guard:
            if not self._active or self._active.job_id != job_id:
                return False
            self._active.cancellation.set()
            return True

    def cancellation_requested(self, job_id: str) -> bool:
        with self._guard:
            return bool(self._active and self._active.job_id == job_id
                        and self._active.cancellation.is_set())

    def finish(self, job_id: str, state: JobState) -> bool:
        """実行中ジョブを終端状態にする．所有権不一致や二重終了はFalse．"""
        if state not in (JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED):
            raise ValueError('finishには終了状態を指定してください')
        with self._guard:
            if self._active is None or self._active.job_id != job_id:
                return False
            self._active = None
            return True

    @staticmethod
    def _snapshot(runtime: _JobRuntime) -> JobSnapshot:
        return JobSnapshot(runtime.job_id, runtime.username, runtime.task_name,
                           JobState.RUNNING, runtime.cancellation.is_set())
