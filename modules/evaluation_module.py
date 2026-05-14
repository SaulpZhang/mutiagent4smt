from __future__ import annotations

from agent.base import BaseAgent
from core.schemas import ConstraintsList, EvaluationResult, SMTLibCode
from prompt.manager import PromptManager


class EvaluationModule:
    """评估模块：运行智能体三（评估），判断代码是否满足约束

    职责：
    1. 逐项评估生成的代码是否满足约束列表中的每个约束
    2. 返回评估结果，用于决定是否回退修改或进入输出
    3. 保持评估过程的独立性和客观性
    """

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
    ) -> EvaluationResult:
        """运行智能体三：评估代码是否满足约束列表"""
        prompt = self.prompt_manager.load(
            "evaluation.txt",
            smt_code=code.code,
            constraints_list=constraints.model_dump_json(),
        )
        result = await self.evaluation_agent.run(prompt=prompt)
        return result  # type: ignore[return-value]
