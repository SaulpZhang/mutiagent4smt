from __future__ import annotations

import json

from agent.base import BaseAgent
from core.schemas import ConstraintsList, Constraint


class IntentUnderstandingAgent(BaseAgent):
    """智能体一：意图理解

    分析验证指令和IAM配置，生成结构化的约束列表。
    运行独立，只使用原始输入信息，不受其他智能体影响。
    """

    async def run(self, **kwargs) -> ConstraintsList:
        prompt = kwargs.get("prompt", "")
        if not prompt:
            raise ValueError("缺少prompt参数")

        response = await self.llm_client.chat(
            system_prompt=self.system_prompt,
            user_message=prompt,
            json_output=True,
        )

        return self._parse_response(response)

    def _parse_response(self, response: str) -> ConstraintsList:
        """解析LLM响应为约束列表"""
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取JSON块
            data = self._extract_json(response)

        constraints_raw = data.get("constraints", [])
        constraints = []
        for i, item in enumerate(constraints_raw):
            cid = item.get("id", f"C{i + 1}")
            desc = item.get("description") or item.get("constraint", "")
            cat = item.get("category", "instruction_derived")
            constraints.append(Constraint(id=cid, description=desc, category=cat))

        if not constraints:
            raise ValueError("未能从LLM响应中解析出约束列表")

        return ConstraintsList(constraints=constraints)

    def _extract_json(self, text: str) -> dict:
        """从文本中提取JSON块"""
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"constraints": []}
