from __future__ import annotations

import importlib.util
from pathlib import Path

from core.skills.base import SkillDef


class SkillRegistry:
    """Skill 注册中心：从场景 skill 目录自动发现 skill

    每个 skill 是一个子目录，包含:
    - skill.md: LLM 可读的描述文档
    - tool.py: 实现文件，必须导出 execute() 函数和 PARAMETERS 字典
    """

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        self._skills_dir = Path(skills_dir) if skills_dir else Path(__file__).parent
        self._skills: dict[str, SkillDef] = {}

    def discover(self) -> dict[str, SkillDef]:
        """扫描 skill 子目录，自动注册所有 skill"""
        if not self._skills_dir.exists():
            return self._skills
        for entry in sorted(self._skills_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
                continue
            self._load_skill(entry)
        return self._skills

    def _load_skill(self, skill_dir: Path) -> None:
        name = skill_dir.name
        md_file = skill_dir / "skill.md"
        tool_file = skill_dir / "tool.py"
        if not md_file.exists() or not tool_file.exists():
            return

        description = md_file.read_text(encoding="utf-8").strip()

        try:
            spec = importlib.util.spec_from_file_location(f"skills_{name}", tool_file)
            if spec is None or spec.loader is None:
                return
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"  [SkillRegistry] 加载 '{name}' 失败: {e}")
            return

        if not hasattr(module, "execute"):
            print(f"  [SkillRegistry] '{name}' 缺少 execute() 函数")
            return

        params = getattr(module, "PARAMETERS", {"type": "object", "properties": {}})
        self._skills[name] = SkillDef(
            name=name,
            description=description,
            fn=module.execute,
            parameters=params,
        )

    def register(self, skill: SkillDef) -> None:
        """手动注册一个 skill"""
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillDef:
        if name not in self._skills:
            raise KeyError(f"Skill '{name}' 未注册，可用: {self.list_skills()}")
        return self._skills[name]

    def get_skills(self, names: list[str]) -> list[SkillDef]:
        """批量获取 skill，按 names 顺序返回"""
        return [self.get(n) for n in names]

    def list_skills(self) -> list[str]:
        return sorted(self._skills.keys())
