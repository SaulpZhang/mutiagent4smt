#!/usr/bin/env python3
"""清除指定 run_id 的实验结果、trace 和数据库记录

用法:
    python clean_run.py run_20260516_172206
    python clean_run.py run_20260516_172206 --yes    # 跳过确认
"""

from __future__ import annotations

import argparse
import sqlite3
import shutil
from pathlib import Path

from config import settings


def clean_run(run_id: str, dry_run: bool = False) -> None:
    """清除指定 run_id 的所有数据"""

    # 1. results 目录
    results_dir = Path(settings.results_dir) / run_id
    if results_dir.exists():
        size = sum(f.stat().st_size for f in results_dir.rglob("*") if f.is_file())
        action = f"[{'模拟' if dry_run else '删除'}] results: {results_dir} ({size / 1024:.0f} KB)"
        print(action)
        if not dry_run:
            shutil.rmtree(results_dir)
    else:
        print(f"[跳过] results: {results_dir} (不存在)")

    # 2. traces 目录
    traces_dir = Path(settings.data_dir) / "../data/traces" / run_id
    traces_dir = traces_dir.resolve()
    if traces_dir.exists():
        size = sum(f.stat().st_size for f in traces_dir.rglob("*") if f.is_file())
        action = f"[{'模拟' if dry_run else '删除'}] traces: {traces_dir} ({size / 1024:.0f} KB)"
        print(action)
        if not dry_run:
            shutil.rmtree(traces_dir)
    else:
        print(f"[跳过] traces: {traces_dir} (不存在)")

    # 3. 数据库记录
    db_path = Path(settings.db_path)
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute("SELECT COUNT(*) FROM experiments WHERE run_id = ?", (run_id,))
            exp_count = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM experiment_runs WHERE run_id = ?", (run_id,))
            run_count = cur.fetchone()[0]

            if exp_count or run_count:
                action = f"[{'模拟' if dry_run else '删除'}] 数据库: {exp_count} 条实验记录, {run_count} 条运行配置"
                print(action)
                if not dry_run:
                    conn.execute("DELETE FROM experiments WHERE run_id = ?", (run_id,))
                    conn.execute("DELETE FROM experiment_runs WHERE run_id = ?", (run_id,))
                    conn.commit()
            else:
                print(f"[跳过] 数据库: run_id '{run_id}' 无匹配记录")
        finally:
            conn.close()
    else:
        print(f"[跳过] 数据库: {db_path} (不存在)")


def main() -> None:
    parser = argparse.ArgumentParser(description="清除指定 run_id 的实验数据")
    parser.add_argument("run_id", help="要清除的实验 run_id")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认直接执行")
    args = parser.parse_args()

    print(f"即将清除 run_id: {args.run_id}")
    print()

    # 先模拟运行一次，展示要删除的内容
    clean_run(args.run_id, dry_run=True)

    if not args.yes:
        print()
        confirm = input("确认执行以上删除操作? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("已取消")
            return

    print()
    clean_run(args.run_id, dry_run=False)
    print()
    print("完成")


if __name__ == "__main__":
    main()
