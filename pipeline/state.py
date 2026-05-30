from __future__ import annotations

from typing import Any, TypedDict

from core.schemas import (
    ConstraintsList,
    EvaluationResult,
    OutputResult,
    SMTLibCode,
    SyntaxResult,
    VerificationInput,
    VerificationResult,
)


class PipelineState(TypedDict):
    """LangGraph StateGraph 的状态定义

    每个字段表示流水线中各模块的输入/输出。
    None 表示该阶段尚未执行。
    """

    # 输入
    input_data: VerificationInput | None
    instruct_id: str
    account_id: str
    label: bool | None

    # Agent 1 输出
    constraints_list: ConstraintsList | None

    # Agent 2 输出
    smt_code: SMTLibCode | None
    syntax_result: SyntaxResult | None
    syntax_retry_count: int

    # Agent 3 输出
    evaluation_result: EvaluationResult | None

    # Output 输出
    output_result: OutputResult | None

    # Verification 输出
    verification_result: VerificationResult | None

    # 迭代控制
    iteration: int
    max_iterations: int
    max_syntax_retries: int
    regeneration_count: int  # 语法修复耗尽后的重生成次数

    # 错误
    error_message: str | None

    # 扩展字段
    extras: dict[str, Any]
