from __future__ import annotations

from config import settings
from agent.llm_client import LLMClient
from agent.tool_agent import ToolAgent, ToolDef
from modules.agents.intent_agent import IntentUnderstandingAgent
from modules.agents.eval_agent import EvaluationAgent


class AgentBuilder:
    """Agent装配器：创建并配置所有Agent

    Agent 1: 意图理解 - 分析验证指令，生成约束列表
    Agent 2: 代码生成 - ToolAgent，LLM 自主选择编译器或 Z3 Python 生成 SMT 代码
    Agent 3: 评估 - 逐项评估代码是否满足约束
    """

    SYSTEM_PROMPTS = {
        "intent": (
            "你是一个IAM策略分析专家。你的任务是根据用户的验证指令，"
            "生成结构化的约束列表。请以JSON格式输出，包含constraints数组，"
            "每个约束包含id、description、category字段。"
        ),
        "eval": (
            "你是一个SMT-LIB V2代码评估专家。你的任务是根据约束列表逐项评估生成的代码。"
            "请以JSON格式输出，包含items数组（每项含constraint_id、status、reason）"
            "和all_satisfied字段。保持评估客观中立。"
        ),
    }

    def _build_client(self, model_name: str) -> LLMClient:
        actual_model = model_name or settings.common_model or settings.model_name
        return LLMClient(model_name=actual_model)

    def _build_client_no_thinking(self, model_name: str) -> LLMClient:
        """构建不带 thinking 模式的客户端（用于 ToolAgent ReAct 循环，
        DeepSeek thinking 模式要求回传 reasoning_content，与 LangGraph ReAct 不兼容）"""
        actual_model = model_name or settings.common_model or settings.model_name
        return LLMClient(
            model_name=actual_model,
            thinking=False,
            reasoning_effort="",
        )

    def build_intent_agent(self) -> IntentUnderstandingAgent:
        return IntentUnderstandingAgent(
            name="intent_understanding",
            system_prompt=self.SYSTEM_PROMPTS["intent"],
            llm_client=self._build_client(settings.agent_1_model),
        )

    def build_tool_code_gen_agent(self) -> ToolAgent:
        """构建 ToolAgent：LLM 自主选择 SMT 生成工具"""
        from modules.tools.smt_tools import TOOL_DEFINITIONS
        from modules.tools.smt_tools import (
            tool_build_smt_model,
            tool_build_smt_expr,
            tool_check_type_compatibility,
            tool_build_type_check_smt,
            tool_check_condition_semantics,
            tool_build_condition_constraint,
        )

        fn_map = {
            "build_smt_model": tool_build_smt_model,
            "build_smt_expr": tool_build_smt_expr,
            "check_type_compatibility": tool_check_type_compatibility,
            "build_type_check_smt": tool_build_type_check_smt,
            "check_condition_semantics": tool_check_condition_semantics,
            "build_condition_constraint": tool_build_condition_constraint,
        }

        tools = [
            ToolDef(
                name=td["name"],
                description=td["description"],
                fn=fn_map[td["name"]],
                parameters=td["parameters"],
            )
            for td in TOOL_DEFINITIONS
        ]

        return ToolAgent(
            name="code_gen_tools",
            llm_client=self._build_client_no_thinking(settings.agent_2_model),
            tools=tools,
            max_steps=20,
        )

    def build_eval_agent(self) -> EvaluationAgent:
        return EvaluationAgent(
            name="evaluation",
            system_prompt=self.SYSTEM_PROMPTS["eval"],
            llm_client=self._build_client(settings.agent_3_model),
        )
