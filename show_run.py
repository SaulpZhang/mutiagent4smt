#!/usr/bin/env python3
"""查看实验数据：按 run_id 汇总或查看某次运行的详情及 PASS@1"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_runs(db_path: str) -> None:
    """列出所有 run_id 及其摘要"""
    conn = get_conn(db_path)
    try:
        rows = conn.execute("""
            SELECT
                run_id,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                SUM(CASE WHEN all_satisfied = 1 THEN 1 ELSE 0 END) as all_ok,
                SUM(CASE WHEN label_match = 1 THEN 1 ELSE 0 END) as label_ok,
                SUM(CASE WHEN label_match IS NOT NULL THEN 1 ELSE 0 END) as label_total,
                ROUND(AVG(total_time_ms)) as avg_ms,
                ROUND(AVG(num_iterations), 1) as avg_iter
            FROM experiments
            GROUP BY run_id
            ORDER BY run_id
        """).fetchall()

        if not rows:
            print("数据库中没有实验记录。")
            return

        print(f"{'Run ID':<15} {'总数':>5} {'成功':>5} {'全满足':>6} {'标签匹配':>8} {'平均耗时':>8} {'平均迭代':>8}")
        print("-" * 65)
        for r in rows:
            label_str = f"{r['label_ok']}/{r['label_total']}" if r['label_total'] else "-"
            print(f"{r['run_id']:<15} {r['total']:>5} {r['success']:>5} {r['all_ok']:>6} {label_str:>8} {r['avg_ms']:>8}ms {r['avg_iter']:>8}")
    finally:
        conn.close()


def show_run(db_path: str, run_id: str) -> None:
    """显示指定 run_id 的详细结果和 PASS@1"""
    conn = get_conn(db_path)
    try:
        rows = conn.execute("""
            SELECT instruct_id, status, all_satisfied, label_match,
                   total_constraint_count, satisfied_count,
                   num_iterations, total_time_ms, first_success_at
            FROM experiments
            WHERE run_id = ?
            ORDER BY instruct_id
        """, (run_id,)).fetchall()

        if not rows:
            print(f"未找到 run_id = '{run_id}' 的记录")
            return

        total = len(rows)
        success = sum(1 for r in rows if r["status"] == "success")
        all_satisfied = sum(1 for r in rows if r["all_satisfied"] == 1)
        label_ok = sum(1 for r in rows if r["label_match"] == 1)
        label_total = sum(1 for r in rows if r["label_match"] is not None)
        first_try_ok = sum(1 for r in rows if r["first_success_at"] is not None and r["first_success_at"] == 1)

        print(f"Run ID: {run_id}")
        print(f"{'=' * 60}")
        print(f"{'用例':<25} {'状态':>6} {'全满足':>6} {'标签':>6} {'迭代':>5} {'耗时':>8}")
        print("-" * 60)
        for r in rows:
            label_str = f"{'✓' if r['label_match'] else '✗'}" if r['label_match'] is not None else "-"
            sat_str = "✓" if r["all_satisfied"] else "~"
            print(f"{r['instruct_id']:<25} {r['status']:>6} {sat_str:>6} {label_str:>6} {r['num_iterations']:>5} {r['total_time_ms']:>7.0f}ms")
        print("-" * 60)
        print(f"总计: {total}  成功: {success}  全满足: {all_satisfied}")
        if label_total:
            print(f"标签匹配: {label_ok}/{label_total} ({label_ok/label_total*100:.1f}%)")
        print(f"\nPASS@1: {first_try_ok}/{total} ({first_try_ok/total*100:.1f}%)")

        # 约束满足率
        cs = conn.execute("""
            SELECT
                SUM(satisfied_count) as num, SUM(total_constraint_count) as den
            FROM experiments WHERE run_id = ? AND status = 'success'
        """, (run_id,)).fetchone()
        if cs and cs["den"] and cs["den"] > 0:
            print(f"约束满足率: {cs['num']}/{cs['den']} ({cs['num']/cs['den']*100:.1f}%)")
    finally:
        conn.close()


def main() -> None:
    from config import settings
    db_path = settings.db_path

    parser = argparse.ArgumentParser(description="查看实验数据")
    parser.add_argument("--run_id", nargs="?", default=None, help="指定 run_id 查看详情（缺省则列出所有 run）")
    args = parser.parse_args()

    if args.run_id:
        show_run(db_path, args.run_id)
    else:
        list_runs(db_path)


if __name__ == "__main__":
    main()
