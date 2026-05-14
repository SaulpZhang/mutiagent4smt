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
    from modules.input_module import InputModule
    from experiment.tracker import tracker
    from experiment.recorder import ExperimentRecorder
    from pipeline.graph import compile_pipeline

    print("=" * 60)
    print("  CodeV 系统流水线")
    print("  多LLM智能体集成的IAM策略形式化验证")
    print("=" * 60)

    input_module = InputModule(settings.data_dir)
    recorder = ExperimentRecorder(settings.db_path)

    pairs = input_module.load_all_pairs()
    answers = input_module.load_answers()

    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    print(f"  实验编号: {run_id}\n")

    if args.index is not None:
        indices = [args.index - 1]
        total = 1
        print(f"\n运行单用例: 第 {args.index} 个")
    else:
        indices = range(len(pairs))
        total = len(pairs)
        print(f"\n运行全部 {total} 个用例\n")

    results_summary = {"success": 0, "failed": 0, "error": 0, "aligned": 0}

    for idx in indices:
        case = pairs[idx]
        label = answers[idx] if idx < len(answers) else None

        case_num = idx + 1
        print(f"\n[{case_num}/{total}] {case.instruct_id} | {case.instruction[:40]}...")

        # 每条数据创建全新的3个Agent，实验结束后销毁
        case_pipeline = compile_pipeline()

        record = tracker.start_new_record(
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

        try:
            final_state = await case_pipeline.ainvoke(initial_state)

            elapsed_ms = (time.perf_counter() - case_start) * 1000
            error_msg = final_state.get("error_message")

            if error_msg:
                print(f"  [!] 错误: {error_msg}")
                record.status = "error"
                record.error_message = error_msg
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
                ver_result = final_state.get("verification_result")
                if ver_result:
                    record.code_execution_result = ver_result.execution_output
                record.num_iterations = final_state.get("iteration", 0)
                record.num_syntax_retries = final_state.get("syntax_retry_count", 0)
                record.label = label

                if record.all_satisfied:
                    print(f"  ✓ 全部约束满足 ({record.num_iterations}次迭代)")
                    results_summary["aligned"] += 1
                else:
                    print(f"  ~ 存在不满足 ({record.num_iterations}次迭代)")
                    results_summary["failed"] += 1

                if ver_result and label is not None:
                    z3_output = ver_result.execution_output.strip().lower()
                    z3_has_permission = z3_output == "sat"
                    label_match = z3_has_permission == label
                    match_str = "✓" if label_match else "✗"
                    print(f"  Z3: {z3_output} | 预期: {label} | {match_str}")

                results_summary["success"] += 1

            record.total_time_ms = elapsed_ms
            print(f"  耗时: {elapsed_ms:.0f}ms")

        except Exception as e:
            elapsed_ms = (time.perf_counter() - case_start) * 1000
            record.status = "error"
            record.error_message = str(e)
            record.total_time_ms = elapsed_ms
            results_summary["error"] += 1
            print(f"  [!!] 异常: {e}")

        try:
            recorder.save_experiment(record)
        except Exception as e:
            print(f"  [!] 保存实验记录失败: {e}")

    print("\n" + "=" * 60)
    print(f"  运行完成")
    print(f"  成功: {results_summary['success']}, 失败: {results_summary['failed']}, 错误: {results_summary['error']}")
    if results_summary["success"] > 0:
        align_rate = results_summary["aligned"] / results_summary["success"] * 100
        print(f"  用户意图对齐率: {align_rate:.1f}%")
    print(f"  数据库: {settings.db_path}")
    print("=" * 60)


def show_stats() -> None:
    """显示实验结果统计"""
    from config import settings
    from experiment.recorder import ExperimentRecorder

    recorder = ExperimentRecorder(settings.db_path)
    stats = recorder.get_summary_stats()

    print("=" * 60)
    print("  实验结果统计")
    print("=" * 60)
    print(f"  总用例: {stats.get('total', 0)}")
    print(f"  成功: {stats.get('success_count', 0)}")
    print(f"  失败: {stats.get('failed_count', 0)}")
    print(f"  用户意图对齐: {stats.get('aligned_count', 0)}")
    print(f"  平均耗时: {stats.get('avg_time_ms', 0):.0f}ms")
    print(f"  平均迭代: {stats.get('avg_iterations', 0):.1f}")
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
