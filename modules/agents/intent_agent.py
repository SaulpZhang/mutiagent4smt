from __future__ import annotations

import json
import re

from agent.base import BaseAgent
from core.schemas import ConstraintsList, Constraint


class IntentUnderstandingAgent(BaseAgent):
    """智能体一：意图理解

    持有 parse_iam_config skill：在调用 LLM 前显式执行该 skill 解析 IAM 配置，
    将结构化解析结果注入 prompt，帮助 LLM 生成更准确的约束列表。
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm_client,
        skills: list,
    ) -> None:
        super().__init__(name, system_prompt, llm_client)
        self._skills = {s.name: s for s in skills}

    async def run(self, **kwargs) -> ConstraintsList:
        prompt = kwargs.get("prompt", "")
        if not prompt:
            raise ValueError("缺少prompt参数")

        # 显式执行 parse_iam_config skill，将解析结果注入 prompt
        if "parse_iam_config" in self._skills:
            config_json = self._extract_config_json(prompt)
            if config_json:
                parsed = self._skills["parse_iam_config"].fn(config_json=config_json)
                prompt = prompt + f"\n\n## IAM配置解析结果（由 parse_iam_config skill 自动生成）\n{parsed}"

        response = await self._chat(user_message=prompt, json_output=True)
        return self._parse_response(response)

    def _extract_config_json(self, text: str) -> str | None:
        """从 prompt 中提取 IAM 配置 JSON 块"""
        match = re.search(r'\{[\s\S]*?"Statement"[\s\S]*?\}', text)
        if match:
            return match.group()
        return None

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
