from __future__ import annotations

"""LangGraph StateGraph 流水线（单用例处理）

Agent 2 使用 ToolAgent（ReAct 模式），通过 smt_verify 自检语法，
无需外部语法修正节点。

流程:
   intent_agent → code_gen (ToolAgent ReAct)
                        │
                        ▼
                    evaluate
                        │
                ┌───────┴───────┐
                │ 全部满足         │ 存在不满足(未达上限)
                ▼                 ▼
             output          semantic_fix (ToolAgent 再次生成)
                │                 │
                ▼                 ▼
             verify          evaluate (loop)

说明：
- 本图处理单个用例，所有用例的遍历在 main.py 中完成
- 每个用例独立创建一个 PipelineState 实例
"""

from typing import Literal

from langgraph.graph import END, StateGraph

from pipeline.nodes import PipelineNodes
from pipeline.state import PipelineState


def decide_evaluation_route(state: PipelineState) -> Literal["semantic_fix", "output"]:
    """评估后的路由

    - 全部满足 → output
    - 存在不满足且未达上限 → semantic_fix
    - 存在不满足且达上限 → output
    """
    evaluation = state.get("evaluation_result")
    if evaluation is None:
        return "output"

    if evaluation.all_satisfied:
        return "output"

    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 10)

    if iteration >= max_iter:
        return "output"

    return "semantic_fix"


def build_case_pipeline(prompt_type: str = "default", run_id: str = "") -> StateGraph:
    """构建单用例处理的流水线"""
    nodes = PipelineNodes(prompt_type=prompt_type, run_id=run_id)

    workflow = StateGraph(PipelineState)

    # 注册所有节点
    workflow.add_node("intent_agent", nodes.intent_agent_node)
    workflow.add_node("code_gen", nodes.code_gen_node)
    workflow.add_node("semantic_fix", nodes.code_gen_node)
    workflow.add_node("evaluate", nodes.evaluate_node)
    workflow.add_node("output", nodes.output_node)
    workflow.add_node("verify", nodes.verify_node)

    # 设置入口
    workflow.set_entry_point("intent_agent")

    # intent_agent → code_gen (ToolAgent ReAct 生成)
    workflow.add_edge("intent_agent", "code_gen")

    # code_gen → evaluate（跳过语法检查，ToolAgent 已用 smt_verify 自检）
    workflow.add_edge("code_gen", "evaluate")

    # evaluate → 条件路由
    workflow.add_conditional_edges(
        "evaluate",
        decide_evaluation_route,
        {
            "semantic_fix": "semantic_fix",
            "output": "output",
        },
    )

    # semantic_fix → evaluate（ToolAgent 再次生成后直接评估）
    workflow.add_edge("semantic_fix", "evaluate")

    # output → verify
    workflow.add_edge("output", "verify")

    # verify → 结束
    workflow.add_edge("verify", END)

    return workflow


def compile_pipeline(prompt_type: str = "default", run_id: str = "") -> StateGraph:
    """编译并返回可执行的流水线"""
    workflow = build_case_pipeline(prompt_type=prompt_type, run_id=run_id)
    return workflow.compile()
