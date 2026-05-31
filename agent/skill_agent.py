from __future__ import annotations

import json
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

        # 对话式日志：记录初始 system + user
        if trace_logger:
            trace_logger.log_message("system", self.system_prompt)
            trace_logger.log_message("user", user_message)

        print(f"  [{self.name}] 启动 ReAct（最大 {self.max_steps} 步）")
        print(f"  ── ReAct Trace ──")
        collected: list = []
        seen_ids: set[int] = set()  # 以 id(msg) 去重，应对 LangGraph 流式事件结构
        react_step = 0

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

                    # 已单独记录的初始消息不再重复
                    if isinstance(msg, (SystemMessage, HumanMessage)):
                        continue

                    if node_name == "agent" and isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                args_str = json.dumps(tc["args"], ensure_ascii=False)[:300]
                                print(f"  [{react_step}] LLM → {tc['name']}({args_str})")
                            calls = ", ".join(f"{tc['name']}(...)" for tc in msg.tool_calls)
                            log_content = f"[tool_calls: {calls}]"
                            if msg.content and msg.content.strip():
                                log_content = msg.content.strip() + "\n" + log_content
                            if trace_logger:
                                trace_logger.log_message("assistant", log_content, step=react_step)
                        elif msg.content and msg.content.strip():
                            c = msg.content.strip()
                            print(f"  [{react_step}] LLM: {c}")
                            if trace_logger:
                                trace_logger.log_message("assistant", c, step=react_step)
                    elif node_name == "tools":
                        c = msg.content.strip() if msg.content else ""
                        if len(c) > 150:
                            print(f"  [{react_step}] 工具 {msg.name}: {len(c)} 字符")
                        else:
                            print(f"  [{react_step}] 工具 {msg.name}: {c}")
                        if trace_logger and c:
                            trace_logger.log_message(f"tool.{msg.name}", c, step=react_step)
            react_step += 1

        self._last_messages = collected
        result = self._extract_result(collected, extract_tool)
        print(f"  [{self.name}] 结束（{react_step} 步）")
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
