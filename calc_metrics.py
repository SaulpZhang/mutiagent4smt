#!/usr/bin/env python3
"""计算指定实验的 PASS@1, Precision, Recall, F1, 约束满足率, 时间统计"""

import sqlite3
from pathlib import Path


def calc(db_path, run_id):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT label, code_execution_result, all_satisfied, total_time_ms FROM experiments WHERE run_id=?",
        (run_id,)
    ).fetchall()
    total = len(rows)
    lm_row = conn.execute(
        "SELECT COUNT(*) FROM experiments WHERE run_id=? AND label_match=1", (run_id,)
    ).fetchone()
    lm = lm_row[0] if lm_row else 0
    conn.close()

    if not rows:
        return None
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

    sat_match = 0
    sat_total = 0
    conn = sqlite3.connect(db_path)
    for label, z3_out, all_sat, _ in conn.execute(
        "SELECT label, code_execution_result, all_satisfied, total_time_ms FROM experiments WHERE run_id=?", (run_id,)
    ).fetchall():
        if all_sat == 1 and label is not None and z3_out:
            sat_total += 1
            z3_sat = any(l.startswith("sat") for l in z3_out.strip().lower().split("""\n"""))
            if z3_sat == label:
                sat_match += 1
    conn.close()

    sat_match_rate = sat_match / sat_total * 100 if sat_total else 0

    pass1 = lm / total * 100 if total else 0
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    sat_rate = all_sat_count / total * 100 if total else 0
    avg_t = sum(times) / len(times) / 1000 if times else 0
    max_t = max(times) / 1000 if times else 0
    min_t = min(times) / 1000 if times else 0
    total_t = sum(times) / 1000 / 3600 if times else 0

    return {"total": total, "valid": valid, "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "pass1": pass1, "precision": precision, "recall": recall, "f1": f1,
            "sat_rate": sat_rate, "all_sat_count": all_sat_count,
            "avg_time": avg_t, "max_time": max_t, "min_time": min_t, "total_time": total_t,
            "sat_match_rate": sat_match_rate, "sat_match": sat_match, "sat_total": sat_total}


def fmt(r, rid):
    if r is None:
        return "  {:25s}  无数据".format(rid)
    return ("  {:25s}  PASS@1={:5.1f}%  Prec={:5.1f}%  Rec={:5.1f}%  F1={:5.1f}%  "
            "Sat={:5.1f}%  SatMatch={:3d}/{:3d}  avg={:5.0f}s  max={:5.0f}s  min={:5.0f}s  total={:.1f}h").format(
        rid, r["pass1"], r["precision"], r["recall"], r["f1"],
        r["sat_rate"], r["sat_match"], r["sat_total"], r["avg_time"], r["max_time"], r["min_time"], r["total_time"])


def main():
    experiments = [
        ("data/experiments.db", "exp_full_v2"),
        ("data/experiments.db", "exp_no_eval"),
        ("data/experiments.db", "exp_gen_only"),
        ("data/experiments.db", "full_v21"),
        ("data/experiments.db", "ablation_no_eval_v1"),
        ("data/experiments.db", "ablation_gen_only_v1"),
        ("data/experiments.db", "full_qwen"),
        ("data/experiments.db", "no_eval_qwen"),
        ("data/experiments.db", "gen_only_qwen"),
        ("remote_data/baseline/experiments.db", "qwen_full_v1"),
        ("remote_data/baseline/experiments.db", "qwen_full_v2"),
        ("remote_data/lora/qwen_lora_full_v1/data/experiments.db", "qwen_lora_full_v1"),
        ("remote_data/lora/qwen_lora_full_v2/data/experiments.db", "qwen_lora_full_v2"),
    ]

    print(f"{'Run ID':25s}  PASS@1      Precision   Recall      F1          Sat         SatMatch    avg_time    max_time    min_time    total")
    print("-" * 120)
    for db_path, run_id in experiments:
        if not Path(db_path).exists():
            print(f"  {run_id:25s}  DB不存在: {db_path}")
            continue
        r = calc(db_path, run_id)
        print(fmt(r, run_id))


if __name__ == "__main__":
    main()
