from __future__ import annotations

import re

from agent.base import BaseAgent
from core.schemas import ConstraintsList, EvaluationResult, SMTLibCode
from resources.prompt.manager import PromptManager


def strip_smt_comments(code: str) -> str:
    """去除SMT-LIB V2代码中的注释（;行注释），避免注释干扰评估"""
    return re.sub(r";[^\n]*", "", code)


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
        trace_logger=None,
        iteration: int = 1,
    ) -> EvaluationResult:
        """运行智能体三：评估代码是否满足约束列表

        Agent 3 持有 run_z3_check skill，会在评估前自动执行 Z3，
        将 sat/unsat 结果作为评估参考。
        """
        clean_code = strip_smt_comments(code.code)

        prompt = self.prompt_manager.load(
            "evaluation.txt",
            smt_code=clean_code,
            constraints_list=constraints.model_dump_json(),
        )
        result = await self.evaluation_agent.run(prompt=prompt)
        return result  # type: ignore[return-value]
