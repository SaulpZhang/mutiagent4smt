#!/usr/bin/env python3
"""计算实验指标：PASS@1, Precision, Recall, F1, 约束满足率, 时间统计

用法:
    python3 sft/train/calc_metrics.py --runid exp_full_v2
    python3 sft/train/calc_metrics.py --db remote_data/baseline/experiments.db --runid qwen_full_v1
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def calc(db_path: str, run_id: str):
    conn = sqlite3.connect(db_path)

    rows = conn.execute(
        "SELECT label, code_execution_result, all_satisfied, total_time_ms FROM experiments WHERE run_id=?",
        (run_id,)
    ).fetchall()

    if not rows:
        print(f"未找到 run_id={run_id} 的实验数据")
        conn.close()
        return

    total = len(rows)
    valid = 0
    tp = fp = tn = fn = 0
    all_sat_count = 0
    times = []

    for label, z3_out, all_sat, time_ms in rows:
        # 时间统计
        if time_ms and time_ms > 0:
            times.append(time_ms)

        # 约束满足率
        if all_sat == 1:
            all_sat_count += 1

        # PASS@1 / PRF1
        if label is not None and z3_out:
            valid += 1
            z3_sat = any(l.startswith("sat") for l in z3_out.strip().lower().split("\n"))
            if label == 1 and z3_sat:
                tp += 1
            elif label == 0 and z3_sat:
                fp += 1
            elif label == 0 and not z3_sat:
                tn += 1
            elif label == 1 and not z3_sat:
                fn += 1

    conn.close()

    # 计算指标
    pass1 = (tp + tn) / valid * 100 if valid > 0 else 0
    precision = tp / (tp + fp) * 100 if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    sat_rate = all_sat_count / total * 100 if total > 0 else 0

    # 时间统计
    avg_time = sum(times) / len(times) / 1000 if times else 0
    max_time = max(times) / 1000 if times else 0
    min_time = min(times) / 1000 if times else 0
    total_time = sum(times) / 1000 / 3600 if times else 0

    print(f"=== {run_id} ===")
    print(f"总用例:     {total}")
    print(f"有效(有label): {valid}")
    print()
    print(f"TP: {tp:4d}  FP: {fp:4d}  TN: {tn:4d}  FN: {fn:4d}")
    print()
    print(f"PASS@1:           {pass1:.1f}% ({tp+tn}/{valid})")
    print(f"Precision:        {precision:.1f}%")
    print(f"Recall:          {recall:.1f}%")
    print(f"F1:              {f1:.1f}%")
    print(f"约束满足率:      {sat_rate:.1f}% ({all_sat_count}/{total})")
    print()
    print(f"平均耗时/例:     {avg_time:.0f}s")
    print(f"最大耗时:        {max_time:.0f}s")
    print(f"最小耗时:        {min_time:.0f}s")
    print(f"总时长(126例):   ~{total_time:.1f}h")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runid", required=True, help="实验 run_id")
    parser.add_argument("--db", default="data/experiments.db", help="SQLite 数据库路径")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        sys.exit(1)

    calc(str(db_path), args.runid)


if __name__ == "__main__":
    main()
