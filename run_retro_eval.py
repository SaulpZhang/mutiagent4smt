"""从 source_run 获取约束列表，对 target_run 的生成代码跑 A3 评估并更新 DB"""

import asyncio
import json
import sqlite3
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from config import settings
from core.prompt_manager import PromptManager
from modules.agent_builder import AgentBuilder
from modules.evaluation_module import EvaluationModule, strip_smt_comments
from core.schemas import SMTLibCode, ConstraintsList, Constraint
from core.trace_logger import TraceLogger


lock = threading.Lock()


async def evaluate_case(eval_module, code: str, constraints_list: str,
                        run_id: str = "", instruct_id: str = "",
                        iteration: int = 0) -> dict:
    """对单个用例跑 A3 评估"""
    clean_code = strip_smt_comments(code)

    try:
        raw = json.loads(constraints_list) if isinstance(constraints_list, str) else constraints_list
    except (json.JSONDecodeError, TypeError):
        raw = {}

    if isinstance(raw, dict):
        items = raw.get("constraints", [])
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    constraints = ConstraintsList(constraints=[
        Constraint(id=c.get("id", ""), description=c.get("description", ""), category=c.get("category", ""))
        for c in items
    ])

    code_obj = SMTLibCode(code=clean_code)
    trace_logger = TraceLogger(run_id, f"agent3_retro_iter{iteration}", case_id=instruct_id)

    try:
        result = await eval_module.evaluate(code_obj, constraints, trace_logger=trace_logger, iteration=iteration)
        return {
            "all_satisfied": result.all_satisfied,
            "satisfied_count": result.satisfied_count,
            "total": len(result.items),
            "summary": result.summary[:500],
            "items": [item.model_dump() for item in result.items],
        }
    except Exception as e:
        trace_logger.add_message("error", str(e))
        trace_logger.flush()
        return {"all_satisfied": None, "error": str(e)}


def update_db(target_run: str, instruct_id: str, constraints_json: str, eval_data: dict):
    """更新 target_run 的约束列表和评估结果"""
    conn = sqlite3.connect(settings.db_path, timeout=30)
    try:
        all_sat = eval_data.get("all_satisfied")
        sat_count = eval_data.get("satisfied_count", 0)
        total_count = eval_data.get("total", 0)
        items = eval_data.get("items", [])
        summary = eval_data.get("summary", "")

        evaluation_result = json.dumps({
            "items": items,
            "all_satisfied": all_sat,
            "summary": summary,
        }, ensure_ascii=False)

        with lock:
            conn.execute("""
                UPDATE experiments
                SET constraints_list = ?,
                    constraint_text = ?,
                    evaluation_result = ?,
                    all_satisfied = ?,
                    satisfied_count = ?,
                    total_constraint_count = ?
                WHERE run_id = ? AND instruct_id = ?
            """, (
                constraints_json,
                json.dumps([{"id": c.get("id"), "description": c.get("description")}
                           for c in json.loads(constraints_json).get("constraints", [])], ensure_ascii=False),
                evaluation_result,
                all_sat,
                sat_count,
                total_count,
                target_run,
                instruct_id,
            ))
            conn.commit()
    finally:
        conn.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", required=True, help="有约束列表的实验 run_id")
    parser.add_argument("--target-run", required=True, help="需要补跑 A3 评估的实验 run_id")
    parser.add_argument("--workers", type=int, default=4, help="并行线程数")
    args = parser.parse_args()

    prompt_manager = PromptManager(scenario_name="valid_permission")
    agent_builder = AgentBuilder(scenario_name="valid_permission")
    eval_agent = agent_builder.build_eval_agent()
    eval_module = EvaluationModule(evaluation_agent=eval_agent, prompt_manager=prompt_manager)

    conn = sqlite3.connect(settings.db_path, timeout=30)

    # 加载 source_run 的约束列表
    print(f"加载 source_run={args.source_run} 的约束列表...")
    source_constraints = {}
    rows = conn.execute(
        "SELECT instruct_id, constraints_list FROM experiments WHERE run_id=? AND constraints_list IS NOT NULL",
        (args.source_run,)
    ).fetchall()
    for iid, cl in rows:
        source_constraints[iid] = cl
    print(f"  找到 {len(source_constraints)} 个约束列表")

    # 加载 target_run 的生成代码
    print(f"加载 target_run={args.target_run} 的生成代码...")
    target_rows = conn.execute(
        "SELECT rowid, instruct_id, generated_code FROM experiments WHERE run_id=? AND generated_code IS NOT NULL AND generated_code != ''",
        (args.target_run,)
    ).fetchall()
    print(f"  找到 {len(target_rows)} 个有代码的用例")

    conn.close()

    if not target_rows:
        print("没有需要评估的用例")
        return

    # 并发评估
    success = 0
    fail = 0
    total = len(target_rows)

    async def process_one(rowid, iid, code):
        nonlocal success, fail
        cl = source_constraints.get(iid)
        if not cl:
            print(f"  [{iid}] 跳过：无约束列表")
            return

        result = await evaluate_case(eval_module, code, cl, run_id=args.target_run, instruct_id=iid, iteration=0)
        update_db(args.target_run, iid, cl, result)

        if result.get("all_satisfied") is True:
            success += 1
        elif result.get("all_satisfied") is False:
            fail += 1

        print(f"  [{iid}] all_satisfied={result.get('all_satisfied')}  satisfied={result.get('satisfied_count', '?')}/{result.get('total', '?')}")

    sem = asyncio.Semaphore(args.workers)

    async def run_one(rowid, iid, code):
        async with sem:
            await process_one(rowid, iid, code)

    tasks = [asyncio.create_task(run_one(rid, iid, code)) for rid, iid, code in target_rows]
    for coro in asyncio.as_completed(tasks):
        await coro

    print(f"\n完成: {total} 例")
    print(f"  all_satisfied: {success}/{total} = {success/total*100:.1f}%")
    print(f"  not_satisfied: {fail}/{total}")


if __name__ == "__main__":
    asyncio.run(main())
