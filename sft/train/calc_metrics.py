#!/usr/bin/env python3
"""计算指定实验的 PASS@1, Precision, Recall, F1, 约束满足率, 时间统计"""

import sqlite3
from pathlib import Path


def calc(db_path: str, run_id: str):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT label, code_execution_result, all_satisfied, total_time_ms FROM experiments WHERE run_id=?",
        (run_id,)
    ).fetchall()
    conn.close()

    if not rows:
        print(f"  {run_id}: 无数据")
        return

    total = len(rows)
    valid = tp = fp = tn = fn = all_sat_count = 0
    times = []

    for label, z3_out, all_sat, time_ms in rows:
        if time_ms and time_ms > 0:
            times.append(time_ms)
        if all_sat == 1:
            all_sat_count += 1
        if label is not None and z3_out:
            valid += 1
            z3_sat = any(l.startswith("sat") for l in z3_out.strip().lower().split("\n"))
            if label == 1 and z3_sat:    tp += 1
            elif label == 0 and z3_sat:  fp += 1
            elif label == 0 and not z3_sat: tn += 1
            elif label == 1 and not z3_sat: fn += 1

    pass1 = (tp + tn) / valid * 100 if valid else 0
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    sat_rate = all_sat_count / total * 100 if total else 0
    avg_t = sum(times) / len(times) / 1000 if times else 0
    max_t = max(times) / 1000 if times else 0
    min_t = min(times) / 1000 if times else 0
    total_t = sum(times) / 1000 / 3600 if times else 0

    print(f"  {run_id:25s}  PASS@1={pass1:5.1f}%  Prec={precision:5.1f}%  Rec={recall:5.1f}%  F1={f1:5.1f}%  "
          f"Sat={sat_rate:5.1f}%  avg={avg_t:5.0f}s  max={max_t:5.0f}s  min={min_t:5.0f}s  total={total_t:.1f}h")


def main():
    experiments = [
        ("data/experiments.db", "exp_full_v2"),
        ("data/experiments.db", "exp_no_eval"),
        ("data/experiments.db", "exp_gen_only"),
        ("data/experiments.db", "full_v1"),
        ("data/experiments.db", "full_v2"),
        ("data/experiments.db", "full_v3"),
        ("data/experiments.db", "a3_v1_full"),
        ("data/experiments.db", "a3_v3_full"),
        ("data/experiments.db", "a3_v4_full"),
        ("data/experiments.db", "full_v21"),
        ("data/experiments.db", "full_v22"),
        ("data/experiments.db", "full_qwen"),
        ("data/experiments.db", "no_eval_qwen"),
        ("data/experiments.db", "gen_only_qwen"),
        ("data/experiments.db", "ablation_no_eval_v1"),
        ("data/experiments.db", "ablation_gen_only_v1"),
        ("remote_data/baseline/experiments.db", "qwen_full_v1"),
        ("remote_data/baseline/experiments.db", "qwen_full_v2"),
        ("remote_data/lora/qwen_lora_full_v1/data/experiments.db", "qwen_lora_full_v1"),
        ("remote_data/lora/qwen_lora_full_v2/data/experiments.db", "qwen_lora_full_v2"),
    ]

    print(f"{'Run ID':25s}  PASS@1      Precision   Recall      F1          Sat         avg_time    max_time    min_time    total")
    print("-" * 130)
    for db_path, run_id in experiments:
        if not Path(db_path).exists():
            print(f"  {run_id:25s}  DB不存在: {db_path}")
            continue
        calc(db_path, run_id)


if __name__ == "__main__":
    main()
