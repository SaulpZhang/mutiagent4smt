from __future__ import annotations

import json
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from agent.llm_client import LLMClient
from core.skills.base import SkillDef


def format_messages(messages: list, label: str) -> str:
    """将消息列表格式化为可读文本（用于 trace 日志和反馈注入）"""
    parts = [f"### {label} ###\n"]
    for i, m in enumerate(messages):
        role = type(m).__name__.replace("Message", "").lower()
        content = ""
        if isinstance(m, AIMessage) and m.tool_calls:
            calls = ", ".join(f"{tc['name']}(...)" for tc in m.tool_calls)
            content = f"[tool_calls: {calls}]"
            if m.content:
                content = m.content + "\n" + content
        elif isinstance(m, ToolMessage):
            c = m.content.strip()
            content = f"[tool_result] {c}"
        elif isinstance(m.content, str):
            content = m.content
        else:
            content = str(m.content)
        parts.append(f"[{i}][{role}]: {content}\n")
    return "".join(parts)


class SkillAgent:
    """基于 LangGraph create_react_agent 的通用 Skill 驱动 Agent

    通过 ReAct 循环让 LLM 自主调用 skill（工具），
    适用于任何需要工具调用能力的场景。
    """

    def __init__(
        self,
        name: str,
        llm_client: LLMClient,
        skills: list[SkillDef],
        system_prompt: str,
        max_steps: int = 20,
    ) -> None:
        self.name = name
        self.llm_client = llm_client
        self.skills = {s.name: s for s in skills}
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self._last_messages: list = []

    def _build_langchain_tool(self, skill: SkillDef) -> StructuredTool:
        """将单个 SkillDef 转为 LangChain StructuredTool"""
        import functools
        from pydantic import Field, create_model

        params = skill.parameters or {}
        props = params.get("properties", {})
        required = params.get("required", [])

        # 由 JSON Schema 通过 create_model 生成 Pydantic model
        fields = {}
        for pname, pdef in props.items():
            ptype = pdef.get("type", "string")
            pdesc = pdef.get("description", "")
            py_type = str if ptype != "boolean" else bool
            if pname in required:
                fields[pname] = (py_type, Field(description=pdesc))
            else:
                fields[pname] = (py_type, Field(default="", description=pdesc))

        ArgsModel = create_model(f"{skill.name}_args", **fields)

        @functools.wraps(skill.fn)
        def wrapped(**kwargs: Any) -> str:
            result = skill.fn(**kwargs)
            printed = str(result)
            if len(printed) > 200:
                print(f"    ✓ {skill.name} 返回 ({len(printed)} 字符)")
            else:
                print(f"    ✓ {skill.name} → {printed}")
            return str(result)

        return StructuredTool.from_function(
            name=skill.name,
            description=skill.description[:1024],
            func=wrapped,
            args_schema=ArgsModel,
        )

    def _build_langchain_tools(self) -> list[StructuredTool]:
        return [self._build_langchain_tool(s) for s in self.skills.values()]

    async def run(
        self,
        user_message: str,
        *,
        extract_tool: str | None = None,
        trace_logger: Any = None,
    ) -> str:
        """运行 ReAct 循环（对话式日志）

        Args:
            user_message: 用户提示词
            extract_tool: 若指定，从该工具的输出提取最终结果
                          （如 Agent 2 的 build_smt_model）
            trace_logger: 可选 TraceLogger，记录对话式日志

        Returns:
            最终响应文本（LLM 回复或工具输出）
        """
        lc_tools = self._build_langchain_tools()
        model = self.llm_client._get_model()
        model_with_tools = model.bind_tools(lc_tools)
        agent = create_react_agent(model_with_tools, lc_tools)

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_message),
        ]

        # 对话式日志：记录初始 system + user + tools
        if trace_logger:
            trace_logger.set_tools([
                {
                    "name": s.name,
                    "description": s.description[:200],
                    "parameters": s.parameters,
                }
                for s in self.skills.values()
            ])
            trace_logger.add_message("system", self.system_prompt)
            trace_logger.add_message("user", user_message)

        print(f"  [{self.name}] 启动 ReAct（最大 {self.max_steps} 步）")
        react_start = time.perf_counter()
        print(f"  ── ReAct Trace ──")
        print(f"  [0] SystemMessage: {self.system_prompt}")
        print(f"  [0] HumanMessage: {user_message}")
        collected: list = []
        seen_ids: set[int] = set()
        self._pending_tool_ids: list[str] = []
        react_step = 0
        llm_call_count = 0
        tool_call_count = 0

        async for event in agent.astream(
            {"messages": messages},
            {"recursion_limit": self.max_steps},
        ):
            for node_name, data in event.items():
                msgs = data.get("messages", [])
                for msg in msgs:
                    if id(msg) in seen_ids:
                        continue
                    seen_ids.add(id(msg))
                    collected.append(msg)

                    # 初始消息已单独记录
                    if isinstance(msg, (SystemMessage, HumanMessage)):
                        continue

                    if node_name == "agent" and isinstance(msg, AIMessage):
                        llm_call_count += 1
                        if msg.tool_calls:
                            tool_calls_data = []
                            for tc in msg.tool_calls:
                                tc_id = tc.get("id", f"call_{tc['name']}_{react_step}")
                                tool_calls_data.append({
                                    "id": tc_id,
                                    "name": tc["name"],
                                    "args": tc["args"],
                                })
                                args_str = json.dumps(tc["args"], ensure_ascii=False)
                                print(f"  [{react_step}] AIMessage[tool_calls]: {tc['name']}({args_str})")
                            if trace_logger:
                                trace_logger.add_message(
                                    "assistant",
                                    content=msg.content.strip() if msg.content and msg.content.strip() else None,
                                    tool_calls=tool_calls_data,
                                )
                                self._pending_tool_ids = [tc["id"] for tc in tool_calls_data]
                        elif msg.content and msg.content.strip():
                            c = msg.content.strip()
                            print(f"  [{react_step}] AIMessage: {c}")
                            if trace_logger:
                                trace_logger.add_message("assistant", c)
                    elif node_name == "tools":
                        tool_call_count += 1
                        c = msg.content.strip() if msg.content else ""
                        print(f"  [{react_step}] ToolMessage({msg.name}): {c}")
                        if trace_logger:
                            tool_call_id = getattr(msg, "tool_call_id", "")
                            if not tool_call_id and hasattr(self, "_pending_tool_ids") and self._pending_tool_ids:
                                tool_call_id = self._pending_tool_ids.pop(0)
                            trace_logger.add_message("tool", c, tool_name=msg.name, tool_call_id=tool_call_id)
            react_step += 1

        self._last_messages = collected
        if trace_logger:
            trace_logger.flush()
        result = self._extract_result(collected, extract_tool)
        react_elapsed = time.perf_counter() - react_start
        print(f"  [{self.name}] 结束 ({react_step} 步, {react_elapsed:.1f}s, LLM={llm_call_count}次, 工具={tool_call_count}次)")
        return result

    def _extract_result(self, messages: list, extract_tool: str | None = None) -> str:
        """从 ReAct 消息中提取最终结果"""
        if extract_tool:
            for msg in reversed(messages):
                name = getattr(msg, "name", "") if hasattr(msg, "name") else ""
                if name == extract_tool:
                    content = msg.content.strip() if msg.content else ""
                    if content:
                        return content

        # 回退：取最后一个有内容的 LLM 回复
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and msg.content.strip():
                if not getattr(msg, "tool_calls", None):
                    return msg.content.strip()
                # 有 tool_calls 但也有文本内容
                if msg.content.strip():
                    return msg.content.strip()

        return ""

    def get_last_trace(self) -> str:
        """获取格式化后的上一轮 ReAct trace（用于评估反馈注入）"""
        if not self._last_messages:
            return ""
        return format_messages(self._last_messages, "上一轮 ReAct")
