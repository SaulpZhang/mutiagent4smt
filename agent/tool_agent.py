"""ToolAgent: 代码生成专用 Agent，基于 SkillAgent + 代码生成特有逻辑

与通用 SkillAgent 的区别：
1. 使用 code_generation.txt 构建用户消息（含规则、约束、IAM配置）
2. 评估反馈注入（regeneration_feedback.txt + 上一轮 ReAct trace）
3. 最终代码从 build_smt_model 工具输出提取
"""

from __future__ import annotations

import json

from agent.skill_agent import SkillAgent
from core.schemas import EvaluationResult, SMTLibCode


class ToolAgent:
    """Agent 2: 代码生成 — SkillAgent + 代码生成特有逻辑"""

    def __init__(
        self,
        name: str,
        llm_client,
        skills: list,
        system_prompt: str,
        max_steps: int = 20,
    ) -> None:
        self.name = name
        self._agent = SkillAgent(name, llm_client, skills, system_prompt, max_steps)
        self.system_prompt = system_prompt

    async def run(
        self,
        prompt: str = "",
        constraints_json: str = "",
        account_data: dict | None = None,
        evaluation_feedback: EvaluationResult | None = None,
        trace_logger=None,
    ) -> SMTLibCode:
        """运行代码生成 ReAct 循环"""
        from pathlib import Path
        from resources.prompt.manager import PromptManager

        pm = PromptManager()

        # 加载规则
        rules_path = pm.template_dir / "rule.txt"
        rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""

        # 构建用户消息
        user_content = pm.load(
            "code_generation.txt",
            instruction=prompt,
            account_data=json.dumps(account_data, indent=2, ensure_ascii=False) if account_data else "",
            constraints_list=constraints_json,
            rules=rules_text,
        )

        # 评估反馈注入
        if evaluation_feedback and self._agent._last_messages:
            feedback = evaluation_feedback
            unsatisfied = [it for it in feedback.items if it.status == "not_satisfied"]
            unsat_text = (
                "\n".join(
                    f"  - {it.constraint_id}: {it.reason}" for it in unsatisfied
                )
                if unsatisfied
                else "  无（全部满足）"
            )
            feedback_prompt = pm.load(
                "regeneration_feedback.txt",
                previous_react_trace=self._agent.get_last_trace(),
                satisfied_count=str(feedback.satisfied_count),
                total_count=str(len(feedback.items)),
                unsatisfied_details=unsat_text,
            )
            user_content = feedback_prompt + "\n\n" + user_content

        # 执行 ReAct 循环
        result = await self._agent.run(
            user_message=user_content,
            extract_tool="build_smt_model",
            trace_logger=trace_logger,
        )

        if not result:
            result = "(check-sat)\n(exit)"

        return SMTLibCode(code=result)

    def get_last_trace(self) -> str:
        return self._agent.get_last_trace()
