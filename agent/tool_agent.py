"""ToolAgent: 基于 LangGraph create_react_agent 的工具调用 Agent。

与 BaseAgent 不同，ToolAgent 将工具绑定到 LLM（bind_tools），
通过 LangGraph 的 ReAct 循环自动调度工具调用。

设计原则：
- 第一步 parse_iam_policy 自动执行（避免 LLM 理解偏差）
- 工具调用由 LangGraph ToolNode 处理（无需自定义解析）
- 最终答案直接输出 SMT-LIB V2 代码
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import Tool
from langgraph.prebuilt import create_react_agent

from agent.base import BaseAgent
from agent.llm_client import LLMClient
from core.schemas import SMTLibCode

_TEMPLATE_PATH = Path(__file__).parent.parent / "prompt" / "templates" / "tool_agent_system.txt"


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
        max_steps: int = 30,
    ) -> None:
        system_prompt = self._build_prompt(tools)
        super().__init__(name, system_prompt, llm_client)
        self.tools = {t.name: t for t in tools}
        self.max_steps = max_steps

    def _build_prompt(self, tools: list[ToolDef]) -> str:
        tool_lines = []
        for t in tools:
            props = t.parameters.get("properties", {})
            param_str = ", ".join(f"{n}({p.get('type','?')})" for n, p in props.items())
            tool_lines.append(f"- **{t.name}({param_str})**: {t.description}")
        tool_descriptions = "\n".join(tool_lines)

        flow_steps = []
        skip_names = {"parse_iam_policy"}
        step_num = 1
        for t in tools:
            if t.name in skip_names:
                continue
            if t.name == "smt_assemble":
                flow_steps.append(f"{step_num}. {t.name} — 传入 code_sections 或空列表自动收集")
            elif t.name == "smt_verify":
                flow_steps.append(f"{step_num}. {t.name} — 传入组装后的完整代码检查语法")
            elif t.name == "smt_validation_funcs":
                flow_steps.append(f"{step_num}. {t.name}")
            else:
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

        # ── 自动解析 policy ──
        print("  [ToolAgent] 自动执行: parse_iam_policy")
        statements_json = tool_parse_iam_policy(account_data)

        # ── 构建 LangChain Tools（带上下文注入） ──
        collected: dict[str, str] = {"statements_json": statements_json}
        lc_tools = self._build_langchain_tools(constraints_json, account_data, collected)

        # ── 获取 ChatOpenAI 模型并绑定工具 ──
        model = self.llm_client._get_model()
        model_with_tools = model.bind_tools(lc_tools)

        # ── 构建 ReAct Agent ──
        agent = create_react_agent(
            model_with_tools,
            lc_tools,
        )

        # ── 初始消息 ──
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=(
                f"## 任务\n\n{task}\n\n"
                f"## 约束列表\n```json\n{constraints_json}\n```\n\n"
                f"## 已解析的 Policy\n```json\n{statements_json}\n```"
            )),
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
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                args_str = json.dumps(tc["args"], ensure_ascii=False)
                                print(f"  [{react_step}] LLM → {tc['name']}({args_str[:300]})")
                        elif msg.content and msg.content.strip():
                            c = msg.content.strip()
                            print(f"  [{react_step}] LLM: {c[:200]}")
                    elif node_name == "tools":
                        c = msg.content.strip() if msg.content else ""
                        if len(c) > 150:
                            print(f"  [{react_step}] 工具 {msg.name}: {len(c)} 字符")
                        else:
                            print(f"  [{react_step}] 工具 {msg.name}: {c}")
            react_step += 1

        # ── 优先使用自动组装的代码（smt_assemble 已从 collected 收集） ──
        if collected.get("smt_assemble"):
            code = collected["smt_assemble"]
            print(f"  [ToolAgent] 使用 smt_assemble 组装代码 ({len(code)} 字符)")
        else:
            # fallback: 从 collected 手动组装
            sections_keys = ["smt_declare_variables", "smt_assert_config", "smt_validation_funcs",
                             "smt_contradiction_check", "smt_allow_deny_combine"]
            sections = [collected.get(k, "") for k in sections_keys if collected.get(k)]
            if sections:
                code = tool_smt_assemble(sections)
                print(f"  [ToolAgent] 自动组装代码 ({len(code)} 字符)")
            else:
                # 最终 fallback: 从 LLM 输出提取
                code = self._extract_final_code(collected_messages)
                print(f"  [ToolAgent] 从 LLM 输出提取代码 ({len(code)} 字符)")

        if not code or len(code.strip()) < 20:
            code = "(check-sat)\n(exit)"

        print(f"  ── ReAct 结束 ({react_step} 步) ──")
        return SMTLibCode(code=code)

    def _build_langchain_tools(
        self,
        constraints_json: str,
        account_data: dict,
        collected: dict[str, str],
    ) -> list[Tool]:
        """将 ToolDef 列表转为 LangChain Tool 列表，自动注入上下文参数。"""
        lc_tools = []

        for td in self.tools.values():
            if td.name == "parse_iam_policy":
                continue  # 已自动执行

            if td.name == "smt_assemble":
                lc_tools.append(self._make_assemble_tool(td, collected))
            elif td.name == "smt_verify":
                lc_tools.append(self._make_verify_tool(td))
            else:
                lc_tools.append(self._make_gen_tool(td, constraints_json, account_data, collected))

        return lc_tools

    def _make_gen_tool(
        self,
        td: ToolDef,
        constraints_json: str,
        account_data: dict,
        collected: dict[str, str],
    ) -> Tool:
        """创建一个自动注入上下文的生成工具。"""
        props = td.parameters.get("properties", {})

        def wrapped(statements_json: str = "", **kwargs: Any) -> str:
            # 自动注入上下文参数（覆写 LLM 传入的值）
            kwargs["statements_json"] = collected.get("statements_json", "")
            if "constraints_json" in props:
                kwargs["constraints_json"] = constraints_json
            if "account_data" in props:
                kwargs["account_data"] = account_data

            result = td.fn(**kwargs)
            collected[td.name] = result
            print(f"    ✓ {td.name}: {len(result)} 字符")
            return result

        return Tool.from_function(
            name=td.name,
            description=td.description,
            func=wrapped,
        )

    def _make_assemble_tool(self, td: ToolDef, collected: dict[str, str]) -> Tool:
        """创建组装工具：从 collected 收集代码段，忽略 LLM 传入的参数。"""
        def wrapped(code_sections: list | None = None, **kwargs: Any) -> str:
            sections = [
                collected.get(k, "")
                for k in ["smt_declare_variables", "smt_assert_config", "smt_validation_funcs",
                          "smt_contradiction_check", "smt_allow_deny_combine"]
                if collected.get(k)
            ]
            result = td.fn(sections)
            collected[td.name] = result
            print(f"    ✓ {td.name}: {len(result)} 字符 ({len(sections)} 段)")
            return result

        return Tool.from_function(
            name=td.name,
            description=td.description,
            func=wrapped,
        )

    def _make_verify_tool(self, td: ToolDef) -> Tool:
        """创建语法检查工具。"""
        def wrapped(code: str = "", **kwargs: Any) -> str:
            result = td.fn(code)
            print(f"    ✓ {td.name}: {len(code)} 字符 → {'通过' if 'valid' in result.lower() or 'ok' in result.lower() else result[:80]}")
            return result

        return Tool.from_function(
            name=td.name,
            description=td.description,
            func=wrapped,
        )

    def _extract_final_code(self, messages: list) -> str:
        """从消息历史中提取最终的 SMT 代码。"""
        import re

        # 从后往前找最后一条包含 SMT 代码的 AIMessage（非 tool_call）
        for msg in reversed(messages):
            if hasattr(msg, "content") and isinstance(msg.content, str) and msg.content:
                content = msg.content.strip()
                # 检查代码块
                m = re.search(r'```(?:smt2|lisp|smt|z3)?\s*\n(.*?)```', content, re.DOTALL)
                if m:
                    return m.group(1).strip()
                # 检查 SMT 关键字
                if sum(1 for kw in ["declare-const", "define-fun", "check-sat", "(exit", "(assert"] if kw in content) >= 2:
                    return content

        return ""

    def _chat(self, user_message: str, json_output: bool = False) -> str:
        raise NotImplementedError("ToolAgent uses LangGraph ReAct loop")


# ── 延迟导入以避免循环依赖 ──

def tool_parse_iam_policy(account_data: dict) -> str:
    from modules.tools.smt_tools import tool_parse_iam_policy as _fn
    return _fn(account_data)


def tool_smt_assemble(code_sections: list[str]) -> str:
    from modules.tools.smt_tools import tool_smt_assemble as _fn
    return _fn(code_sections)
