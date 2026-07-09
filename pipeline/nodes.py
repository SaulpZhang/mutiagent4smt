from __future__ import annotations

import json
import time
from typing import Any

from config import settings
from core.schemas import Constraint, ConstraintsList, EvaluationResult, SMTLibCode
from core.trace_logger import TraceLogger
from modules.generation_module import GenerationModule
from modules.evaluation_module import EvaluationModule
from modules.output_module import OutputModule
from modules.verification_module import VerificationModule
from modules.agent_builder import AgentBuilder
from core.prompt_manager import PromptManager


class PipelineNodes:
    """流水线节点适配器：注册所有模块并实现节点函数"""

    def __init__(
        self,
        scenario_name: str = "valid_permission",
        run_id: str = "",
        instruct_id: str = "",
    ) -> None:
        self._modules: dict[str, Any] = {}
        self.run_id = run_id
        self.scenario_name = scenario_name

        prompt_manager = PromptManager(scenario_name=scenario_name)
        agent_builder = AgentBuilder(scenario_name=scenario_name)
        verification_module = VerificationModule()

        # 每个 Agent 独立的日志记录器（按用例分目录）
        self._loggers: dict[str, TraceLogger] = {
            "agent1": TraceLogger(run_id, "agent1", case_id=instruct_id),
            "agent2": TraceLogger(run_id, "agent2", case_id=instruct_id),
            "agent3": TraceLogger(run_id, "agent3", case_id=instruct_id),
        }

        # Agent 2: ToolAgent（LLM 自主选择编译器或 Z3 Python）
        tool_agent = agent_builder.build_tool_code_gen_agent()
        fix_agent = agent_builder.build_fix_agent()

        self._modules["generation"] = GenerationModule(
            intent_agent=agent_builder.build_intent_agent(),
            prompt_manager=prompt_manager,
            tool_agent=tool_agent,
            fix_agent=fix_agent,
        )
        self._modules["evaluation"] = EvaluationModule(
            evaluation_agent=agent_builder.build_eval_agent(),
            prompt_manager=prompt_manager,
        )
        self._modules["output"] = OutputModule(
            code_output_dir=settings.experiments_dir,
            run_id=run_id,
        )
        self._modules["verification"] = verification_module

    def _get(self, name: str) -> Any:
        m = self._modules.get(name)
        if m is None:
            raise RuntimeError(f"模块未注册: {name}")
        return m

    async def intent_agent_node(self, state: dict) -> dict:
        """智能体一：意图理解生成约束列表"""
        t0 = time.perf_counter()
        gen_module: GenerationModule = self._get("generation")
        input_data = state.get("input_data")
        if not input_data:
            return {"error_message": "缺少输入数据"}
        extras = dict(state.get("extras", {}))
        extras["gen_start_time"] = time.perf_counter()

        self._loggers["agent1"].log_separator("意图理解 — 约束生成")
        print(f"  [timing] A1 意图理解 开始")

        try:
            constraints = await gen_module.run_intent_analysis(
                input_data,
                trace_logger=self._loggers["agent1"],
            )
            elapsed = time.perf_counter() - t0
            print(f"  [timing] A1 意图理解 完成 ({elapsed:.1f}s)")
            return {"extras": extras, "constraints_list": constraints}
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  [timing] A1 意图理解 失败 ({elapsed:.1f}s): {e}")
            return {"extras": extras, "error_message": f"意图理解失败: {e}"}

    async def mock_intent_node(self, state: dict) -> dict:
        """非LLM约束生成：返回空约束列表，generate_smt_from_policy 自行推断

        gen_only 消融模式下，A2直接基于IAM配置生成代码，不依赖预解析的约束。
        """
        input_data = state.get("input_data")
        if not input_data:
            return {"error_message": "缺少输入数据"}
        extras = dict(state.get("extras", {}))
        extras["gen_start_time"] = time.perf_counter()
        return {"extras": extras, "constraints_list": ConstraintsList(constraints=[])}

    async def code_gen_node(self, state: dict) -> dict:
        """智能体二：ToolAgent 代码生成（ReAct 模式，LLM 自主选择工具）"""
        t0 = time.perf_counter()
        if state.get("error_message"):
            return {}

        gen_module: GenerationModule = self._get("generation")
        input_data = state.get("input_data")
        constraints = state.get("constraints_list")
        evaluation = state.get("evaluation_result")
        iteration = state.get("iteration", 0)
        trace_logger = self._loggers["agent2"]
        extras = dict(state.get("extras", {}))
        extras["trace_logger"] = trace_logger

        if not input_data or not constraints:
            return {"error_message": "缺少输入数据或约束列表"}

        # 对话式日志：迭代分隔
        if iteration > 0:
            trace_logger.log_separator(f"Code Generation — Iteration {iteration}（反馈修正）")
            print(f"  [timing] A2 代码生成 开始 (iter {iteration})")
        else:
            trace_logger.log_separator("Code Generation — 初始生成")
            print(f"  [timing] A2 代码生成 开始 (首次)")

        try:
            if iteration > 0 and evaluation:
                original_code = state.get("smt_code")
                original_str = original_code.code if hasattr(original_code, 'code') else str(original_code) if original_code else ""
                result = await gen_module.run_code_fix(
                    original_code=original_str,
                    input_data=input_data,
                    constraints=constraints,
                    evaluation_feedback=evaluation,
                    trace_logger=trace_logger,
                )
            else:
                result = await gen_module.run_code_generation(
                    input_data, constraints, trace_logger=trace_logger,
                )
            elapsed = time.perf_counter() - t0
            print(f"  [timing] A2 代码生成 完成 ({elapsed:.1f}s)")
            return {"smt_code": result, "extras": extras}
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  [timing] A2 代码生成 失败 ({elapsed:.1f}s): {e}")
            return {"error_message": f"代码生成失败: {e}"}

    async def evaluate_node(self, state: dict) -> dict:
        """智能体三：语义评估"""
        t0 = time.perf_counter()
        if state.get("error_message"):
            return {}

        eval_module: EvaluationModule = self._get("evaluation")
        code = state.get("smt_code")
        constraints = state.get("constraints_list")
        iteration = state.get("iteration", 0)
        trace_logger: TraceLogger | None = state.get("extras", {}).get("trace_logger")

        if not code or not constraints:
            return {"error_message": "缺少代码或约束列表"}

        # 对话式日志：评估分隔
        self._loggers["agent3"].log_separator(f"Evaluation — Iteration {iteration}")
        print(f"  [timing] A3 评估 开始 (iter {iteration})")

        try:
            result = await eval_module.evaluate(
                code, constraints, trace_logger=self._loggers["agent3"], iteration=iteration,
            )
            elapsed = time.perf_counter() - t0
            satisfied = f"{result.satisfied_count}/{len(result.items)}" if result.items else "?"
            print(f"  [timing] A3 评估 完成 ({elapsed:.1f}s, 满足: {satisfied})")
            return {"evaluation_result": result, "iteration": iteration + 1}
        except Exception as e:
            elapsed = time.perf_counter() - t0
            print(f"  [timing] A3 评估 失败 ({elapsed:.1f}s): {e}")
            return {"error_message": f"评估失败: {e}", "iteration": iteration + 1}

    async def output_node(self, state: dict) -> dict:
        """输出节点"""
        output_module: OutputModule = self._get("output")
        code = state.get("smt_code")
        evaluation = state.get("evaluation_result")
        constraints = state.get("constraints_list")
        instruct_id = state.get("instruct_id", "unknown")

        # 消融实验无评估时使用空评估结果占位
        if code and not evaluation:
            evaluation = EvaluationResult(items=[], all_satisfied=True, summary="消融模式 — 无Agent3评估")

        if not code:
            error_msg = state.get("error_message", "未知错误")
            output_result = output_module.generate_error_output(error_msg, instruct_id)
        else:
            output_result = output_module.generate_output(code, evaluation, instruct_id, constraints)

        extras = dict(state.get("extras", {}))
        extras["gen_end_time"] = time.perf_counter()
        return {"extras": extras, "output_result": output_result}

    async def verify_node(self, state: dict) -> dict:
        """验证节点：Z3执行"""
        ver_module: VerificationModule = self._get("verification")
        output = state.get("output_result")

        if not output or not output.code:
            return {}

        from core.schemas import VerificationResult
        is_exec, exec_out, exec_ms = ver_module.execute(output.code)

        self._loggers["agent2"].log_verify_result(output.code.code, exec_out, exec_ms)

        return {
            "verification_result": VerificationResult(
                is_executable=is_exec,
                execution_output=exec_out,
                execution_time_ms=exec_ms,
            ),
        }
