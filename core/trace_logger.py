from __future__ import annotations

from datetime import datetime
from pathlib import Path


class TraceLogger:
    """用例级日志记录器：每个attempt记录一个完整的log文件，按运行顺序追加"""

    def __init__(self, log_dir: str, instruct_id: str, attempt: int = 1) -> None:
        self.base_dir = Path(log_dir) / instruct_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.base_dir / f"{attempt:02d}_attempt.log"

    def _append(self, text: str) -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(text)

    def log(
        self,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        iteration: int = 1,
        extra: str = "",
    ) -> None:
        """记录一次LLM调用的完整输入输出，追加到当前attempt的log文件"""
        parts = [
            "=" * 60 + "\n",
            f"Agent: {agent_name}\n",
            f"Iteration: {iteration}\n",
            f"Time: {datetime.now().strftime('%H:%M:%S')}\n",
        ]
        if extra:
            parts.append(f"{extra}\n")
        parts.extend([
            "=" * 60 + "\n\n",
            "【System Prompt】\n",
            system_prompt + "\n\n",
            "【User Prompt】\n",
            user_prompt + "\n\n",
            "【LLM Response】\n",
            response + "\n",
            "=" * 60 + "\n\n",
        ])
        self._append("".join(parts))

    def log_syntax_result(
        self, code: str, syntax_valid: bool, errors: list[str], retry_count: int
    ) -> None:
        """记录语法检查结果，追加到当前attempt的log文件"""
        parts = [
            "-" * 40 + "\n",
            f"Syntax Check (retry {retry_count}): {'PASS' if syntax_valid else 'FAIL'}\n",
            "-" * 40 + "\n",
        ]
        if errors:
            parts.append("【Errors】\n")
            for err in errors:
                parts.append(f"  {err}\n")
        parts.append("\n")
        self._append("".join(parts))

    def log_verify_result(self, code: str, output: str, time_ms: float) -> None:
        """记录Z3验证结果，追加到当前attempt的log文件"""
        parts = [
            "=" * 60 + "\n",
            "Z3 Verification\n",
            f"Execution Time: {time_ms:.0f}ms\n",
            "=" * 60 + "\n\n",
            "【Code】\n",
            code + "\n\n",
            "【Output】\n",
            output + "\n",
            "=" * 60 + "\n",
        ]
        self._append("".join(parts))
