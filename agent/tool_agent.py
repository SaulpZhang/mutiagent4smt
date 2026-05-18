"""ToolAgent: 基于 LangGraph create_react_agent 的工具调用 Agent。

与 BaseAgent 不同，ToolAgent 将工具绑定到 LLM（bind_tools），
通过 LangGraph 的 ReAct 循环自动调度工具调用。

核心工具：
1. execute_z3_python — 执行 Z3 Python 代码并导出 SMT-LIB V2（由 LLM 调用）
parse_iam_policy 自动执行，不绑给 LLM。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent

from agent.base import BaseAgent
from agent.llm_client import LLMClient
from core.schemas import SMTLibCode
from prompt.manager import PromptManager

_TEMPLATE_PATH = Path(__file__).parent.parent / "prompt" / "templates" / "tool_agent_system.txt"


def _format_messages(messages: list, label: str) -> str:
    """将消息列表格式化为可读文本"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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
            content = f"[tool_result] {c[:200]}{'...' if len(c) > 200 else ''}"
        elif isinstance(m.content, str):
            content = m.content
        else:
            content = str(m.content)
        parts.append(f"[{i}][{role}]: {content}\n")
    return "".join(parts)


class ToolDef:
    """工具定义（轻量元数据，用于构建 LangChain Tool）"""

    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable,
        parameters: dict | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.fn = fn
        self.parameters = parameters or {"type": "object", "properties": {}}


