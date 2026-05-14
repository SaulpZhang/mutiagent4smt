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
            conn.execute("PRAGMA journal_mode=WAL")
            for table_sql in ALL_TABLES:
                conn.execute(table_sql)
            conn.commit()
        finally:
            conn.close()

    def enable_wal(self) -> None:
        """启用WAL模式以支持并行写入"""
        conn = self._get_conn()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
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
                    constraints_list, constraint_text, generated_code, syntax_valid,
                    syntax_error_info, code_execution_result, evaluation_result,
                    all_satisfied, satisfied_count, total_constraint_count, label_match,
                    num_iterations, num_syntax_retries, label,
                    model_used, total_time_ms, total_attempts, first_success_at,
                    stages, status, error_message, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.run_id,
                    record.instruct_id,
                    record.account_id,
                    record.instruction,
                    json.dumps(record.account_data, ensure_ascii=False),
                    record.constraints_list,
                    record.constraint_text,
                    record.generated_code,
                    int(record.syntax_valid) if record.syntax_valid is not None else None,
                    record.syntax_error_info,
                    record.code_execution_result,
                    record.evaluation_result,
                    int(record.all_satisfied) if record.all_satisfied is not None else None,
                    record.satisfied_count,
                    record.total_constraint_count,
                    int(record.label_match) if record.label_match is not None else None,
                    record.num_iterations,
                    record.num_syntax_retries,
                    int(record.label) if record.label is not None else None,
                    record.model_used,
                    record.total_time_ms,
                    record.total_attempts,
                    record.first_success_at,
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

    def get_summary_stats(self, run_id: str | None = None) -> dict:
        """获取实验摘要统计，可指定 run_id 筛选某次实验"""
        conn = self._get_conn()
        try:
            where = "WHERE run_id = ?" if run_id else ""
            params = [run_id] if run_id else []
            cursor = conn.execute(
                f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count,
                    -- 约束满足率：所有成功用例中 satisfied_count / total_constraint_count
                    CASE
                        WHEN SUM(CASE WHEN status = 'success' THEN total_constraint_count ELSE 0 END) > 0
                        THEN 1.0 * SUM(CASE WHEN status = 'success' THEN satisfied_count ELSE 0 END)
                            / SUM(CASE WHEN status = 'success' THEN total_constraint_count ELSE 0 END)
                        ELSE NULL
                    END as constraint_satisfaction_rate,
                    -- 全部约束满足的用例数
                    SUM(CASE WHEN all_satisfied = 1 THEN 1 ELSE 0 END) as all_satisfied_count,
                    -- 标签匹配率：label_match=1 的占比（针对有label的数据）
                    CASE
                        WHEN SUM(CASE WHEN label_match IS NOT NULL THEN 1 ELSE 0 END) > 0
                        THEN 1.0 * SUM(CASE WHEN label_match = 1 THEN 1 ELSE 0 END)
                            / SUM(CASE WHEN label_match IS NOT NULL THEN 1 ELSE 0 END)
                        ELSE NULL
                    END as label_accuracy,
                    SUM(CASE WHEN label_match = 1 THEN 1 ELSE 0 END) as label_match_count,
                    SUM(CASE WHEN label_match IS NOT NULL THEN 1 ELSE 0 END) as label_total_count,
                    AVG(total_time_ms) as avg_time_ms,
                    AVG(num_iterations) as avg_iterations
                FROM experiments {where}
                """,
                params,
            )
            return dict(cursor.fetchone())
        finally:
            conn.close()

    def save_run_config(self, run_id: str, config: dict) -> None:
        """保存本轮实验的运行参数"""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiment_runs
                    (run_id, prompt_type, model_used, parallel, attempts,
                     max_iterations, max_syntax_retries, total_cases)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    config.get("prompt_type", "default"),
                    config.get("model_used", ""),
                    config.get("parallel", 1),
                    config.get("attempts", 1),
                    config.get("max_iterations", 10),
                    config.get("max_syntax_retries", 5),
                    config.get("total_cases", 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_run_config(self, run_id: str) -> dict | None:
        """查询实验运行参数"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT * FROM experiment_runs WHERE run_id = ?", (run_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_pass_at_k_stats(self, run_id: str, ks: list[int] | None = None) -> dict:
        """计算PASS@K指标

        通过 first_success_at 字段聚合：
          PASS@K = first_success_at 在 1..K 范围内的用例比例。
        """
        if ks is None:
            ks = [1, 3, 5]

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT first_success_at, total_attempts, all_satisfied "
                "FROM experiments WHERE run_id = ?",
                (run_id,),
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        total_cases = len(rows)
        result = {"total_cases": total_cases}

        for k in ks:
            count = sum(1 for r in rows if r["first_success_at"] is not None and r["first_success_at"] <= k)
            result[f"pass_at_{k}"] = round(count / total_cases, 4) if total_cases else 0.0
            result[f"pass_at_{k}_count"] = count

        # 约束满足率
        cs_count = sum(1 for r in rows if r["all_satisfied"] == 1)
        result["constraint_pass_rate"] = round(cs_count / total_cases, 4) if total_cases else 0.0
        result["constraint_pass_count"] = cs_count

        return result
