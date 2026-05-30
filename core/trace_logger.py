from __future__ import annotations

from datetime import datetime
from pathlib import Path


class TraceLogger:
    """ReAct 日志记录器：每个 Agent 一个文件，按运行顺序追加

    日志路径: data/<run_id>/log/<agent_name>.log
    """

    def __init__(self, run_id: str, agent_name: str) -> None:
        self.log_path = Path("data") / run_id / "log" / f"{agent_name}.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, text: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(text)

    def log(
        self,
        system_prompt: str,
        user_prompt: str,
        response: str,
        iteration: int = 1,
        extra: str = "",
    ) -> None:
        """记录一次LLM调用的完整输入输出"""
        parts = [
            "=" * 60 + "\n",
            f"Iteration: {iteration}\n",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
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

    def log_react_message(self, step: int, node: str, content: str) -> None:
        """记录 ReAct 循环中的单步消息"""
        parts = [
            f"── Step {step} [{node}] ──\n",
            content,
            "\n\n",
        ]
        self._append("".join(parts))

    def log_verify_result(self, code: str, output: str, time_ms: float) -> None:
        """记录Z3验证结果"""
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
