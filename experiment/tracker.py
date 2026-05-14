from __future__ import annotations

import json
import time
import contextvars
from datetime import datetime, timezone
from typing import Any

from core.schemas import ExperimentRecord, StageTiming

current_record: contextvars.ContextVar[ExperimentRecord] = (
    contextvars.ContextVar("experiment_current_record")
)


class MetricsTracker:
    """实验指标追踪器

    使用ContextVar在流水线执行过程中传递当前实验记录上下文，
    避免将tracker对象层层传递到每个函数签名。
    """

    def __init__(self) -> None:
        self._record: ExperimentRecord | None = None

    def start_new_record(
        self,
        instruct_id: str = "",
        account_id: str = "",
        instruction: str = "",
        account_data: dict | None = None,
        model_used: str = "",
        run_id: str = "",
    ) -> ExperimentRecord:
        """开始一个新的实验记录"""
        record = ExperimentRecord(
            instruct_id=instruct_id,
            account_id=account_id,
            instruction=instruction,
            account_data=account_data or {},
            model_used=model_used,
            run_id=run_id,
        )
        self._record = record
        current_record.set(record)
        return record

    def get_record(self) -> ExperimentRecord:
        """获取当前实验记录"""
        record = current_record.get(None)
        if record is None:
            record = self._record
        if record is None:
            record = self.start_new_record()
        return record

    def update(self, **fields: Any) -> None:
        """更新当前实验记录的字段"""
        record = self.get_record()
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)

    def start_stage(self, stage_name: str) -> StageContext:
        """开始记录一个阶段的耗时

        返回StageContext上下文管理器，在with块结束后自动记录耗时
        """
        return StageContext(self, stage_name)

    def get_stages_summary(self) -> dict[str, float]:
        """获取各阶段耗时摘要"""
        record = self.get_record()
        return {s.stage_name: s.duration_ms for s in record.stages}

    def compute_total_time(self) -> float:
        """计算总耗时（各阶段耗时之和）"""
        record = self.get_record()
        return sum(s.duration_ms for s in record.stages)


class StageContext:
    """阶段耗时上下文管理器"""

    def __init__(self, tracker: MetricsTracker, stage_name: str) -> None:
        self.tracker = tracker
        self.stage_name = stage_name
        self.start_time: float = 0.0

    async def __aenter__(self) -> "StageContext":
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: Any = None,
    ) -> None:
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        now_iso = datetime.now(timezone.utc).isoformat()
        timing = StageTiming(
            stage_name=self.stage_name,
            duration_ms=elapsed_ms,
            start_time=now_iso,
            end_time=now_iso,
        )
        record = self.tracker.get_record()
        record.stages.append(timing)


# 全局单例
tracker = MetricsTracker()
