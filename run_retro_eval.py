"""对已有实验的生成代码补跑 A3 评估
"""
import asyncio
import json
import sqlite3
import time

from config import settings
from core.prompt_manager import PromptManager
from modules.agent_builder import AgentBuilder
from modules.evaluation_module import EvaluationModule, strip_smt_comments
from core.schemas import SMTLibCode, ConstraintsList, Constraint


async def evaluate_case(eval_module, code: str, constraints_list: str) -> dict:
    """对单个用例跑 A3 评估，返回 all_satisfied"""
    clean_code = strip_smt_comments(code)

    # 解析约束列表
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

    try:
        result = await eval_module.evaluate(code_obj, constraints)
        return {
            "all_satisfied": result.all_satisfied,
            "satisfied_count": result.satisfied_count,
            "total": len(result.items),
            "summary": result.summary[:200],
        }
    except Exception as e:
        return {"all_satisfied": None, "error": str(e)}


async def main():
    import sys
    target_runs = sys.argv[1:] if len(sys.argv) > 1 else ['exp_no_eval', 'exp_gen_only']

    prompt_manager = PromptManager(scenario_name="valid_permission")
    agent_builder = AgentBuilder(scenario_name="valid_permission")
    eval_agent = agent_builder.build_eval_agent()
    eval_module = EvaluationModule(evaluation_agent=eval_agent, prompt_manager=prompt_manager)

    conn = sqlite3.connect(settings.db_path, timeout=30)

    # 获取 no_eval 的约束列表（供 gen_only 使用）
    print("Loading no_eval constraints...")
    noeval_constraints = {}
    rows = conn.execute("SELECT instruct_id, constraints_list FROM experiments WHERE run_id='exp_no_eval'").fetchall()
    for iid, cl in rows:
        noeval_constraints[iid] = cl

    for run_id in target_runs:
        print(f"\n=== Processing {run_id} ===")
        rows = conn.execute(
            "SELECT instruct_id, generated_code, constraints_list FROM experiments WHERE run_id=? GROUP BY instruct_id HAVING MAX(rowid)",
            (run_id,)
        ).fetchall()

        correct = 0
        fail = 0
        sat_count = 0
        total = len(rows)

        for idx, (iid, code, cl) in enumerate(rows):
            if not code:
                continue

            # 确定约束列表
            constraints_json = cl
            if run_id == 'exp_gen_only' and iid in noeval_constraints:
                constraints_json = noeval_constraints[iid]

            result = await evaluate_case(eval_module, code, constraints_json)

            if result.get("all_satisfied") is True:
                sat_count += 1
            elif result.get("all_satisfied") is False:
                fail += 1

            if (idx + 1) % 10 == 0:
                print(f"  {run_id}: {idx+1}/{total}, all_sat={sat_count}/{idx+1}")

        print(f"\n  {run_id} 完成: {total}例")
        print(f"  all_satisfied: {sat_count}/{total} = {sat_count/total*100:.1f}%")
        print(f"  not_satisfied: {fail}/{total}")

    conn.close()
    print("\n全部完成")


if __name__ == "__main__":
    asyncio.run(main())
