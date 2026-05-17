from __future__ import annotations

from config import settings
from agent.llm_client import LLMClient
from agent.tool_agent import ToolAgent, ToolDef
from modules.agents.intent_agent import IntentUnderstandingAgent
from modules.agents.eval_agent import EvaluationAgent


class AgentBuilder:
    """Agent装配器：创建并配置三个Agent

    Agent 1: 意图理解 - 分析验证指令，生成约束列表
    Agent 2: 代码生成 - ToolAgent，通过 ReAct + 工具调用生成 SMT 代码
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

    def build_intent_agent(self) -> IntentUnderstandingAgent:
        return IntentUnderstandingAgent(
            name="intent_understanding",
            system_prompt=self.SYSTEM_PROMPTS["intent"],
            llm_client=self._build_client(settings.agent_1_model),
        )

    def build_eval_agent(self) -> EvaluationAgent:
        return EvaluationAgent(
            name="evaluation",
            system_prompt=self.SYSTEM_PROMPTS["eval"],
            llm_client=self._build_client(settings.agent_3_model),
        )

    def build_tool_code_gen_agent(self) -> ToolAgent:
        """构建 ToolAgent：通过 ReAct + 工具调用生成 SMT 代码"""
        from modules.tools.smt_tools import TOOL_DEFINITIONS
        from modules.tools.smt_tools import (
            tool_parse_iam_policy,
            tool_smt_declare_variables,
            tool_smt_assert_config,
            tool_smt_validation_funcs,
            tool_smt_contradiction_check,
            tool_smt_allow_deny_combine,
            tool_smt_assemble,
            tool_smt_verify,
        )

        fn_map = {
            "parse_iam_policy": tool_parse_iam_policy,
            "smt_declare_variables": tool_smt_declare_variables,
            "smt_assert_config": tool_smt_assert_config,
            "smt_validation_funcs": tool_smt_validation_funcs,
            "smt_contradiction_check": tool_smt_contradiction_check,
            "smt_allow_deny_combine": tool_smt_allow_deny_combine,
            "smt_assemble": tool_smt_assemble,
            "smt_verify": tool_smt_verify,
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
            llm_client=self._build_client(settings.agent_2_model),
            tools=tools,
        )
