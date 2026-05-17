#!/usr/bin/env python3
"""CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

使用方法:
    python main.py run              # 运行系统流水线（全部126个用例）
    python main.py run --index 1         # 只运行第1个用例
    python main.py run --attempts 5       # 每个用例跑5次,计算PASS@1/3/5
    python main.py run --prompt-type v2   # 使用v2类型提示词
    python main.py stats                 # 查看实验结果统计
    python main.py init                  # 检查项目配置
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CodeV - 多LLM智能体集成的IAM策略形式化验证系统",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    run_parser = subparsers.add_parser("run", help="运行系统流水线")
    run_parser.add_argument(
        "--index", type=int, default=None,
        help="指定单个用例编号（从1开始），不指定则运行全部",
    )
    run_parser.add_argument(
        "--model", type=str, default=None,
        help="指定LLM模型名称",
    )
    run_parser.add_argument(
        "--attempts", type=int, default=5,
        help="每个用例重复尝试次数，用于计算PASS@K（默认5）",
    )
    run_parser.add_argument(
        "--prompt-type", type=str, default="default",
        help="提示词类型（默认default，对应 templates/ 目录）",
    )
    run_parser.add_argument(
        "--runid", type=str, default=None,
        help="自定义实验ID，不指定则自动生成",
    )
    run_parser.add_argument(
        "--from", type=int, default=None, dest="from_",
        help="起始用例编号（左开右闭，即不包含此用例），从1开始",
    )
    run_parser.add_argument(
        "--to", type=int, default=None,
        help="结束用例编号（左开右闭，即包含此用例），从1开始",
    )

    subparsers.add_parser("stats", help="查看实验结果统计")
    subparsers.add_parser("init", help="初始化项目（检查配置和依赖）")

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_pipeline(args))
    elif args.command == "stats":
        show_stats()
    elif args.command == "init":
        init_project()
    else:
        parser.print_help()


async def run_pipeline(args: argparse.Namespace) -> None:
    """运行系统流水线"""
    from config import settings
    from core.schemas import ExperimentRecord
    from modules.input_module import InputModule
    from experiment.recorder import ExperimentRecorder
    from pipeline.graph import compile_pipeline

    attempts = args.attempts or 1
    prompt_type = args.prompt_type or "default"

    print("=" * 60)
    print("  CodeV 系统流水线")
    print("  多LLM智能体集成的IAM策略形式化验证")
    if attempts > 1:
        print(f"  尝试次数: {attempts}（用于PASS@1/3/5统计）")
    print(f"  提示词:    {prompt_type}")
    print("=" * 60)

    input_module = InputModule(settings.data_dir)
    recorder = ExperimentRecorder(settings.db_path)
    recorder.enable_wal()

    pairs = input_module.load_all_pairs()
    answers = input_module.load_answers()

    run_id = args.runid or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    print(f"  实验编号: {run_id}\n")

    if args.index is not None:
        indices = [args.index - 1]
        total = 1
        print(f"运行单用例: 第 {args.index} 个\n")
    elif args.from_ is not None and args.to is not None:
        indices = list(range(args.from_, args.to))
        total = len(indices)
        print(f"运行用例 {args.from_}（不含）到 {args.to}（含），共 {total} 个\n")
    else:
        indices = list(range(len(pairs)))
        total = len(pairs)
        print(f"运行全部 {total} 个用例", end="")
        if attempts > 1:
            print(f"，总计 {total * attempts} 条记录", end="")
        print("\n")

    # 保存本次实验的运行参数
    recorder.save_run_config(run_id, {
        "prompt_type": prompt_type,
        "model_used": settings.model_name,
        "attempts": attempts,
        "max_iterations": settings.max_iterations,
        "max_syntax_retries": settings.max_syntax_retries,
        "total_cases": total,
    })

    async def process_one(idx: int) -> dict:
        """处理单个用例（内部循环 attempts 次），返回该用例的结果摘要"""
        case = pairs[idx]
        # 从 instruct_id (如 "instruct_1_50") 中提取编号 → answers 数组中定位
        import re as _re
        m = _re.search(r"_(\d+)$", case.instruct_id)
        label = answers[int(m.group(1)) - 1] if m else None
        case_num = idx + 1

        label_matches: list[bool] = []
        saved_record = None
        has_any_success = False
        result = {"idx": idx, "success": False, "aligned": False, "error": False}

        for attempt_num in range(1, attempts + 1):
            # 每次尝试创建全新的3个Agent
            case_pipeline = compile_pipeline(prompt_type=prompt_type, run_id=run_id)

            record = ExperimentRecord(
                instruct_id=case.instruct_id,
                account_id=case.account_id,
                instruction=case.instruction,
                account_data=case.account_data,
                model_used=settings.model_name,
                run_id=run_id,
            )

            initial_state = {
                "input_data": case,
                "instruct_id": case.instruct_id,
                "account_id": case.account_id,
                "label": label,
                "constraints_list": None,
                "smt_code": None,
                "syntax_result": None,
                "syntax_retry_count": 0,
                "evaluation_result": None,
                "output_result": None,
                "verification_result": None,
                "iteration": 0,
                "max_iterations": settings.max_iterations,
                "max_syntax_retries": settings.max_syntax_retries,
                "regeneration_count": 0,
                "tracking": record,
                "error_message": None,
                "extras": {"attempt": attempt_num},
            }

            try:
                case_timeout = 600  # 10 minutes max per case (LLM calls can be slow)
                final_state = await asyncio.wait_for(
                    case_pipeline.ainvoke(initial_state),
                    timeout=case_timeout,
                )
                extras = final_state.get("extras", {})
                gen_start = extras.get("gen_start_time")
                gen_end = extras.get("gen_end_time")
                elapsed_ms = ((gen_end - gen_start) * 1000) if gen_start and gen_end else 0.0
                error_msg = final_state.get("error_message")

                if error_msg:
                    record.status = "error"
                    record.error_message = error_msg
                    record.total_time_ms = elapsed_ms
                    # 即使出错也保存SMT代码
                    code = final_state.get("smt_code")
                    if code:
                        record.generated_code = code.code
                        from pathlib import Path as _Path
                        code_dir = _Path(settings.results_dir) / run_id
                        code_dir.mkdir(parents=True, exist_ok=True)
                        code_path = code_dir / f"{case.instruct_id}.smt2"
                        _Path(code_path).write_text(code.code)
                    saved_record = record
                    print(f"  [{case_num}/{total}] {case.instruct_id}[A{attempt_num}] [!] {error_msg}")
                else:
                    record.status = "success"
                    record.syntax_valid = (
                        final_state.get("syntax_result", None) is not None
                        and final_state["syntax_result"].is_valid
                    )
                    record.all_satisfied = (
                        final_state.get("evaluation_result", None) is not None
                        and final_state["evaluation_result"].all_satisfied
                    )
                    ev_result = final_state.get("evaluation_result")
                    if ev_result:
                        record.evaluation_result = ev_result.model_dump_json()
                    code = final_state.get("smt_code")
                    if code:
                        record.generated_code = code.code
                    constraints = final_state.get("constraints_list")
                    if constraints:
                        record.constraints_list = constraints.model_dump_json()
                        record.constraint_text = json.dumps(
                            [c.model_dump() for c in constraints.constraints],
                            ensure_ascii=False,
                        )
                    ver_result = final_state.get("verification_result")
                    if ver_result:
                        record.code_execution_result = ver_result.execution_output
                    record.num_iterations = final_state.get("iteration", 0)
                    record.num_syntax_retries = final_state.get("syntax_retry_count", 0)
                    record.label = label

                    if ev_result:
                        record.total_constraint_count = len(ev_result.items)
                        record.satisfied_count = ev_result.satisfied_count
                    if ver_result and label is not None:
                        z3_output = ver_result.execution_output.strip().lower()
                        z3_has_permission = z3_output == "sat"
                        record.label_match = z3_has_permission == label
                        label_matches.append(record.label_match)

                    all_satisfied = record.all_satisfied
                    if not has_any_success:  # 保留首次成功的结果
                        has_any_success = True
                        result["success"] = True
                        result["aligned"] = bool(all_satisfied)
                        result["error"] = False
                        saved_record = record

                    record.total_time_ms = elapsed_ms
                    status = "✓" if all_satisfied else "~"
                    iters = record.num_iterations
                    match_str = ""
                    if ver_result and label is not None:
                        z3_output = ver_result.execution_output.strip().lower()
                        z3_has_permission = z3_output == "sat"
                        label_match = z3_has_permission == label
                        match_str = " ✓" if label_match else " ✗"
                        match_str += f" (Z3={z3_output}, label={label})"
                    print(f"  [{case_num}/{total}] {case.instruct_id}[A{attempt_num}]: {status} "
                          f"({iters}次迭代{match_str}, {elapsed_ms:.0f}ms)")

                    # 标签匹配成功则提前终止
                    if record.label_match:
                        break

            except Exception as e:
                record.status = "error"
                record.error_message = str(e)
                record.total_time_ms = 0.0
                saved_record = record
                print(f"  [{case_num}/{total}] {case.instruct_id}[A{attempt_num}] [!!] {e}")

        # 计算首次成功位置
        if saved_record:
            saved_record.total_attempts = attempts
            for i, m in enumerate(label_matches):
                if m:
                    saved_record.first_success_at = i + 1
                    break

            try:
                recorder.save_experiment(saved_record)
            except Exception as e:
                print(f"  [!] {case.instruct_id} 保存失败: {e}")

        return result

    # 串行处理所有用例
    if attempts > 1:
        print(f"  每用例循环 {attempts} 次, 共 {total * attempts} 次 Agent 调用\n")
    from tqdm import tqdm
    all_results = []
    for idx in tqdm(indices, desc="处理用例", unit="用例"):
        all_results.append(await process_one(idx))

    # PASS@K 统计
    pass_stats = recorder.get_pass_at_k_stats(run_id=run_id)

    # 释放所有LLM客户端连接资源（httpx共享连接池）
    from agent.llm_client import LLMClient
    await LLMClient.close_all()

    print(f"\n{'=' * 60}")
    print(f"  运行完成  实验编号: {run_id}")
    print(f"{'=' * 60}")

    if attempts > 1:
        total_cases = pass_stats.get("total_cases", 0)
        print(f"  总记录数:   {total_cases} ({total_cases} 用例 × {attempts} 次)")

    print(f"  {'─' * 47}")

    for k in [1, 3, 5]:
        pk = pass_stats.get(f"pass_at_{k}")
        if pk is not None:
            pk_count = pass_stats.get(f"pass_at_{k}_count", 0)
            pk_total = pass_stats.get("total_cases", 0)
            print(f"  PASS@{k}:       {pk:.2%} ({pk_count}/{pk_total})")

    print(f"  {'─' * 47}")

    cpr = pass_stats.get("constraint_pass_rate")
    if cpr is not None:
        cpc = pass_stats.get("constraint_pass_count", 0)
        ct = pass_stats.get("total_cases", 0)
        print(f"  约束满足率: {cpr:.2%} ({cpc}/{ct})")

    print(f"  {'─' * 47}")
    print(f"  数据库:       {settings.db_path}")
    print(f"{'=' * 60}")


def show_stats() -> None:
    """显示实验结果统计"""
    from config import settings
    from experiment.recorder import ExperimentRecorder

    recorder = ExperimentRecorder(settings.db_path)
    stats = recorder.get_summary_stats()

    print("=" * 60)
    print("  实验结果统计")
    print("=" * 60)
    print(f"  总用例:     {stats.get('total', 0)}")
    print(f"  成功:       {stats.get('success_count') or 0}")
    print(f"  错误:       {stats.get('error_count') or 0}")
    print(f"  {'─' * 47}")
    # 约束满足率
    csr = stats.get('constraint_satisfaction_rate')
    if csr is not None:
        asc = stats.get('all_satisfied_count', 0)
        print(f"  全部约束满足: {asc} 例")
        print(f"  约束满足率:   {csr:.2%}")
    print(f"  {'─' * 47}")
    # 标签准确率
    la = stats.get('label_accuracy')
    if la is not None:
        lmc = stats.get('label_match_count', 0)
        ltc = stats.get('label_total_count', 0)
        print(f"  标签匹配:     {lmc}/{ltc}")
        print(f"  标签准确率:   {la:.2%}")
    print(f"  {'─' * 47}")
    print(f"  平均耗时:     {(stats.get('avg_time_ms') or 0):.0f}ms")
    print(f"  平均迭代:     {(stats.get('avg_iterations') or 0):.1f}")
    print("=" * 60)


def init_project() -> None:
    """初始化项目检查"""
    from config import settings
    from pathlib import Path
    from prompt.manager import PromptManager
    from modules.input_module import InputModule

    print("=" * 60)
    print("  CodeV 项目初始化检查")
    print("=" * 60)

    print(f"\n[配置]")
    print(f"  API URL: {settings.api_url or '未设置'}")
    print(f"  Model: {settings.model_name}")
    if not settings.api_key:
        print(f"  API Key: 未设置 (!)")
    else:
        print(f"  API Key: 已设置 ({settings.api_key[:8]}...)")

    print(f"\n[数据]")
    data_path = Path(settings.data_dir)
    if data_path.exists():
        im = InputModule(settings.data_dir)
        pairs = im.load_all_pairs()
        answers = im.load_answers()
        print(f"  数据目录: {data_path}")
        print(f"  指令文件: {len(pairs)} 个")
        print(f"  账户文件: {len(pairs)} 个")
        print(f"  答案: {len(answers)} 个 (true={sum(answers)}, false={len(answers)-sum(answers)})")
    else:
        print(f"  [!] 数据目录不存在: {settings.data_dir}")

    print(f"\n[Prompt]")
    print(f"  当前类型:  {settings.prompt_type}")
    # 列出所有可用类型
    from pathlib import Path as _Path
    templates_root = _Path(__file__).parent / "prompt" / "templates"
    types = ["default"]
    for d in templates_root.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            types.append(d.name)
    for pt in types:
        pm = PromptManager(prompt_type=pt)
        templates = pm.list_templates()
        print(f"  [{pt}] {len(templates)} 个模板")
        for t in templates:
            print(f"    - {t}")

    print(f"\n[依赖]")
    try:
        import z3
        print(f"  Z3: 已安装")
    except ImportError:
        print(f"  Z3: 未安装")
    try:
        import langgraph
        print(f"  LangGraph: 已安装")
    except ImportError:
        print(f"  LangGraph: 未安装")

    print(f"\n[Z3验证]")
    from utils.smt_executor import SMTExecutor
    executor = SMTExecutor()
    is_ok, out, ms = executor.execute("(check-sat)")
    print(f"  Z3基本测试: {'通过' if is_ok else '失败'} ({ms:.0f}ms)")
    if is_ok:
        print(f"  输出: {out}")

    print(f"\n{'=' * 60}")
    print(f"  初始化完成")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
