from __future__ import annotations

from config import settings
from agent.llm_client import LLMClient
from agent.tool_agent import ToolAgent, ToolDef
from modules.agents.intent_agent import IntentUnderstandingAgent
from modules.agents.code_gen_agent import CodeGenerationAgent
from modules.agents.eval_agent import EvaluationAgent


class AgentBuilder:
    """Agent装配器：创建并配置所有三个Agent

    每个Agent可独立配置不同的LLM模型（通过.env中的AGNET_1/2/3_MODEL指定）。
    如未指定，各Agent使用全局默认model_name。
    """

    SYSTEM_PROMPTS = {
        "intent": (
            "你是一个IAM策略分析专家。你的任务是根据用户的验证指令，"
            "生成结构化的约束列表。请以JSON格式输出，包含constraints数组，"
            "每个约束包含id、description、category字段。"
        ),
        "code_gen": (
            "你是一个SMT-LIB V2代码生成专家。你的任务是根据验证指令、华为云IAM配置和约束列表，"
            "生成可执行的SMT-LIB V2代码。代码必须使用SMT-LIB V2语法，"
            "包含变量定义、断言和check-sat命令。"
        ),
        "eval": (
            "你是一个SMT-LIB V2代码评估专家。你的任务是根据约束列表逐项评估生成的代码。"
            "请以JSON格式输出，包含items数组（每项含constraint_id、status、reason）"
            "和all_satisfied字段。保持评估客观中立。"
        ),
    }

    def _build_client(self, model_name: str) -> LLMClient:
        """为指定模型创建LLM客户端，如model_name为空则用common_model"""
        actual_model = model_name or settings.common_model or settings.model_name
        return LLMClient(model_name=actual_model)

    def build_intent_agent(self) -> IntentUnderstandingAgent:
        return IntentUnderstandingAgent(
            name="intent_understanding",
            system_prompt=self.SYSTEM_PROMPTS["intent"],
            llm_client=self._build_client(settings.agent_1_model),
        )

    def build_code_gen_agent(self) -> CodeGenerationAgent:
        return CodeGenerationAgent(
            name="code_generation",
            system_prompt=self.SYSTEM_PROMPTS["code_gen"],
            llm_client=self._build_client(settings.agent_2_model),
        )

    def build_eval_agent(self) -> EvaluationAgent:
        return EvaluationAgent(
            name="evaluation",
            system_prompt=self.SYSTEM_PROMPTS["eval"],
            llm_client=self._build_client(settings.agent_3_model),
        )

    def build_tool_code_gen_agent(self) -> ToolAgent:
        """为 gen_mode=2 构建工具增强的代码生成 Agent"""
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
