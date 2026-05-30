from __future__ import annotations

import json
import re

from agent.base import BaseAgent
from core.schemas import EvaluationItem, EvaluationResult
from modules.evaluation_module import strip_smt_comments


class EvaluationAgent(BaseAgent):
    """智能体三：语义评估

    持有 run_z3_check skill：在调用 LLM 前显式执行该 skill 运行 Z3，
    将 sat/unsat 结果注入 prompt，让 LLM 在评估时参考真实执行结果。
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

    async def run(self, **kwargs) -> EvaluationResult:
        prompt = kwargs.get("prompt", "")
        if not prompt:
            raise ValueError("缺少prompt参数")

        # 显式执行 run_z3_check skill，将 Z3 结果注入 prompt
        if "run_z3_check" in self._skills:
            smt_code = self._extract_smt_code(prompt)
            if smt_code:
                clean = strip_smt_comments(smt_code)
                z3_result = self._skills["run_z3_check"].fn(smt_code=clean)
                prompt = prompt + f"\n\n## Z3 预执行结果（由 run_z3_check skill 自动执行）\n{z3_result}"

        response = await self._chat(user_message=prompt, json_output=True)
        return self._parse_response(response)

    def _extract_smt_code(self, text: str) -> str | None:
        """从 prompt 中提取 SMT 代码块"""
        # 查找 {{smt_code}} 后的代码块
        match = re.search(r'SMT-LIB V2代码：\s*\n(.*?)(?=\n约束列表：|\Z)', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # 回退：查找 ```smt2 块
        match = re.search(r'```(?:smt2|lisp|smt)\s*\n(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

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
