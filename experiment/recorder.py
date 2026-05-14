from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.exceptions import ExperimentError
from core.schemas import ExperimentRecord
from experiment.models import ALL_TABLES


class ExperimentRecorder:
    """实验记录器：将实验数据持久化到SQLite"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """初始化数据库表"""
        conn = self._get_conn()
        try:
            for table_sql in ALL_TABLES:
                conn.execute(table_sql)
            conn.commit()
        finally:
            conn.close()

    def save_experiment(self, record: ExperimentRecord) -> str:
        """保存一条实验记录

        Returns:
            记录ID
        """
        stages_json = json.dumps(
            [s.model_dump() for s in record.stages],
            ensure_ascii=False,
        )

        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiments (
                    id, run_id, instruct_id, account_id, instruction, account_data,
                    constraints_list, generated_code, syntax_valid,
                    syntax_error_info, code_execution_result, evaluation_result,
                    all_satisfied, num_iterations, num_syntax_retries, label,
                    model_used, total_time_ms, stages, status, error_message, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.run_id,
                    record.instruct_id,
                    record.account_id,
                    record.instruction,
                    json.dumps(record.account_data, ensure_ascii=False),
                    record.constraints_list,
                    record.generated_code,
                    int(record.syntax_valid) if record.syntax_valid is not None else None,
                    record.syntax_error_info,
                    record.code_execution_result,
                    record.evaluation_result,
                    int(record.all_satisfied) if record.all_satisfied is not None else None,
                    record.num_iterations,
                    record.num_syntax_retries,
                    int(record.label) if record.label is not None else None,
                    record.model_used,
                    record.total_time_ms,
                    stages_json,
                    record.status,
                    record.error_message,
                    record.timestamp,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            raise ExperimentError(f"保存实验记录失败: {e}") from e
        finally:
            conn.close()

        return record.id

    def query_experiments(
        self,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict]:
        """查询实验记录"""
        conn = self._get_conn()
        try:
            where = "WHERE status = ?" if status else ""
            params = [status] if status else []
            cursor = conn.execute(
                f"SELECT * FROM experiments {where} ORDER BY timestamp DESC LIMIT ?",
                [*params, limit],
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_summary_stats(self) -> dict:
        """获取实验摘要统计"""
        conn = self._get_conn()
        try:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN all_satisfied = 1 THEN 1 ELSE 0 END) as aligned_count,
                    AVG(total_time_ms) as avg_time_ms,
                    AVG(num_iterations) as avg_iterations
                FROM experiments
            """)
            return dict(cursor.fetchone())
        finally:
            conn.close()
