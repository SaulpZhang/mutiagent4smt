from __future__ import annotations

import json
import re

from agent.skill_agent import SkillAgent
from core.schemas import ConstraintsList, Constraint


def _fix_json(text: str) -> str:
    """修复 LLM 生成的 JSON 中常见语法问题（未转义引号等）"""
    # 将中文字符上下文中的 "English" 替换为 「English」
    text = re.sub(r'([一-鿿])"([^"]*?)"([一-鿿\s，。、；：])', r'\1「\2」\3', text)
    text = re.sub(r'([一-鿿])"([^"]*?)"', r'\1「\2」', text)
    text = re.sub(r'"([^"]*?)"([一-鿿])', r'「\1」\2', text)
    return text


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
            extract_tool="extract_intent_json",
            trace_logger=trace_logger,
        )
        return self._parse_response(result)

    def _parse_response(self, response: str) -> ConstraintsList:
        # 优先来自 extract_intent_json 工具的输出（已是合法 JSON）
        data = self._try_parse(response)
        if data is None:
            raise ValueError("未能从LLM响应中解析出约束列表")

        constraints = [
            Constraint(
                id=item.get("id", f"C{i + 1}"),
                description=item.get("description") or item.get("constraint", ""),
                category=item.get("category", "instruction_derived"),
            )
            for i, item in enumerate(data.get("constraints", []))
        ]

        if not constraints:
            raise ValueError("未能从LLM响应中解析出约束列表")

        return ConstraintsList(constraints=constraints)

    @staticmethod
    def _try_parse(text: str) -> dict | None:
        """多策略尝试解析 JSON"""
        raw = text.strip()

        # 1) 直接解析
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "constraints" in data:
                return data
        except json.JSONDecodeError:
            pass

        # 2) 从 markdown 代码块中提取
        match = re.search(r'```(?:json)?\s*\n(.*?)```', raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1).strip())
                if isinstance(data, dict) and "constraints" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # 3) 修复未转义引号后重试
        fixed = _fix_json(raw)
        try:
            data = json.loads(fixed)
            if isinstance(data, dict) and "constraints" in data:
                return data
        except json.JSONDecodeError:
            pass

        # 4) 从修复后的文本中提取代码块
        match = re.search(r'```(?:json)?\s*\n(.*?)```', fixed, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1).strip())
                if isinstance(data, dict) and "constraints" in data:
                    return data
            except json.JSONDecodeError:
                pass

        return None
