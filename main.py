#!/usr/bin/env python3
"""CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

使用方法:
    python main.py run              # 运行系统流水线（全部126个用例）
    python main.py run --index 1    # 只运行第1个用例
    python main.py stats            # 查看实验结果统计
    python main.py init             # 检查项目配置
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import time


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
        "-p", "--parallel", type=int, default=10,
        help="并行处理数（默认10）",
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
    """运行系统流水线（支持并行处理）"""
    from config import settings
    from core.schemas import ExperimentRecord
    from modules.input_module import InputModule
    from experiment.recorder import ExperimentRecorder
    from pipeline.graph import compile_pipeline

    parallel = args.parallel or 1

    print("=" * 60)
    print("  CodeV 系统流水线")
    print("  多LLM智能体集成的IAM策略形式化验证")
    if parallel > 1:
        print(f"  并行数: {parallel}")
    print("=" * 60)

    input_module = InputModule(settings.data_dir)
    recorder = ExperimentRecorder(settings.db_path)
    recorder.enable_wal()

    pairs = input_module.load_all_pairs()
    answers = input_module.load_answers()

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    print(f"  实验编号: {run_id}\n")

    if args.index is not None:
        indices = [args.index - 1]
        total = 1
        print(f"运行单用例: 第 {args.index} 个\n")
    else:
        indices = list(range(len(pairs)))
        total = len(pairs)
        print(f"运行全部 {total} 个用例\n")

    async def process_one(idx: int) -> dict:
        """处理单个用例，返回该用例的结果摘要"""
        case = pairs[idx]
        label = answers[idx] if idx < len(answers) else None
        case_num = idx + 1

        # 每条数据创建全新的3个Agent，实验结束后销毁
        case_pipeline = compile_pipeline()

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
            "tracking": record,
            "error_message": None,
            "extras": {},
        }

        case_start = time.perf_counter()
        result = {"idx": idx, "success": False, "aligned": False, "error": False}

        try:
            final_state = await case_pipeline.ainvoke(initial_state)
            elapsed_ms = (time.perf_counter() - case_start) * 1000
            error_msg = final_state.get("error_message")

            if error_msg:
                print(f"  [{case_num}/{total}] {case.instruct_id} [!] {error_msg}")
                record.status = "error"
                record.error_message = error_msg
                result["error"] = True
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

                # 约束满足统计
                if ev_result:
                    record.total_constraint_count = len(ev_result.items)
                    record.satisfied_count = ev_result.satisfied_count
                # 标签匹配统计
                if ver_result and label is not None:
                    z3_output = ver_result.execution_output.strip().lower()
                    z3_has_permission = z3_output == "sat"
                    record.label_match = z3_has_permission == label

                all_satisfied = record.all_satisfied
                result["success"] = True
                result["aligned"] = bool(all_satisfied)

                status = "✓" if all_satisfied else "~"
                iters = record.num_iterations
                match_str = ""
                if ver_result and label is not None:
                    z3_output = ver_result.execution_output.strip().lower()
                    z3_has_permission = z3_output == "sat"
                    label_match = z3_has_permission == label
                    match_str = " ✓" if label_match else " ✗"
                    match_str += f" (Z3={z3_output}, label={label})"
                print(f"  [{case_num}/{total}] {case.instruct_id}: {status} "
                      f"({iters}次迭代{match_str}, {elapsed_ms:.0f}ms)")

            record.total_time_ms = elapsed_ms

        except Exception as e:
            elapsed_ms = (time.perf_counter() - case_start) * 1000
            record.status = "error"
            record.error_message = str(e)
            record.total_time_ms = elapsed_ms
            result["error"] = True
            result["success"] = False
            print(f"  [{case_num}/{total}] {case.instruct_id} [!!] {e}")

        try:
            recorder.save_experiment(record)
        except Exception as e:
            print(f"  [!] {case.instruct_id} 保存失败: {e}")

        return result

    if parallel > 1 and total > 1:
        # 分批处理
        batch_size = (total + parallel - 1) // parallel
        batches = [indices[i:i + batch_size] for i in range(0, total, batch_size)]
        print(f"  分批: {len(batches)} 批, 每批 ~{batch_size} 条\n")

        async def run_batch(batch: list[int]) -> list[dict]:
            return [await process_one(idx) for idx in batch]

        batch_results_lists = await asyncio.gather(*[run_batch(b) for b in batches])
        # 扁平化结果
        all_results = [r for blist in batch_results_lists for r in blist]
    else:
        all_results = [await process_one(idx) for idx in indices]

    # 汇总 — 从数据库读取该次实验的完整统计
    stats = recorder.get_summary_stats(run_id=run_id)

    print(f"\n{'=' * 60}")
    print(f"  运行完成  实验编号: {run_id}")
    print(f"{'=' * 60}")
    print(f"  总用例:     {stats.get('total', 0)}")
    print(f"  成功:       {stats.get('success_count', 0)}")
    print(f"  错误:       {stats.get('error_count', 0)}")
    print(f"  {'─' * 47}")
    csr = stats.get('constraint_satisfaction_rate')
    if csr is not None:
        asc = stats.get('all_satisfied_count', 0)
        print(f"  全部约束满足: {asc} 例")
        print(f"  约束满足率:   {csr:.2%}")
    print(f"  {'─' * 47}")
    la = stats.get('label_accuracy')
    if la is not None:
        lmc = stats.get('label_match_count', 0)
        ltc = stats.get('label_total_count', 0)
        print(f"  标签匹配:     {lmc}/{ltc}")
        print(f"  标签准确率:   {la:.2%}")
    print(f"  {'─' * 47}")
    print(f"  平均耗时:     {stats.get('avg_time_ms', 0):.0f}ms")
    print(f"  平均迭代:     {stats.get('avg_iterations', 0):.1f}")
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
    print(f"  成功:       {stats.get('success_count', 0)}")
    print(f"  错误:       {stats.get('error_count', 0)}")
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
    print(f"  平均耗时:     {stats.get('avg_time_ms', 0):.0f}ms")
    print(f"  平均迭代:     {stats.get('avg_iterations', 0):.1f}")
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
    pm = PromptManager()
    templates = pm.list_templates()
    print(f"  模板文件: {len(templates)} 个")
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
