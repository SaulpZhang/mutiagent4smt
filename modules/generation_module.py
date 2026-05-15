from __future__ import annotations

from agent.base import BaseAgent
from config import settings
from core.schemas import (
    ConstraintsList,
    EvaluationResult,
    SMTLibCode,
    SyntaxResult,
    VerificationInput,
)
from core.trace_logger import TraceLogger
from prompt.manager import PromptManager
from modules.verification_module import VerificationModule


class GenerationModule:
    """生成模块：协调智能体一（意图理解）和智能体二（代码生成）

    职责：
    1. Agent 1: 分析指令和IAM配置，生成约束列表
    2. Agent 2: 生成SMT-LIB V2代码，包含语法修正循环
    """

    def __init__(
        self,
        intent_agent: BaseAgent,
        code_gen_agent: BaseAgent,
        prompt_manager: PromptManager,
        verification_module: VerificationModule,
    ) -> None:
        self.intent_agent = intent_agent
        self.code_gen_agent = code_gen_agent
        self.prompt_manager = prompt_manager
        self.verification_module = verification_module

    async def run_intent_analysis(
        self,
        input_data: VerificationInput,
        trace_logger: TraceLogger | None = None,
    ) -> ConstraintsList:
        """运行智能体一：意图理解，生成约束列表"""
        prompt = self.prompt_manager.load(
            "intent_understanding.txt",
            instruction=input_data.instruction,
            account_data=str(input_data.account_data),
        )
        result = await self.intent_agent.run(prompt=prompt)

        if trace_logger:
            trace_logger.log(
                "intent_agent",
                self.intent_agent.system_prompt,
                prompt,
                result.model_dump_json() if hasattr(result, "model_dump_json") else str(result),
            )

        return result  # type: ignore[return-value]

    async def run_code_generation(
        self,
        input_data: VerificationInput,
        constraints: ConstraintsList,
        evaluation_feedback: EvaluationResult | None = None,
        current_code: SMTLibCode | None = None,
        trace_logger: TraceLogger | None = None,
        iteration: int = 1,
    ) -> SMTLibCode:
        """运行智能体二：生成SMT-LIB V2代码

        如果提供了evaluation_feedback，则为语义修正模式。
        semantic_fix模式下需传入current_code作为待修改的代码。
        """
        if evaluation_feedback:
            code_text = current_code.code if current_code else ""
            prompt = self.prompt_manager.load(
                "code_modification.txt",
                smt_code=code_text,
                evaluation_result=evaluation_feedback.model_dump_json(),
            )
            agent_label = "semantic_fix"
        else:
            prompt = self.prompt_manager.load(
                "code_generation.txt",
                instruction=input_data.instruction,
                account_data=str(input_data.account_data),
                constraints_list=constraints.model_dump_json(),
            )
            agent_label = "code_gen"

        result = await self.code_gen_agent.run(prompt=prompt)

        if trace_logger:
            extra = f"Iteration: {iteration}" if iteration > 1 else ""
            trace_logger.log(
                agent_label,
                self.code_gen_agent.system_prompt,
                prompt,
                result.code,
                iteration=iteration,
                extra=extra,
            )

        return result  # type: ignore[return-value]

    async def syntax_fix_loop(
        self,
        code: SMTLibCode,
        max_retries: int | None = None,
        trace_logger: TraceLogger | None = None,
    ) -> tuple[SMTLibCode, int]:
        """语法修正循环：检查语法并修正，直到通过或达到最大次数

        Returns:
            (修正后的代码, 实际修正次数)
        """
        max_retries = max_retries or settings.max_syntax_retries
        current_code = code
        retry_count = 0

        while retry_count < max_retries:
            syntax_result = self.verification_module.check_syntax(current_code)
            if trace_logger:
                trace_logger.log_syntax_result(
                    current_code.code, syntax_result.is_valid, syntax_result.errors, retry_count
                )

            if syntax_result.is_valid:
                return current_code, retry_count

            error_info = "\n".join(syntax_result.errors)
            fix_prompt = self.prompt_manager.load(
                "syntax_fix.txt",
                smt_code=current_code.code,
                error_info=error_info,
            )
            result = await self.code_gen_agent.run(prompt=fix_prompt)

            if trace_logger:
                trace_logger.log(
                    "syntax_fix",
                    self.code_gen_agent.system_prompt,
                    fix_prompt,
                    result.code,
                    iteration=retry_count + 1,
                )

            current_code = result  # type: ignore[assignment]
            retry_count += 1

        return current_code, retry_count
