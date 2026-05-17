"""User-Defined Generator Manager for LLM-Managed generation mode.

Manages user-defined SMT code generators stored in the user_defined/ directory.
Each generator consists of:
  - spec.json: name, version, description, input/output format, usage
  - generator.py: Python implementation with a generate() function

Generators are initially empty and created/improved by LLM over time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agent.llm_client import LLMClient
from core.schemas import ConstraintsList, SMTLibCode


DISPATCH_SYSTEM_PROMPT = (
    "You are a dispatch router for SMT-LIB V2 code generators. "
    "Your job is to decide whether an existing user-defined generator "
    "can handle the given verification instruction.\n\n"
    "For each generator, consider:\n"
    "1. Does the instruction match the generator's description and intended use case?\n"
    "2. Does the instruction's input format match what the generator expects?\n\n"
    "Respond in JSON format with exactly these fields:\n"
    "- use_generator: boolean — whether any available generator should be used\n"
    "- generator_name: string or null — the name of the best-matching generator\n"
    "- confidence: float — confidence score 0.0 to 1.0\n"
    "- reason: string — brief explanation for your decision"
)


class UserDefinedGeneratorManager:
    """管理用户自定义的生成器（由LLM创建和改进）

    职责：
    1. 维护 user_defined/ 目录下的生成器索引和spec
    2. 通过LLM根据验证指令分发到合适的生成器
    3. 动态加载和执行生成器的Python代码
    """

    def __init__(self, base_dir: str | Path, llm_client: LLMClient) -> None:
        self.base_dir = Path(base_dir)
        self.llm_client = llm_client
        self._ensure_dirs()
        self._load_index()

    def _ensure_dirs(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "generators").mkdir(exist_ok=True)

    def _load_index(self) -> None:
        index_path = self.base_dir / "index.json"
        if index_path.exists():
            self.index: dict = json.loads(index_path.read_text())
        else:
            self.index = {"generators": []}
            self._save_index()

    def _save_index(self) -> None:
        index_path = self.base_dir / "index.json"
        index_path.write_text(json.dumps(self.index, indent=2, ensure_ascii=False))

    def list_generators(self) -> list[dict]:
        """列出所有已注册的生成器及其spec"""
        return self.index.get("generators", [])

    def _generator_name_exists(self, name: str) -> bool:
        return any(g.get("name") == name for g in self.list_generators())

    def _build_dispatch_user_message(self, instruction: str) -> str:
        """构建包含可用生成器列表和验证指令的用户消息"""
        generators = self.list_generators()

        if not generators:
            return (
                f"## Verification Instruction\n\n{instruction}\n\n"
                "## Decision\n\n(no generators available — respond with use_generator: false)"
            )

        lines = ["## Available Generators\n"]
        for g in generators:
            name = g.get("name", "unknown")
            ver = g.get("version", "1.0.0")
            desc = g.get("description", "")
            inp = json.dumps(g.get("input", {}), ensure_ascii=False)
            out = json.dumps(g.get("output", {}), ensure_ascii=False)
            examples = g.get("examples", [])
            lines.append(f"### {name} (v{ver})")
            lines.append(f"- Description: {desc}")
            lines.append(f"- Input: {inp}")
            lines.append(f"- Output: {out}")
            if examples:
                lines.append(f"- Examples: {'; '.join(examples[:3])}")
            lines.append("")

        lines.append("## Verification Instruction")
        lines.append("")
        lines.append(instruction)
        lines.append("")
        lines.append("## Decision")
        lines.append("")
        lines.append(
            "Based on the instruction and available generators above, respond in JSON:"
        )
        lines.append(
            '{"use_generator": true/false, "generator_name": "name or null", '
            '"confidence": 0.0-1.0, "reason": "..."}'
        )

        return "\n".join(lines)

    async def dispatch(self, instruction: str) -> tuple[str | None, str]:
        """根据验证指令分发到合适的生成器

        流程：
        1. 无可用生成器 -> 立即返回 (None, "no generators")
        2. 有生成器 -> LLM 判断是否使用以及使用哪个
        3. LLM 返回的 generator_name 做存在性验证

        Args:
            instruction: 验证指令文本

        Returns:
            (generator_name, reason)
            - generator_name: 匹配的生成器名称，None 表示不使用
            - reason: 分发决策的原因
        """
        if not self.list_generators():
            return None, "no generators available"

        user_message = self._build_dispatch_user_message(instruction)

        try:
            raw = await self.llm_client.chat(
                system_prompt=DISPATCH_SYSTEM_PROMPT,
                user_message=user_message,
                json_output=True,
            )
            data = json.loads(raw)
        except Exception:
            return None, "dispatch LLM returned invalid response"

        use_generator = data.get("use_generator", False)
        generator_name = data.get("generator_name")
        reason = data.get("reason", "")

        if not use_generator or not generator_name:
            return None, reason or "LLM decided not to use generator"

        # 验证 generator_name 存在于索引中（防止 LLM 幻觉）
        if not self._generator_name_exists(generator_name):
            return None, f"LLM hallucinated non-existent generator: '{generator_name}'"

        return generator_name, reason

    def get_generator_spec(self, name: str) -> dict | None:
        """加载指定生成器的 spec.json"""
        spec_path = self._get_generator_dir(name) / "spec.json"
        if spec_path.exists():
            return json.loads(spec_path.read_text())
        return None

    def _get_generator_dir(self, name: str) -> Path:
        return self.base_dir / "generators" / name

    def _to_smtlib_code(self, raw: Any) -> SMTLibCode:
        """将 generator 的输出规范化为 SMTLibCode

        支持的输入类型:
        - SMTLibCode: 直接返回
        - dict 且包含 "code" 键: 提取 code
        - 有 .code 属性的对象: 提取 code
        - str: 直接作为 code
        """
        if isinstance(raw, SMTLibCode):
            return raw
        if isinstance(raw, dict) and "code" in raw:
            return SMTLibCode(code=raw["code"])
        if hasattr(raw, "code"):
            return SMTLibCode(code=str(raw.code))
        if isinstance(raw, str):
            return SMTLibCode(code=raw)
        raise ValueError(
            f"Cannot convert generator result ({type(raw).__name__}) to SMTLibCode"
        )

    def load_generator_function(self, name: str) -> Callable:
        """动态加载生成器的 generate() 函数

        加载 generators/{name}/generator.py，执行 Python 代码，
        提取 generate(config, constraints) 函数，并包装返回值规范化为 SMTLibCode。

        Args:
            name: 生成器名称

        Returns:
            包装后的 generate(config, constraints) -> SMTLibCode 函数
        """
        gen_dir = self._get_generator_dir(name)
        code_path = gen_dir / "generator.py"

        if not code_path.exists():
            raise FileNotFoundError(
                f"Generator '{name}' has no generator.py at {code_path}"
            )

        code_text = code_path.read_text()
        namespace: dict[str, Any] = {}
        exec(code_text, namespace)

        if "generate" not in namespace:
            raise ValueError(
                f"Generator '{name}' must define a generate() function"
            )

        raw_generate = namespace["generate"]
        normalize = self._to_smtlib_code

        def wrapped(
            config: dict, constraints: ConstraintsList
        ) -> SMTLibCode:
            result = raw_generate(config, constraints)
            return normalize(result)

        return wrapped
