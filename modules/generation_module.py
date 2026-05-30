from __future__ import annotations

from agent.base import BaseAgent
from agent.tool_agent import ToolAgent
from core.schemas import (
    ConstraintsList,
    EvaluationResult,
    SMTLibCode,
    VerificationInput,
)
from core.trace_logger import TraceLogger
from core.prompt_manager import PromptManager


class GenerationModule:
    """生成模块：协调智能体一（意图理解）和智能体二（代码生成）"""

    def __init__(
        self,
        intent_agent: BaseAgent,
        prompt_manager: PromptManager,
        tool_agent: ToolAgent | None = None,
    ) -> None:
        self.intent_agent = intent_agent
        self.prompt_manager = prompt_manager
        self.tool_agent = tool_agent

    async def run_intent_analysis(
        self,
        input_data: VerificationInput,
        trace_logger: TraceLogger | None = None,
    ) -> ConstraintsList:
        """运行智能体一：从 agent1.md 加载 User prompt，传给 intent_agent"""
        system_prompt, user_prompt = self.prompt_manager.load_agent_prompt(
            "1",
            instruction=input_data.instruction,
            account_data=str(input_data.account_data),
        )
        result = await self.intent_agent.run(prompt=user_prompt, trace_logger=trace_logger)
        if trace_logger:
            trace_logger.log(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=str(result),
                iteration=1,
            )
        return result  # type: ignore[return-value]

    async def run_code_generation(
        self,
        input_data: VerificationInput,
        constraints: ConstraintsList,
        evaluation_feedback: EvaluationResult | None = None,
        trace_logger: TraceLogger | None = None,
        iteration: int = 1,
    ) -> SMTLibCode:
        """运行智能体二：通过 ToolAgent ReAct 模式生成 SMT 代码"""
        if self.tool_agent is None:
            raise RuntimeError("GenerationModule 需要 ToolAgent，但未构建")

        prompt_text = (
            f"验证指令：{input_data.instruction}\n\n"
            f"IAM配置：{str(input_data.account_data)}"
        )
        constraints_json = (
            constraints.model_dump_json()
            if hasattr(constraints, "model_dump_json")
            else str(constraints)
        )

        if evaluation_feedback:
            prompt_text += (
                f"\n\n## 前次评估反馈（语义修正）\n"
                f"{evaluation_feedback.model_dump_json()}"
            )

        result = await self.tool_agent.run(
            prompt=prompt_text,
            constraints_json=constraints_json,
            account_data=input_data.account_data,
            evaluation_feedback=evaluation_feedback,
            trace_logger=trace_logger,
        )
        if trace_logger:
            trace_logger.log(
                system_prompt=self.tool_agent.system_prompt,
                user_prompt=prompt_text,
                response=result.code,
                iteration=iteration,
            )
        return result
