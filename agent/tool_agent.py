"""ToolAgent: 代码生成专用 Agent，基于 SkillAgent + 代码生成特有逻辑

使用场景的 agent2.md 构建提示词：
- # System 分区 → 系统提示词（含工具描述）
- # User 分区 → 用户消息（含指令、配置、约束）
- 评估反馈通过 {{feedback_section}} 变量注入
"""

from __future__ import annotations

import json

from agent.skill_agent import SkillAgent
from core.schemas import EvaluationResult, SMTLibCode
from core.prompt_manager import PromptManager


class ToolAgent:
    """Agent 2: 代码生成 — SkillAgent + 代码生成特有逻辑"""

    def __init__(
        self,
        name: str,
        llm_client,
        skills: list,
        system_prompt: str,
        prompt_manager: PromptManager,
        max_steps: int = 20,
        prompt_key: str = "2",
    ) -> None:
        self.name = name
        self._agent = SkillAgent(name, llm_client, skills, system_prompt, max_steps)
        self.system_prompt = system_prompt
        self._prompt_manager = prompt_manager
        self.prompt_key = prompt_key

    async def run(
        self,
        prompt: str = "",
        constraints_json: str = "",
        account_data: dict | None = None,
        evaluation_feedback: EvaluationResult | None = None,
        original_code: str = "",
        trace_logger=None,
    ) -> SMTLibCode:
        """运行代码生成 ReAct 循环"""
        pm = self._prompt_manager

        # 构建反馈文本
        feedback_section = ""
        if evaluation_feedback:
            feedback_section = evaluation_feedback.model_dump_json(indent=2, ensure_ascii=False)

        # 从对应的 prompt 文件加载 user prompt
        _, user_content = pm.load_agent_prompt(
            self.prompt_key,
            feedback_section=feedback_section,
            instruction=prompt,
            account_data=(
                json.dumps(account_data, indent=2, ensure_ascii=False)
                if account_data
                else ""
            ),
            constraints_list=constraints_json,
            original_code=original_code,
        )

        # 执行 ReAct 循环
        result = await self._agent.run(
            user_message=user_content,
            extract_tool="extract_smt_code",
            trace_logger=trace_logger,
        )

        if not result:
            result = "(check-sat)\n(exit)"

        return SMTLibCode(code=result)

    def get_last_trace(self) -> str:
        return self._agent.get_last_trace()
