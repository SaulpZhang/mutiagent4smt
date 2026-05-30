from __future__ import annotations

from datetime import datetime
from pathlib import Path


class TraceLogger:
    """对话式日志记录器：每个 Agent 一个文件，按运行顺序追加

    日志路径: data/<run_id>/log/<case_id>/<agent_name>.log
    """

    def __init__(self, run_id: str, agent_name: str, case_id: str = "") -> None:
        if case_id:
            self.log_path = Path("data") / run_id / "log" / case_id / f"{agent_name}.log"
        else:
            self.log_path = Path("data") / run_id / "log" / f"{agent_name}.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_header(agent_name, run_id)

    def _write_header(self, agent_name: str, run_id: str) -> None:
        self._append(
            f"{'=' * 60}\n"
            f"  Agent: {agent_name}  |  Run: {run_id}\n"
            f"{'=' * 60}\n\n"
        )

    def _append(self, text: str) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(text)

    def log_message(self, role: str, content: str, step: int | None = None) -> None:
        """记录一条对话消息

        role: system / user / assistant / tool.<name>
        """
        ts = datetime.now().strftime("%H:%M:%S")
        step_str = f" · step {step}" if step is not None else ""
        self._append(f"[{ts}] [{role}]{step_str}\n{content}\n\n")

    def log_react_message(self, step: int, node: str, content: str) -> None:
        """兼容旧接口，内部转为 log_message"""
        role = node.replace("LLM_prompt", "assistant").replace("tool_", "tool.")
        self.log_message(role, content, step=step)

    def log_separator(self, title: str) -> None:
        """记录分隔线（用于区分迭代轮次）"""
        self._append(f"\n{'─' * 40}\n  {title}\n{'─' * 40}\n\n")

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
