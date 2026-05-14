from __future__ import annotations

from typing import Any

from config import settings
from core.schemas import SMTLibCode
from modules.generation_module import GenerationModule
from modules.evaluation_module import EvaluationModule
from modules.output_module import OutputModule
from modules.verification_module import VerificationModule
from modules.agent_builder import AgentBuilder
from prompt.manager import PromptManager


class PipelineNodes:
    """流水线节点适配器：注册所有模块并实现节点函数"""

    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}

        # 初始化所有依赖
        prompt_manager = PromptManager()
        agent_builder = AgentBuilder()
        verification_module = VerificationModule()

        self._modules["generation"] = GenerationModule(
            intent_agent=agent_builder.build_intent_agent(),
            code_gen_agent=agent_builder.build_code_gen_agent(),
            prompt_manager=prompt_manager,
            verification_module=verification_module,
        )
        self._modules["evaluation"] = EvaluationModule(
            evaluation_agent=agent_builder.build_eval_agent(),
            prompt_manager=prompt_manager,
        )
        self._modules["output"] = OutputModule(settings.results_dir)
        self._modules["verification"] = verification_module

        self._syntax_fix_agent = agent_builder.build_syntax_fix_agent()
        self._code_mod_agent = agent_builder.build_code_mod_agent()
        self._prompt_manager = prompt_manager

    def _get(self, name: str) -> Any:
        m = self._modules.get(name)
        if m is None:
            raise RuntimeError(f"模块未注册: {name}")
        return m

    async def intent_agent_node(self, state: dict) -> dict:
        """智能体一：意图理解生成约束列表"""
        gen_module: GenerationModule = self._get("generation")
        input_data = state.get("input_data")
        if not input_data:
            return {"error_message": "缺少输入数据"}
        try:
            constraints = await gen_module.run_intent_analysis(input_data)
            return {"constraints_list": constraints}
        except Exception as e:
            return {"error_message": f"意图理解失败: {e}"}

    async def code_gen_node(self, state: dict) -> dict:
        """智能体二：代码生成或修正"""
        gen_module: GenerationModule = self._get("generation")
        input_data = state.get("input_data")
        constraints = state.get("constraints_list")
        evaluation = state.get("evaluation_result")
        iteration = state.get("iteration", 0)
        current_code: SMTLibCode | None = state.get("smt_code")

        if not input_data or not constraints:
            return {"error_message": "缺少输入数据或约束列表"}

        try:
            if iteration > 0 and evaluation:
                result = await gen_module.run_code_generation(
                    input_data, constraints,
                    evaluation_feedback=evaluation,
                    current_code=current_code,
                )
            else:
                result = await gen_module.run_code_generation(input_data, constraints)
            return {"smt_code": result}
        except Exception as e:
            return {"error_message": f"代码生成失败: {e}"}

    async def syntax_check_node(self, state: dict) -> dict:
        """语法检查节点（含自修正循环）"""
        code: SMTLibCode | None = state.get("smt_code")
        if not code:
            return {"error_message": "缺少待检查的代码"}

        gen_module: GenerationModule = self._get("generation")
        new_code, retry_count = await gen_module.syntax_fix_loop(code)

        ver_module = self._get("verification")
        syntax_result = ver_module.check_syntax(new_code)

        return {
            "smt_code": new_code,
            "syntax_result": syntax_result,
            "syntax_retry_count": state.get("syntax_retry_count", 0) + retry_count + 1,
        }

    async def evaluate_node(self, state: dict) -> dict:
        """智能体三：语义评估"""
        eval_module: EvaluationModule = self._get("evaluation")
        code = state.get("smt_code")
        constraints = state.get("constraints_list")
        iteration = state.get("iteration", 0)

        if not code or not constraints:
            return {"error_message": "缺少代码或约束列表"}

        try:
            result = await eval_module.evaluate(code, constraints)
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

        return {"output_result": output_result}

    async def verify_node(self, state: dict) -> dict:
        """验证节点：Z3执行"""
        ver_module: VerificationModule = self._get("verification")
        output = state.get("output_result")
        if not output or not output.code:
            return {}

        from core.schemas import VerificationResult
        is_exec, exec_out, exec_ms = ver_module.execute(output.code)
        return {
            "verification_result": VerificationResult(
                is_executable=is_exec,
                execution_output=exec_out,
                execution_time_ms=exec_ms,
            ),
        }
