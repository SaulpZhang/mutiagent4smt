from __future__ import annotations

import re
from pathlib import Path

from core.exceptions import CodeVError


class PromptManager:
    """Prompt 管理器：加载场景对应的 agent prompt（MD 格式）

    从 resources/scenarios/<scenario_name>/prompt/ 加载 agent{1,2,3}.md，
    解析其中的 # System 和 # User 分区，填充 {{variables}} 后返回。

    MD 文件格式示例：
    ```markdown
    # System

    系统提示词内容...

    # User

    用户提示词内容...
    ```
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

    _AGENT_FILES = {
        "1": "intent.md",
        "agent1": "intent.md",
        "intent": "intent.md",
        "2": "gen_code.md",
        "agent2": "gen_code.md",
        "gen_code": "gen_code.md",
        "3": "eval.md",
        "agent3": "eval.md",
        "eval": "eval.md",
    }

    def load_agent_prompt(
        self, agent_key: str, **variables: str
    ) -> tuple[str, str]:
        """加载并解析指定 Agent 的 prompt 文件

        Args:
            agent_key: "1"/"agent1"/"intent" | "2"/"agent2"/"gen_code" | "3"/"agent3"/"eval"
            **variables: 要填充的模板变量

        Returns:
            (system_prompt, user_prompt) 元组
        """
        filename = self._AGENT_FILES.get(agent_key)
        if not filename:
            raise CodeVError(
                f"Unknown agent_key: {agent_key}. "
                f"Use: {set(self._AGENT_FILES.keys())}"
            )
        filepath = self._prompt_dir / filename
        if not filepath.exists():
            available = [p.name for p in self._prompt_dir.glob("agent*.md")]
            raise CodeVError(
                f"Prompt file not found: {filename} "
                f"(scenario={self.scenario_name}). "
                f"Available: {available}"
            )

        content = filepath.read_text(encoding="utf-8")
        system, user = self._parse_md_sections(content)

        system = self._fill_vars(system, variables)
        user = self._fill_vars(user, variables)

        return system.strip(), user.strip()

    def _parse_md_sections(self, content: str) -> tuple[str, str]:
        """解析 MD 文件中的 # System 和 # User 分区"""
        system_match = re.search(
            r"^#\s+System\s*\n(.*?)(?=^#\s|\Z)", content, re.MULTILINE | re.DOTALL
        )
        user_match = re.search(
            r"^#\s+User\s*\n(.*?)(?=^#\s|\Z)", content, re.MULTILINE | re.DOTALL
        )
        system = system_match.group(1).strip() if system_match else ""
        user = user_match.group(1).strip() if user_match else ""
        if not user:
            raise CodeVError(
                f"Missing '# User' section in agent prompt "
                f"(scenario={self.scenario_name})"
            )
        return system, user

    def _fill_vars(self, text: str, variables: dict) -> str:
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text

    def load_system_prompt(self, agent_key: str, **variables: str) -> str:
        """只加载 # System 分区"""
        system, _ = self.load_agent_prompt(agent_key, **variables)
        return system

    def load_user_prompt(self, agent_key: str, **variables: str) -> str:
        """只加载 # User 分区"""
        _, user = self.load_agent_prompt(agent_key, **variables)
        return user
