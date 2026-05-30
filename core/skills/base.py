from __future__ import annotations

from typing import Any, Callable


class SkillDef:
    """Skill 定义：标准化能力单元元数据

    每个 Skill 是一个独立、可复用的能力单元，包含：
    - name: 唯一标识符
    - description: LLM 调用时的自然语言描述（来自 skill.md）
    - fn: 实际执行的 Python 函数
    - parameters: JSON Schema 格式的参数定义
    """

    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable[..., Any],
        parameters: dict | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.fn = fn
        self.parameters = parameters or {"type": "object", "properties": {}}
