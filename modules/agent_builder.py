from __future__ import annotations

from pathlib import Path

from config import settings
from agent.llm_client import LLMClient
from agent.tool_agent import ToolAgent
from resources.skills.registry import SkillRegistry
from modules.agents.intent_agent import IntentUnderstandingAgent
from modules.agents.eval_agent import EvaluationAgent


class AgentBuilder:
    """Agent 装配器：通过 SkillRegistry 加载 skill，按场景装配 Agent

    Agent 1: 意图理解 — skills: [parse_iam_config]
    Agent 2: 代码生成 — skills: [build_smt_model, build_smt_expr, check_type_compatibility,
                                   build_type_check_smt, check_condition_semantics,
                                   build_condition_constraint]
    Agent 3: 语义评估 — skills: [run_z3_check]
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

    CODE_GEN_SKILL_NAMES = [
        "build_smt_model",
        "build_smt_expr",
        "check_type_compatibility",
        "build_type_check_smt",
        "check_condition_semantics",
        "build_condition_constraint",
    ]

    def __init__(self) -> None:
        self._registry = SkillRegistry()
        self._registry.discover()

    def _build_client(self, model_name: str) -> LLMClient:
        actual_model = model_name or settings.common_model or settings.model_name
        return LLMClient(model_name=actual_model)

    def _build_client_no_thinking(self, model_name: str, temperature: float | None = None) -> LLMClient:
        actual_model = model_name or settings.common_model or settings.model_name
        return LLMClient(
            model_name=actual_model,
            temperature=temperature,
            thinking=False,
            reasoning_effort="",
        )

    def _render_code_gen_prompt(self, skills: list) -> str:
        """渲染 Agent 2 系统提示词：工具描述替换到模板中"""
        tool_lines = []
        for s in skills:
            props = s.parameters.get("properties", {})
            param_str = ", ".join(f"{n}({p.get('type','?')})" for n, p in props.items())
            tool_lines.append(f"- **{s.name}({param_str})**: {s.description[:200]}")
        tool_descriptions = "\n".join(tool_lines)

        flow_steps = [f"{i+1}. {s.name}" for i, s in enumerate(skills)]
        recommended_flow = "\n".join(flow_steps)

        template_path = Path(__file__).parent.parent / "resources" / "prompt" / "templates" / "tool_agent_system.txt"
        template = template_path.read_text(encoding="utf-8")
        return template.replace("{{tool_descriptions}}", tool_descriptions).replace(
            "{{recommended_flow}}", recommended_flow
        )

    def build_intent_agent(self) -> IntentUnderstandingAgent:
        return IntentUnderstandingAgent(
            name="intent_understanding",
            system_prompt=self.SYSTEM_PROMPTS["intent"],
            llm_client=self._build_client(settings.agent_1_model),
            skills=self._registry.get_skills(["parse_iam_config"]),
        )

    def build_tool_code_gen_agent(self) -> ToolAgent:
        skills = self._registry.get_skills(self.CODE_GEN_SKILL_NAMES)
        system_prompt = self._render_code_gen_prompt(skills)
        return ToolAgent(
            name="code_gen_tools",
            llm_client=self._build_client_no_thinking(settings.agent_2_model, temperature=0.0),
            skills=skills,
            system_prompt=system_prompt,
            max_steps=20,
        )

    def build_eval_agent(self) -> EvaluationAgent:
        return EvaluationAgent(
            name="evaluation",
            system_prompt=self.SYSTEM_PROMPTS["eval"],
            llm_client=self._build_client(settings.agent_3_model),
            skills=self._registry.get_skills(["run_z3_check"]),
        )
