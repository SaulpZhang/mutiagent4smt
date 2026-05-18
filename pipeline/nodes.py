from __future__ import annotations

import time
from typing import Any

from config import settings
from core.schemas import SMTLibCode
from core.trace_logger import TraceLogger
from modules.generation_module import GenerationModule
from modules.evaluation_module import EvaluationModule
from modules.output_module import OutputModule
from modules.verification_module import VerificationModule
from modules.agent_builder import AgentBuilder
from prompt.manager import PromptManager


class PipelineNodes:
    """流水线节点适配器：注册所有模块并实现节点函数"""

    def __init__(self, prompt_type: str = "default", run_id: str = "") -> None:
        self._modules: dict[str, Any] = {}
        self.run_id = run_id

        # 初始化所有依赖
        prompt_manager = PromptManager(prompt_type=prompt_type)
        agent_builder = AgentBuilder()
        verification_module = VerificationModule()

        # 构建 ToolAgent（ReAct 模式，始终使用 gen_mode=2 路径）
        tool_agent = agent_builder.build_tool_code_gen_agent()

        self._modules["generation"] = GenerationModule(
            intent_agent=agent_builder.build_intent_agent(),
            prompt_manager=prompt_manager,
            verification_module=verification_module,
            tool_agent=tool_agent,
        )
        self._modules["evaluation"] = EvaluationModule(
            evaluation_agent=agent_builder.build_eval_agent(),
            prompt_manager=prompt_manager,
        )
        self._modules["output"] = OutputModule(settings.results_dir, run_id=run_id)
        self._modules["verification"] = verification_module

    def _get(self, name: str) -> Any:
        m = self._modules.get(name)
        if m is None:
            raise RuntimeError(f"模块未注册: {name}")
        return m

    def _make_logger(self, state: dict) -> TraceLogger | None:
        """从state创建用例级日志记录器"""
        instruct_id = state.get("instruct_id", "unknown")
        run_id = self.run_id
        attempt = state.get("extras", {}).get("attempt", 1)
        log_dir = f"{settings.data_dir}/../data/traces/{run_id}"
        return TraceLogger(log_dir, instruct_id, attempt=attempt)

    async def intent_agent_node(self, state: dict) -> dict:
        """智能体一：意图理解生成约束列表"""
        gen_module: GenerationModule = self._get("generation")
        input_data = state.get("input_data")
        if not input_data:
            return {"error_message": "缺少输入数据"}
        extras = dict(state.get("extras", {}))
        extras["gen_start_time"] = time.perf_counter()

        try:
            constraints = await gen_module.run_intent_analysis(input_data)
            return {"extras": extras, "constraints_list": constraints}
        except Exception as e:
            return {"extras": extras, "error_message": f"意图理解失败: {e}"}

    async def code_gen_node(self, state: dict) -> dict:
        """智能体二：ToolAgent 代码生成（ReAct 模式，自检语法）"""
        if state.get("error_message"):
            return {}

        gen_module: GenerationModule = self._get("generation")
        input_data = state.get("input_data")
        constraints = state.get("constraints_list")
        evaluation = state.get("evaluation_result")
        iteration = state.get("iteration", 0)
        current_code: SMTLibCode | None = state.get("smt_code")
        trace_logger = self._make_logger(state)
        # 存入 extras 供其他节点复用
        extras = dict(state.get("extras", {}))
        extras["trace_logger"] = trace_logger

        if not input_data or not constraints:
            return {"error_message": "缺少输入数据或约束列表"}

        try:
            extra_hint = ""
            if state.get("regeneration_count", 0) > 0:
                # 用于重新生成（目前不会触发，保留兼容）
                pass

            if iteration > 0 and evaluation:
                result = await gen_module.run_code_generation(
                    input_data, constraints,
                    evaluation_feedback=evaluation,
                    trace_logger=trace_logger,
                    iteration=iteration,
                )
            else:
                result = await gen_module.run_code_generation(
                    input_data, constraints, trace_logger=trace_logger,
                )
            return {"smt_code": result, "extras": extras}
        except Exception as e:
            return {"error_message": f"代码生成失败: {e}"}

    async def evaluate_node(self, state: dict) -> dict:
        """智能体三：语义评估"""
        if state.get("error_message"):
            return {}

        eval_module: EvaluationModule = self._get("evaluation")
        code = state.get("smt_code")
        constraints = state.get("constraints_list")
        iteration = state.get("iteration", 0)
        trace_logger: TraceLogger | None = state.get("extras", {}).get("trace_logger")

        if not code or not constraints:
            return {"error_message": "缺少代码或约束列表"}

        try:
            result = await eval_module.evaluate(
                code, constraints, trace_logger=trace_logger, iteration=iteration,
            )
            return {"evaluation_result": result, "iteration": iteration + 1}
        except Exception as e:
            return {"error_message": f"评估失败: {e}", "iteration": iteration + 1}

    async def output_node(self, state: dict) -> dict:
        """输出节点"""
        output_module: OutputModule = self._get("output")
        code = state.get("smt_code")
        evaluation = state.get("evaluation_result")
        instruct_id = state.get("instruct_id", "unknown")

        if not code or not evaluation:
            error_msg = state.get("error_message", "未知错误")
            output_result = output_module.generate_error_output(error_msg, instruct_id)
        else:
            output_result = output_module.generate_output(code, evaluation, instruct_id)

        extras = dict(state.get("extras", {}))
        extras["gen_end_time"] = time.perf_counter()
        return {"extras": extras, "output_result": output_result}

    async def verify_node(self, state: dict) -> dict:
        """验证节点：Z3执行"""
        ver_module: VerificationModule = self._get("verification")
        output = state.get("output_result")
        trace_logger: TraceLogger | None = state.get("extras", {}).get("trace_logger")

        if not output or not output.code:
            return {}

        from core.schemas import VerificationResult
        is_exec, exec_out, exec_ms = ver_module.execute(output.code)

        if trace_logger:
            trace_logger.log_verify_result(output.code.code, exec_out, exec_ms)

        return {
            "verification_result": VerificationResult(
                is_executable=is_exec,
                execution_output=exec_out,
                execution_time_ms=exec_ms,
            ),
        }
