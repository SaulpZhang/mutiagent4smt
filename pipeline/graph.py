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
    instruct_id: str = "",
    ablation_mode: str = "full",
) -> StateGraph:
    """构建单用例处理的流水线

    ablation_mode:
        full    — intent_agent → code_gen → evaluate → (loop|output)
        no_eval — intent_agent → code_gen → output  (跳过 Agent3)
        gen_only — mock_intent → code_gen → output  (跳过 Agent1+Agent3)
    """
    nodes = PipelineNodes(
        scenario_name=scenario_name,
        run_id=run_id,
        instruct_id=instruct_id,
    )

    workflow = StateGraph(PipelineState)

    # 注册节点（所有模式共用）
    workflow.add_node("code_gen", nodes.code_gen_node)
    workflow.add_node("output", nodes.output_node)
    workflow.add_node("verify", nodes.verify_node)

    if ablation_mode in ("full", "no_eval"):
        workflow.add_node("intent_agent", nodes.intent_agent_node)

    if ablation_mode == "full":
        workflow.add_node("evaluate", nodes.evaluate_node)
    elif ablation_mode == "gen_only":
        workflow.add_node("mock_intent", nodes.mock_intent_node)

    # 路由
    if ablation_mode == "gen_only":
        workflow.set_entry_point("mock_intent")
        workflow.add_edge("mock_intent", "code_gen")
        workflow.add_edge("code_gen", "output")
    elif ablation_mode == "no_eval":
        workflow.set_entry_point("intent_agent")
        workflow.add_edge("intent_agent", "code_gen")
        workflow.add_edge("code_gen", "output")
    else:  # full
        workflow.set_entry_point("intent_agent")
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
    instruct_id: str = "",
    ablation_mode: str = "full",
) -> StateGraph:
    """编译并返回可执行的流水线"""
    workflow = build_case_pipeline(
        scenario_name=scenario_name,
        run_id=run_id,
        instruct_id=instruct_id,
        ablation_mode=ablation_mode,
    )
    return workflow.compile()
