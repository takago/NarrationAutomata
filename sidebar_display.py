"""サイドバーの表示対象・更新キーを決める，UIに依存しないヘルパー．"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

def select_refinement_candidate(candidates: Sequence[tuple], *, pipeline_running: bool) -> tuple | None:
    """生きたrefineジョブを優先し，通常ジョブ実行中は古いrunning履歴を隠す．"""
    if not candidates:
        return None
    if pipeline_running:
        candidates = [candidate for candidate in candidates if candidate[0]]
    return max(candidates) if candidates else None

def video_render_key(project: Path, signature: Any) -> tuple[str, Any]:
    """同名ビデオが存在する別プロジェクトを識別する．"""
    return (str(project.resolve()), signature)
