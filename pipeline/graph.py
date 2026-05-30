from __future__ import annotations

"""LangGraph StateGraph 流水线（单用例处理）

Agent 2 (ToolAgent) 通过 ReAct 循环自主选择工具生成 SMT 代码。
当语义评估不通过时，自动进入修正循环（带评估反馈重新生成）。

流程:
   intent_agent → code_gen (ToolAgent) → evaluate
       ↕ (evaluation_feedback loop, max_iterations 次)
       └── output → verify
"""

from langgraph.graph import END, StateGraph

from pipeline.nodes import PipelineNodes
from pipeline.state import PipelineState


def decide_evaluation_route(state: PipelineState) -> str:
    """评估路由决策：评估未通过且未超限则重试，否则输出"""
    evaluation = state.get("evaluation_result")
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if state.get("error_message"):
        return "output"

    if evaluation and not evaluation.all_satisfied and iteration < max_iterations:
        return "code_gen"  # 带评估反馈重新生成

    return "output"


def build_case_pipeline(
    scenario_name: str = "valid_permission",
    run_id: str = "",
) -> StateGraph:
    """构建单用例处理的流水线"""
    nodes = PipelineNodes(
        scenario_name=scenario_name,
        run_id=run_id,
    )

    workflow = StateGraph(PipelineState)

    # 注册所有节点
    workflow.add_node("intent_agent", nodes.intent_agent_node)
    workflow.add_node("code_gen", nodes.code_gen_node)
    workflow.add_node("evaluate", nodes.evaluate_node)
    workflow.add_node("output", nodes.output_node)
    workflow.add_node("verify", nodes.verify_node)

    # 设置入口
    workflow.set_entry_point("intent_agent")

    # 流水线
    workflow.add_edge("intent_agent", "code_gen")
    workflow.add_edge("code_gen", "evaluate")
    workflow.add_conditional_edges(
        "evaluate",
        decide_evaluation_route,
        {"code_gen": "code_gen", "output": "output"},
    )
    workflow.add_edge("output", "verify")
    workflow.add_edge("verify", END)

    return workflow


def compile_pipeline(
    scenario_name: str = "valid_permission",
    run_id: str = "",
) -> StateGraph:
    """编译并返回可执行的流水线"""
    workflow = build_case_pipeline(
        scenario_name=scenario_name,
        run_id=run_id,
    )
    return workflow.compile()
