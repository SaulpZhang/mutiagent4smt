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
from prompt.manager import PromptManager
from modules.verification_module import VerificationModule


class GenerationModule:
    """生成模块：协调智能体一（意图理解）和智能体二（代码生成）

    职责：
    1. Agent 1: 分析指令和IAM配置，生成约束列表
    2. Agent 2: ToolAgent — 通过 ReAct 模式 + 工具调用生成 SMT 代码
    """

    def __init__(
        self,
        intent_agent: BaseAgent,
        prompt_manager: PromptManager,
        verification_module: VerificationModule,
        tool_agent: ToolAgent | None = None,
    ) -> None:
        self.intent_agent = intent_agent
        self.prompt_manager = prompt_manager
        self.verification_module = verification_module
        self.tool_agent = tool_agent

    async def run_intent_analysis(
        self,
        input_data: VerificationInput,
        trace_logger: TraceLogger | None = None,
    ) -> ConstraintsList:
        """运行智能体一：意图理解，生成约束列表"""
        prompt = self.prompt_manager.load(
            "intent_understanding.txt",
            instruction=input_data.instruction,
        )
        result = await self.intent_agent.run(prompt=prompt)
        return result  # type: ignore[return-value]

    async def run_code_generation(
        self,
        input_data: VerificationInput,
        constraints: ConstraintsList,
        evaluation_feedback: EvaluationResult | None = None,
        trace_logger: TraceLogger | None = None,
        iteration: int = 1,
        extra_hint: str = "",
    ) -> SMTLibCode:
        """运行智能体二：通过 ToolAgent ReAct 模式生成 SMT 代码

        支持首次生成和语义修正（通过 evaluation_feedback 传入前次评估结果）。
        ToolAgent 在 ReAct 循环内使用 smt_verify 自检语法，不依赖外部语法修正节点。
        """
        if self.tool_agent is None:
            raise RuntimeError("gen_mode=2 需要 ToolAgent，但未构建")

        prompt_text = (
            f"验证指令：{input_data.instruction}\n\n"
            f"IAM配置：{str(input_data.account_data)}"
        )
        constraints_json = constraints.model_dump_json() if hasattr(constraints, "model_dump_json") else str(constraints)

        if evaluation_feedback:
            prompt_text += f"\n\n## 前次评估反馈（语义修正）\n{evaluation_feedback.model_dump_json()}"
        if extra_hint:
            prompt_text += f"\n\n{extra_hint}"

        result = await self.tool_agent.run(
            prompt=prompt_text,
            constraints_json=constraints_json,
            account_data=input_data.account_data,
            trace_logger=trace_logger,
        )
        if trace_logger:
            trace_logger.log(
                "tool_agent",
                self.tool_agent.system_prompt[:200],
                prompt_text,
                result.code,
                iteration=iteration,
            )
        return result
