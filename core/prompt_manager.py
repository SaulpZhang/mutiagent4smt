from __future__ import annotations

from pathlib import Path

from core.exceptions import CodeVError


class PromptManager:
    """Prompt 管理器：加载场景对应的 agent prompt

    从 resources/scenarios/<scenario_name>/prompt/<agent>/ 加载 system.md 和 user.md，
    填充 {{variables}} 后返回。
    """

    def __init__(self, scenario_name: str) -> None:
        self.scenario_name = scenario_name
        self._prompt_dir = (
            Path(__file__).parent.parent / "resources" / "scenarios" / scenario_name / "prompt"
        )
        if not self._prompt_dir.exists():
            raise CodeVError(
                f"Scenario prompt directory not found: {self._prompt_dir}"
            )

    _AGENT_DIRS = {
        "1": "intent",
        "agent1": "intent",
        "intent": "intent",
        "2": "gen_code",
        "agent2": "gen_code",
        "gen_code": "gen_code",
        "3": "eval",
        "agent3": "eval",
        "eval": "eval",
        "fix": "fix_code",
    }

    def load_agent_prompt(
        self, agent_key: str, **variables: str
    ) -> tuple[str, str]:
        """加载指定 Agent 的 system.md 和 user.md

        Returns:
            (system_prompt, user_prompt) 元组
        """
        dir_name = self._AGENT_DIRS.get(agent_key)
        if not dir_name:
            raise CodeVError(
                f"Unknown agent_key: {agent_key}. "
                f"Use: {set(self._AGENT_DIRS.keys())}"
            )
        prompt_dir = self._prompt_dir / dir_name
        if not prompt_dir.exists():
            available = [p.name for p in self._prompt_dir.iterdir() if p.is_dir()]
            raise CodeVError(
                f"Prompt directory not found: {dir_name} "
                f"(scenario={self.scenario_name}). "
                f"Available: {available}"
            )

        system_file = prompt_dir / "system.md"
        user_file = prompt_dir / "user.md"

        system = system_file.read_text(encoding="utf-8").strip() if system_file.exists() else ""
        user = user_file.read_text(encoding="utf-8").strip() if user_file.exists() else ""

        if not user:
            raise CodeVError(
                f"Missing user.md in prompt directory "
                f"(scenario={self.scenario_name}, agent={dir_name})"
            )

        system = self._fill_vars(system, variables)
        user = self._fill_vars(user, variables)

        return system.strip(), user.strip()

    def _fill_vars(self, text: str, variables: dict) -> str:
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text

    def load_system_prompt(self, agent_key: str, **variables: str) -> str:
        system, _ = self.load_agent_prompt(agent_key, **variables)
        return system

    def load_user_prompt(self, agent_key: str, **variables: str) -> str:
        _, user = self.load_agent_prompt(agent_key, **variables)
        return user