class ToolAgent(BaseAgent):
    """基于 LangGraph create_react_agent 的工具增强 Agent。"""

    def __init__(
        self,
        name: str,
        llm_client: LLMClient,
        tools: list[ToolDef],
        max_steps: int = 10,
    ) -> None:
        system_prompt = self._build_prompt(tools)
        super().__init__(name, system_prompt, llm_client)
        self.tools = {t.name: t for t in tools}
        self.max_steps = max_steps

    def _build_prompt(self, tools: list[ToolDef]) -> str:
        skip_names = {"parse_iam_policy"}
        tool_lines = []
        for t in tools:
            if t.name in skip_names:
                continue
            props = t.parameters.get("properties", {})
            param_str = ", ".join(f"{n}({p.get('type','?')})" for n, p in props.items())
            tool_lines.append(f"- **{t.name}({param_str})**: {t.description}")
        tool_descriptions = "\n".join(tool_lines)

        flow_steps = []
        step_num = 1
        for t in tools:
            if t.name in skip_names:
                continue
            flow_steps.append(f"{step_num}. {t.name}")
            step_num += 1
        recommended_flow = "\n".join(flow_steps)

        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
        return template.replace("{{tool_descriptions}}", tool_descriptions).replace(
            "{{recommended_flow}}", recommended_flow
        )

    async def run(self, **kwargs) -> SMTLibCode:
        task = kwargs.get("prompt", "")
        constraints_json = kwargs.get("constraints_json", "")
        account_data = kwargs.get("account_data", {})
        trace_logger = kwargs.get("trace_logger", None)

        # ── 自动解析 policy（结果注入 prompt 供 LLM 参考） ──
        print("  [ToolAgent] 自动执行: parse_iam_policy")
        parsed_policy = tool_parse_iam_policy(account_data)

        # ── 构建 LangChain Tools ──
        lc_tools = self._build_langchain_tools()

        # ── 获取 ChatOpenAI 模型并绑定工具 ──
        model = self.llm_client._get_model()
        model_with_tools = model.bind_tools(lc_tools)

        # ── 构建 ReAct Agent ──
        agent = create_react_agent(
            model_with_tools,
            lc_tools,
        )

        # ── 初始消息 ──
        pm = PromptManager()
        user_content = pm.load(
            "code_generation.txt",
            instruction=task,
            account_data=json.dumps(account_data, indent=2, ensure_ascii=False),
            constraints_list=constraints_json,
            parsed_policy=parsed_policy,
        )

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_content),
        ]

        # ── 执行 ReAct 循环（stream 模式输出详细 trace） ──
        print(f"  [ToolAgent] 启动 LangGraph ReAct（最大 {self.max_steps} 步）")
        print(f"  ── ReAct Trace ──")
        collected_messages: list = []
        react_step = 0

        async for event in agent.astream(
            {"messages": messages},
            {"recursion_limit": self.max_steps},
        ):
            for node_name, data in event.items():
                msgs = data.get("messages", [])
                for msg in msgs:
                    collected_messages.append(msg)
                    if node_name == "agent":
                        if trace_logger and collected_messages:
                            prompt_msgs = collected_messages[:-1]
                            if prompt_msgs:
                                prompt_str = _format_messages(prompt_msgs, "Prompt_" + str(react_step))
                                trace_logger.log_react_message(react_step, "LLM_prompt", prompt_str)

                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                args_str = json.dumps(tc["args"], ensure_ascii=False)
                                line = f"  [{react_step}] LLM → {tc['name']}({args_str[:300]})"
                                print(line)
                                if trace_logger:
                                    trace_logger.log_react_message(react_step, "LLM_call", f"{tc['name']}({args_str})")
                        elif msg.content and msg.content.strip():
                            c = msg.content.strip()
                            print(f"  [{react_step}] LLM: {c[:200]}")
                            if trace_logger:
                                trace_logger.log_react_message(react_step, "LLM_response", c)
                    elif node_name == "tools":
                        c = msg.content.strip() if msg.content else ""
                        if len(c) > 150:
                            print(f"  [{react_step}] 工具 {msg.name}: {len(c)} 字符")
                        else:
                            print(f"  [{react_step}] 工具 {msg.name}: {c}")
                        if trace_logger and c:
                            trace_logger.log_react_message(react_step, f"tool_{msg.name}", c)
            react_step += 1

        # ── 从 execute_z3_python 工具结果中提取最终 SMT 代码 ──
        code = self._extract_final_code(collected_messages)

        if code and not code.startswith("错误"):
            print(f"  [ToolAgent] 最终代码 ({len(code)} 字符)")
        else:
            print(f"  [ToolAgent] 使用占位代码（{code[:100] if code else '空'}）")
            code = "(check-sat)\n(exit)"

        print(f"  ── ReAct 结束 ({react_step} 步) ──")
        return SMTLibCode(code=code)

    def _build_langchain_tools(self) -> list:
        """将 ToolDef 列表转为 LangChain StructuredTool 列表。

        parse_iam_policy 已自动执行，不绑定给 LLM。
        """
        lc_tools = []

        for td in self.tools.values():
            if td.name == "parse_iam_policy":
                continue  # 已自动执行
            lc_tools.append(self._make_gen_tool(td))

        return lc_tools

    def _make_gen_tool(self, td: ToolDef) -> StructuredTool:
        """通用工具包装器。"""
        import functools

        @functools.wraps(td.fn)
        def wrapped(**kwargs: Any) -> str:
            result = td.fn(**kwargs)
            print(f"    ✓ {td.name}: {len(result)} 字符")
            return result

        return StructuredTool.from_function(
            name=td.name,
            description=td.description,
            func=wrapped,
        )

    def _extract_final_code(self, messages: list) -> str:
        """从消息历史中提取最终的 SMT 代码。

        优先取 execute_z3_python 工具的成功输出（从最新往前找第一个成功），
        其次回退到 LLM 文本中的代码块。
        """
        import re

        # 优先：从最新往前找第一个成功的 execute_z3_python 结果
        for msg in reversed(messages):
            if hasattr(msg, "name") and getattr(msg, "name", "") == "execute_z3_python":
                content = msg.content.strip() if msg.content else ""
                if content and not content.startswith("错误") and not content.startswith("执行错误"):
                    return content

        # 回退：从 LLM 文本中提取代码块
        for msg in reversed(messages):
            if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
                content = msg.content.strip()
                m = re.search(r'```(?:smt2|lisp|smt|z3)?\s*\n(.*?)```', content, re.DOTALL)
                if m:
                    return m.group(1).strip()

        return ""

    def _chat(self, user_message: str, json_output: bool = False) -> str:
        raise NotImplementedError("ToolAgent uses LangGraph ReAct loop")


# ── 延迟导入以避免循环依赖 ──

def tool_parse_iam_policy(account_data: dict) -> str:
    from modules.tools.smt_tools import tool_parse_iam_policy as _fn
    return _fn(account_data)
