from __future__ import annotations

from pathlib import Path

from core.exceptions import CodeVError


class PromptManager:
    """Prompt模板管理器，从文件加载并渲染模板"""

    def __init__(self, template_dir: str | None = None) -> None:
        if template_dir is None:
            template_dir = str(Path(__file__).parent / "templates")
        self.template_dir = Path(template_dir)
        if not self.template_dir.exists():
            raise CodeVError(f"模板目录不存在: {template_dir}")

    def load(self, name: str, **variables: str) -> str:
        """加载模板文件并渲染变量

        Args:
            name: 模板文件名（不含路径）
            **variables: 要渲染的模板变量

        Returns:
            渲染后的完整文本
        """
        template_path = self.template_dir / name
        if not template_path.exists():
            available = [p.name for p in self.template_dir.glob("*.txt")]
            raise CodeVError(f"模板文件不存在: {name}，可用模板: {available}")

        content = template_path.read_text(encoding="utf-8")

        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            if placeholder in content:
                content = content.replace(placeholder, str(value))

        return content

    def list_templates(self) -> list[str]:
        """列出所有可用的模板文件"""
        return sorted(p.name for p in self.template_dir.glob("*.txt"))
