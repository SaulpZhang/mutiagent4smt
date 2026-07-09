from __future__ import annotations

from pathlib import Path

from config import settings
from agent.llm_client import LLMClient
from agent.tool_agent import ToolAgent
from core.prompt_manager import PromptManager
from core.skills.registry import SkillRegistry
from modules.agents.intent_agent import IntentUnderstandingAgent
from modules.agents.eval_agent import EvaluationAgent


class AgentBuilder:
    """Agent 装配器：根据场景加载 skill 和 prompt，装配 3 个 Agent

    - skill: 从 resources/scenarios/<scenario>/skill/ 加载
    - prompt: 从 resources/scenarios/<scenario>/prompt/agent{1,2,3}.md 加载
    """

    CODE_GEN_SKILL_NAMES = [
        "generate_smt_from_policy",
        "extract_smt_code",
        "check_type_compatibility",
        "check_condition_semantics",
    ]

    def __init__(self, scenario_name: str) -> None:
        self.scenario_name = scenario_name
        self.prompt_manager = PromptManager(scenario_name=scenario_name)
        self._registry = self._build_registry()
        self._registry.discover()

    def _build_registry(self) -> SkillRegistry:
        """构建 SkillRegistry，从场景 skill 目录加载"""
        skills_dir = (
            Path(__file__).parent.parent
            / "resources"
            / "scenarios"
            / self.scenario_name
            / "skill"
        )
        return SkillRegistry(skills_dir)

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

    def _render_tool_descriptions(self, skills: list) -> str:
        """生成工具描述文本（用于 agent2.md 的 {{tool_descriptions}}）"""
        lines = []
        for s in skills:
            props = s.parameters.get("properties", {})
            param_str = ", ".join(f"{n}({p.get('type', '?')})" for n, p in props.items())
            lines.append(f"- **{s.name}({param_str})**: {s.description}")
        return "\n".join(lines)

    def build_intent_agent(self) -> IntentUnderstandingAgent:
        skills = self._registry.get_skills([
            "parse_iam_config",
            "extract_intent_json",
        ])
        tool_descriptions = self._render_tool_descriptions(skills)
        system_prompt = self.prompt_manager.load_system_prompt(
            "1", tool_descriptions=tool_descriptions,
        )
        return IntentUnderstandingAgent(
            name="intent_understanding",
            system_prompt=system_prompt,
            llm_client=self._build_client(settings.agent_1_model),
            skills=skills,
            max_steps=20,
        )

    def build_tool_code_gen_agent(self) -> ToolAgent:
        skills = self._registry.get_skills(self.CODE_GEN_SKILL_NAMES)
        tool_descriptions = self._render_tool_descriptions(skills)
        system_prompt = self.prompt_manager.load_system_prompt(
            "2", tool_descriptions=tool_descriptions,
        )
        return ToolAgent(
            name="code_gen_tools",
            llm_client=self._build_client_no_thinking(settings.agent_2_model, temperature=0.0),
            skills=skills,
            system_prompt=system_prompt,
            prompt_manager=self.prompt_manager,
            max_steps=20,
        )

    CODE_FIX_SKILL_NAMES = [
        "apply_smt_fix",
        "extract_smt_code",
    ]

    def build_fix_agent(self) -> ToolAgent:
        skills = self._registry.get_skills(self.CODE_FIX_SKILL_NAMES)
        tool_descriptions = self._render_tool_descriptions(skills)
        system_prompt = self.prompt_manager.load_system_prompt(
            "fix", tool_descriptions=tool_descriptions,
        )
        return ToolAgent(
            name="code_fix",
            llm_client=self._build_client_no_thinking(settings.agent_2_model, temperature=0.0),
            skills=skills,
            system_prompt=system_prompt,
            prompt_manager=self.prompt_manager,
            max_steps=10,
            prompt_key="fix",
        )

    def build_eval_agent(self) -> EvaluationAgent:
        skills = self._registry.get_skills([
            "run_z3_check",
            "check_type_compatibility",
            "check_condition_semantics",
        ])
        tool_descriptions = self._render_tool_descriptions(skills)
        system_prompt = self.prompt_manager.load_system_prompt(
            "3", tool_descriptions=tool_descriptions,
        )
        return EvaluationAgent(
            name="evaluation",
            system_prompt=system_prompt,
            llm_client=self._build_client(settings.agent_3_model),
            skills=skills,
            max_steps=20,
        )
