from __future__ import annotations

import json

from agent.base import BaseAgent
from core.schemas import EvaluationItem, EvaluationResult


class EvaluationAgent(BaseAgent):
    """智能体三：语义评估

    评估生成的SMT-LIB V2代码是否满足约束列表中的每项约束。
    保持中立和客观，只依据约束列表进行判断。
    """

    async def run(self, **kwargs) -> EvaluationResult:
        prompt = kwargs.get("prompt", "")
        if not prompt:
            raise ValueError("缺少prompt参数")

        response = await self.llm_client.chat(
            system_prompt=self.system_prompt,
            user_message=prompt,
            json_output=True,
        )

        return self._parse_response(response)

    def _parse_response(self, response: str) -> EvaluationResult:
        """解析LLM响应为评估结果"""
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = self._extract_json(response)

        items_raw = data.get("items") or data.get("evaluations") or data.get("results", [])
        items = []
        for item in items_raw:
            cid = item.get("constraint_id") or item.get("id", "")
            status = item.get("status", "not_satisfied")
            reason = item.get("reason", "")
            items.append(EvaluationItem(
                constraint_id=cid,
                status=status,
                reason=reason,
            ))

        # 如果没有items但有顶层字段，尝试从顶层字段生成
        if not items:
            all_sat = data.get("all_satisfied", data.get("all_satisfied", False))
            if isinstance(all_sat, str):
                all_sat = all_sat.lower() == "true"
            if not items:
                summary = data.get("summary", data.get("evaluation", ""))
                items.append(EvaluationItem(
                    constraint_id="C1",
                    status="satisfied" if all_sat else "not_satisfied",
                    reason=summary,
                ))

        all_satisfied = all(item.status == "satisfied" for item in items)
        summary = data.get("summary", data.get("conclusion", ""))

        return EvaluationResult(
            items=items,
            all_satisfied=all_satisfied,
            summary=summary,
        )

    def _extract_json(self, text: str) -> dict:
        """从文本中提取JSON块"""
        import re
        for match in re.finditer(r'\{.*?\}', text, re.DOTALL):
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and ("items" in data or "all_satisfied" in data):
                    return data
            except json.JSONDecodeError:
                continue
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {"items": [], "all_satisfied": False}
