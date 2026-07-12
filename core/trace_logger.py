from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class TraceLogger:
    """对话式日志记录器：每个 Agent 一个 JSON 文件，存放完整 trace

    日志路径: data/<run_id>/log/<case_id>/<agent_name>.json
    """

    def __init__(self, run_id: str, agent_name: str, case_id: str = "") -> None:
        if case_id:
            self.log_path = Path("data") / run_id / "log" / case_id / f"{agent_name}.json"
        else:
            self.log_path = Path("data") / run_id / "log" / f"{agent_name}.json"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {
            "agent": agent_name,
            "run_id": run_id,
            "case_id": case_id,
            "tools": [],
            "messages": [],
        }

    def set_tools(self, tools: list[dict]) -> None:
        """设置该 agent 的工具列表"""
        self._data["tools"] = tools

    def add_message(self, role: str, content: str | None = None,
                    tool_calls: list | None = None, tool_name: str | None = None,
                    tool_call_id: str | None = None) -> None:
        """添加一条消息

        role: system / user / assistant / tool
        content: 消息内容
        tool_calls: assistant 调用的工具列表
        tool_name: tool 消息对应的工具名
        tool_call_id: tool 消息对应的调用 ID
        """
        entry: dict = {"role": role}
        if content:
            entry["content"] = content
        if tool_calls:
            entry["tool_calls"] = tool_calls
        if tool_name:
            entry["name"] = tool_name
        if tool_call_id:
            entry["tool_call_id"] = tool_call_id
        self._data["messages"].append(entry)

    def flush(self) -> None:
        """写入 JSON 文件"""
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def log_message(self, role: str, content: str, step: int | None = None) -> None:
        """兼容旧接口"""
        self.add_message(role, content)

    def log_react_message(self, step: int, node: str, content: str) -> None:
        """兼容旧接口"""
        role = node.replace("LLM_prompt", "assistant").replace("tool_", "tool.")
        self.add_message(role, content)

    def log_separator(self, title: str) -> None:
        """兼容旧接口：不写入 JSON messages"""
        pass

    def log_verify_result(self, code: str, output: str, time_ms: float) -> None:
        """兼容旧接口"""
        self.add_message("verify", f"Z3: {output[:100]} (耗时{time_ms:.0f}ms)")
