from __future__ import annotations

import json
import re

from agent.skill_agent import SkillAgent
from core.schemas import ConstraintsList, Constraint


class IntentUnderstandingAgent:
    """智能体一：意图理解（ReAct）

    通过 ReAct 循环自主调用工具分析 IAM 配置并生成约束列表。
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm_client,
        skills: list,
        max_steps: int = 20,
    ) -> None:
        self._agent = SkillAgent(name, llm_client, skills, system_prompt, max_steps)

    async def run(self, **kwargs) -> ConstraintsList:
        prompt = kwargs.get("prompt", "")
        trace_logger = kwargs.get("trace_logger")
        if not prompt:
            raise ValueError("缺少prompt参数")

        result = await self._agent.run(
            user_message=prompt,
            trace_logger=trace_logger,
        )
        return self._parse_response(result)

    def _parse_response(self, response: str) -> ConstraintsList:
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
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
        # 先尝试从 markdown 代码块中提取 JSON
        match = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and "constraints" in data:
                    return data
            except json.JSONDecodeError:
                pass

        for match in re.finditer(r'\{.*?\}', text, re.DOTALL):
            candidate = match.group()
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and "constraints" in data:
                    return data
            except json.JSONDecodeError:
                continue
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            candidate = match.group()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        return {"constraints": []}
