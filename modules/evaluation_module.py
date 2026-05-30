from __future__ import annotations

import re

from agent.base import BaseAgent
from core.schemas import ConstraintsList, EvaluationResult, SMTLibCode
from core.prompt_manager import PromptManager


def strip_smt_comments(code: str) -> str:
    """去除SMT-LIB V2代码中的注释（;行注释），避免注释干扰评估"""
    return re.sub(r";[^\n]*", "", code)


class EvaluationModule:
    """评估模块：运行智能体三（评估），判断代码是否满足约束"""

    def __init__(
        self,
        evaluation_agent: BaseAgent,
        prompt_manager: PromptManager,
    ) -> None:
        self.evaluation_agent = evaluation_agent
        self.prompt_manager = prompt_manager

    async def evaluate(
        self,
        code: SMTLibCode,
        constraints: ConstraintsList,
        trace_logger=None,
        iteration: int = 1,
    ) -> EvaluationResult:
        """运行智能体三：从 agent3.md 加载 User prompt，传给 evaluation_agent"""
        clean_code = strip_smt_comments(code.code)

        system_prompt, user_prompt = self.prompt_manager.load_agent_prompt(
            "3",
            smt_code=clean_code,
            constraints_list=constraints.model_dump_json(),
        )
        result = await self.evaluation_agent.run(prompt=user_prompt, trace_logger=trace_logger)
        if trace_logger:
            trace_logger.log(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=str(result),
                iteration=iteration,
            )
        return result  # type: ignore[return-value]
