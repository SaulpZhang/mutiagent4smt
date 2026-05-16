from __future__ import annotations

import json

from agent.base import BaseAgent
from core.schemas import SMTLibCode


class CodeGenerationAgent(BaseAgent):
    """智能体二：代码生成

    根据验证指令、IAM配置和约束列表生成SMT-LIB V2代码。
    支持语法修正和语义修正两种模式。
    """

    async def run(self, **kwargs) -> SMTLibCode:
        prompt = kwargs.get("prompt", "")
        if not prompt:
            raise ValueError("缺少prompt参数")

        response = await self.llm_client.chat(
            system_prompt=self.system_prompt,
            user_message=prompt,
        )

        return self._parse_response(response)

    def _parse_response(self, response: str) -> SMTLibCode:
        """解析LLM响应为SMT-LIB V2代码"""
        code = self._extract_code(response)

        if not code:
            # 无法提取代码块时，将整个响应视为代码
            code = response

        return SMTLibCode(code=code)

    def _extract_code(self, text: str) -> str:
        """从LLM响应中提取SMT-LIB V2代码块（取最后一个代码块，因为CoT可能包含中间片段）"""
        import re

        patterns = [
            r'```(?:smt2|lisp|smt|z3)\s*\n(.*?)```',
            r'```\s*\n(.*?)```',
            r'```(.*?)```',
        ]
        for pattern in patterns:
            matches = list(re.finditer(pattern, text, re.DOTALL))
            if matches:
                return matches[-1].group(1).strip()

        return ""
