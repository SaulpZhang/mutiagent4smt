from __future__ import annotations

import json
import re

from agent.skill_agent import SkillAgent
from core.schemas import EvaluationItem, EvaluationResult
from modules.evaluation_module import strip_smt_comments


class EvaluationAgent:
    """智能体三：语义评估（ReAct）

    通过 ReAct 循环自主调用工具（run_z3_check 等）分析 SMT 代码。
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

    async def run(self, **kwargs) -> EvaluationResult:
        prompt = kwargs.get("prompt", "")
        trace_logger = kwargs.get("trace_logger")
        if not prompt:
            raise ValueError("缺少prompt参数")

        result = await self._agent.run(
            user_message=prompt,
            trace_logger=trace_logger,
        )
        return self._parse_response(result)

    def _parse_response(self, response: str) -> EvaluationResult:
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
                constraint_id=cid, status=status, reason=reason,
            ))

        if not items:
            all_sat = data.get("all_satisfied", data.get("all_satisfied", False))
            if isinstance(all_sat, str):
                all_sat = all_sat.lower() == "true"
            summary = data.get("summary", data.get("evaluation", ""))
            items.append(EvaluationItem(
                constraint_id="C1",
                status="satisfied" if all_sat else "not_satisfied",
                reason=summary,
            ))

        all_satisfied = all(item.status == "satisfied" for item in items)
        summary = data.get("summary", data.get("conclusion", ""))
        return EvaluationResult(items=items, all_satisfied=all_satisfied, summary=summary)

    def _extract_json(self, text: str) -> dict:
        # 先尝试从 markdown 代码块中提取 JSON
        match = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and ("items" in data or "all_satisfied" in data):
                    return data
            except json.JSONDecodeError:
                pass

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
