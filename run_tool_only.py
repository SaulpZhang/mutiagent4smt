"""A1 → generate_smt_from_policy → Z3 验证，绕过 A2 LLM

评估 generate_smt_from_policy 工具本身的 PASS@1。
"""
import asyncio
import json
import subprocess
import tempfile
import time
from pathlib import Path

from config import settings
from core.prompt_manager import PromptManager
from modules.agent_builder import AgentBuilder
from core.schemas import VerificationInput, ConstraintsList


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--runid", type=str, default="tool_only")
    parser.add_argument("--index", type=str, default=None, help="逗号分隔，如 1,5,22")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    prompt_manager = PromptManager(scenario_name="valid_permission")
    agent_builder = AgentBuilder(scenario_name="valid_permission")
    intent_agent = agent_builder.build_intent_agent()

    # 加载数据
    from modules.input_module import InputModule
    input_module = InputModule(settings.data_dir)
    pairs = input_module.load_all_pairs()
    answers = input_module.load_answers()

    if args.index:
        indices = [int(x.strip()) - 1 for x in args.index.split(",") if x.strip().isdigit()]
    else:
        indices = list(range(len(pairs)))

    # 导入工具（直接读文件）
    import runpy
    tool_mod = runpy.run_path(
        str(Path(__file__).parent / "resources/scenarios/valid_permission/tools/generate_smt_from_policy/tool.py")
    )
    gen_smt = tool_mod["execute"]

    total = len(indices)
    correct = 0
    wrong = 0
    error = 0
    results = []

    print(f"\n运行 {total} 个用例, workers={args.workers}, runid={args.runid}")
    print(f"{'='*60}")

    for pos, idx in enumerate(indices):
        case = pairs[idx]
        label = answers[idx]

        print(f"  [{pos+1}/{total}] {case.instruct_id} label={label} ...", end=" ")

        # A1 意图理解
        t0 = time.perf_counter()
        try:
            constraints = await intent_agent.run(prompt=str(case.model_dump_json()))
            t1 = time.perf_counter()
            print(f"A1({t1-t0:.1f}s)", end=" ")
        except Exception as e:
            print(f"A1失败: {e}")
            error += 1
            results.append({"id": case.instruct_id, "status": "a1_error", "label": label})
            continue

        # 工具生成 SMT 代码
        try:
            constraints_json = constraints.model_dump_json() if hasattr(constraints, "model_dump_json") else str(constraints)
            smt_code = gen_smt(json.dumps(case.account_data, ensure_ascii=False), constraints_json)
            t2 = time.perf_counter()
            if smt_code.startswith("错误："):
                print(f"工具错误: {smt_code[:50]}")
                error += 1
                results.append({"id": case.instruct_id, "status": "tool_error", "error": smt_code[:100], "label": label})
                continue
            print(f"工具({t2-t1:.1f}s)", end=" ")
        except Exception as e:
            print(f"工具异常: {e}")
            error += 1
            results.append({"id": case.instruct_id, "status": "tool_exception", "error": str(e)[:100], "label": label})
            continue

        # Z3 执行
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".smt2", delete=False) as f:
                f.write(smt_code)
                fname = f.name
            out = subprocess.run(["z3", fname], capture_output=True, text=True, timeout=30)
            Path(fname).unlink(missing_ok=True)
            z3_output = out.stdout.strip().lower()
            z3_has_permission = any(line.startswith("sat") for line in z3_output.split("\n"))
            match = (z3_has_permission == label)
            t3 = time.perf_counter()
            print(f"Z3({t3-t2:.1f}s)={'✓' if match else '✗'} (z3={z3_output[:15]} label={label})")

            if match:
                correct += 1
            else:
                wrong += 1
            results.append({
                "id": case.instruct_id,
                "status": "ok",
                "z3": z3_output[:50],
                "label": label,
                "match": match,
                "constraints": constraints_json,
            })
        except subprocess.TimeoutExpired:
            print(f"Z3超时")
            error += 1
            Path(fname).unlink(missing_ok=True)
            results.append({"id": case.instruct_id, "status": "z3_timeout", "label": label})

    # 汇总
    print(f"\n{'='*60}")
    print(f"  run_id: {args.runid}")
    print(f"  总用例: {total}")
    print(f"  正确:   {correct} ({correct/total*100:.1f}%)")
    print(f"  错误:   {wrong} ({wrong/total*100:.1f}%)")
    print(f"  异常:   {error}")
    if wrong > 0:
        print(f"\n  错误列表:")
        for r in results:
            if r.get("match") is False:
                print(f"    {r['id']}: z3={r.get('z3','')} label={r['label']}")
    if error > 0:
        print(f"\n  异常列表:")
        for r in results:
            if r.get("status") != "ok":
                print(f"    {r['id']}: {r.get('status')} {r.get('error','')}")

    # 保存结果
    out_dir = Path("data") / args.runid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n  结果已保存到 {out_dir / 'results.json'}")


if __name__ == "__main__":
    asyncio.run(main())
