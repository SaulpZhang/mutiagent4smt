#!/usr/bin/env python3
"""从 experiments.db 读取指定 run_id 的实验数据，计算 PASS@1 等指标。

用法:
    python statistic.py                         # 列出所有可用 run_id
    python statistic.py --runid run_xxx          # 查看指定 run 的统计
    python statistic.py --runid run_xxx --detail # 显示每个用例详情
    python statistic.py --runid run_xxx --exclude-anomaly  # 排除已知标签异常用例
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "experiments.db"

# 已知标签异常的用例（Z3=unsat 但 label=True）
KNOWN_ANOMALIES = {96, 117, 121, 123, 125}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def list_run_ids() -> list[str]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT run_id, created_at FROM experiment_runs ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_by_run_id(run_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE run_id = ? ORDER BY instruct_id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def extract_case_num(instruct_id: str) -> int:
    """从 instruct_1_50 提取 50"""
    import re
    m = re.search(r"_(\d+)$", instruct_id)
    return int(m.group(1)) if m else 0


def compute_stats(rows: list[dict], exclude_anomaly: bool = False) -> dict:
    total = len(rows)
    if total == 0:
        return {"total": 0}

    # filter anomalies if requested
    filtered = rows
    if exclude_anomaly:
        filtered = [r for r in rows if extract_case_num(r["instruct_id"]) not in KNOWN_ANOMALIES]

    total_f = len(filtered)

    # PASS@1 via first_success_at
    pass1_count = sum(
        1 for r in filtered
        if r["first_success_at"] is not None and r["first_success_at"] <= 1
    )
    # general label_match
    label_match_count = sum(1 for r in filtered if r["label_match"] == 1)
    label_total = sum(1 for r in filtered if r["label_match"] is not None)

    # all_satisfied
    all_satisfied_count = sum(1 for r in filtered if r["all_satisfied"] == 1)

    # status breakdown
    success_count = sum(1 for r in filtered if r["status"] == "success")
    error_count = sum(1 for r in filtered if r["status"] == "error")

    # extract instruct_ids where label_match=0
    mismatches = []
    for r in filtered:
        lm = r.get("label_match")
        if lm is not None and lm == 0:
            cn = extract_case_num(r["instruct_id"])
            mismatches.append({
                "instruct_id": r["instruct_id"],
                "case_num": cn,
                "is_anomaly": cn in KNOWN_ANOMALIES,
            })

    return {
        "total": total_f,
        "excluded_anomalies": total - total_f if exclude_anomaly else 0,
        "success": success_count,
        "error": error_count,
        "pass_at_1": round(pass1_count / total_f, 4) if total_f else 0.0,
        "pass_at_1_count": pass1_count,
        "label_match_rate": round(label_match_count / label_total, 4) if label_total else 0.0,
        "label_match_count": label_match_count,
        "label_total": label_total,
        "all_satisfied": all_satisfied_count,
        "mismatches": mismatches,
    }


def print_stats(run_id: str, stats: dict, detail: bool = False) -> None:
    print(f"{'=' * 60}")
    print(f"  Run ID: {run_id}")
    print(f"{'=' * 60}")

    if stats["total"] == 0:
        print("  无数据")
        return

    print(f"  总用例:       {stats['total']}")
    if stats["excluded_anomalies"]:
        print(f"  排除异常:     {stats['excluded_anomalies']} 个 (cases {sorted(KNOWN_ANOMALIES)})")
    print(f"  成功:         {stats['success']}")
    print(f"  错误:         {stats['error']}")
    print(f"  {'─' * 47}")
    print(f"  全部约束满足: {stats['all_satisfied']}")
    print(f"  {'─' * 47}")
    print(f"  PASS@1:       {stats['pass_at_1']:.2%} ({stats['pass_at_1_count']}/{stats['total']})")
    print(f"  Label匹配:    {stats['label_match_rate']:.2%} ({stats['label_match_count']}/{stats['label_total']})")

    if stats["mismatches"]:
        print(f"  {'─' * 47}")
        print(f"  Label不匹配 ({len(stats['mismatches'])} 个):")
        for m in stats["mismatches"]:
            flag = " ⚠ 已知异常" if m["is_anomaly"] else ""
            print(f"    {m['instruct_id']}{flag}")
    print(f"{'=' * 60}")

    if detail:
        print(f"\n  {'=' * 60}")
        print(f"  各用例详情")
        print(f"  {'=' * 60}")
        rows = query_by_run_id(run_id)
        for r in rows:
            cn = extract_case_num(r["instruct_id"])
            status = "✓" if r["label_match"] == 1 else ("✗" if r["label_match"] == 0 else "?")
            anomaly = " (异常)" if cn in KNOWN_ANOMALIES else ""
            sat = "sat" if r.get("code_execution_result") and r["code_execution_result"].strip().lower() == "sat" else "unsat"
            print(f"  [{status}] {r['instruct_id']}  Z3={sat}  label_match={r['label_match']}{anomaly}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CodeV 实验结果统计")
    parser.add_argument("--runid", type=str, default=None, help="实验 run_id")
    parser.add_argument("--detail", action="store_true", help="显示每个用例详情")
    parser.add_argument("--exclude-anomaly", action="store_true", help="排除已知标签异常用例")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"[!] 数据库不存在: {DB_PATH}")
        return

    if args.runid:
        rows = query_by_run_id(args.runid)
        if not rows:
            print(f"[!] 未找到 run_id='{args.runid}' 的数据")
            return
        stats = compute_stats(rows, exclude_anomaly=args.exclude_anomaly)
        print_stats(args.runid, stats, detail=args.detail)
    else:
        runs = list_run_ids()
        if not runs:
            print("数据库中没有实验记录")
            return
        print(f"{'=' * 60}")
        print(f"  可用实验 (共 {len(runs)} 次)")
        print(f"{'=' * 60}")
        for r in runs:
            print(f"  {r['run_id']:30s}  {r.get('created_at', '')}")
        print(f"\n  使用 python statistic.py --runid <run_id> 查看详情")


if __name__ == "__main__":
    main()
