from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class VerificationInput(BaseModel):
    """输入模块的输出：一个验证指令与对应IAM配置的配对"""

    instruction: str = Field(description="自然语言验证指令")
    account_data: dict = Field(description="IAM配置数据")
    instruct_id: str = Field(default="", description="指令文件标识")
    account_id: str = Field(default="", description="账户标识")


class Constraint(BaseModel):
    """约束列表中的单个约束项"""

    id: str = Field(description="约束唯一标识")
    description: str = Field(description="约束内容的自然语言描述")
    category: str = Field(description="约束分类：instruction_derived 或 policy_derived")


class ConstraintsList(BaseModel):
    """智能体一（意图理解）的输出：结构化的约束列表"""

    constraints: list[Constraint] = Field(description="约束项列表")

    @property
    def count(self) -> int:
        return len(self.constraints)


class SMTLibCode(BaseModel):
    """智能体二（代码生成）的输出：生成的SMT-LIB V2代码"""

    code: str = Field(description="SMT-LIB V2代码内容")
    language: Literal["smt-lib-v2"] = "smt-lib-v2"


class SyntaxResult(BaseModel):
    """语法检查结果"""

    is_valid: bool = Field(description="语法是否正确")
    errors: list[str] = Field(default_factory=list, description="错误信息列表")


class EvaluationItem(BaseModel):
    """单条约束的评估结果"""

    constraint_id: str = Field(description="对应约束的ID")
    status: Literal["satisfied", "not_satisfied"] = Field(description="满足状态")
    reason: str | None = Field(default=None, description="判断理由")


class EvaluationResult(BaseModel):
    """智能体三（评估）的输出：完整的评估结果"""

    items: list[EvaluationItem] = Field(description="各约束项的评估结果")
    all_satisfied: bool = Field(description="是否所有约束都满足")
    summary: str = Field(default="", description="评估总结")

    @property
    def satisfied_count(self) -> int:
        return sum(1 for item in self.items if item.status == "satisfied")

    @property
    def not_satisfied_count(self) -> int:
        return sum(1 for item in self.items if item.status == "not_satisfied")


class OutputResult(BaseModel):
    """输出模块的结果"""

    code: SMTLibCode = Field(description="最终生成的SMT-LIB V2代码")
    evaluation: EvaluationResult = Field(description="最终评估结果")
    file_path: str | None = Field(default=None, description="输出文件路径")


class VerificationResult(BaseModel):
    """验证模块的结果"""

    is_executable: bool = Field(description="代码是否可执行")
    execution_output: str = Field(default="", description="Z3执行输出")
    execution_time_ms: float = Field(default=0.0, description="执行耗时(毫秒)")


class StageTiming(BaseModel):
    """单个阶段的耗时记录"""

    stage_name: str = Field(description="阶段名称")
    duration_ms: float = Field(default=0.0, description="耗时(毫秒)")
    start_time: str | None = Field(default=None, description="开始时间")
    end_time: str | None = Field(default=None, description="结束时间")


class ExperimentRecord(BaseModel):
    """单个实验用例的完整记录"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="记录唯一标识")
    run_id: str = Field(default="", description="实验运行编号，同一批运行的记录共享同一编号")
    instruct_id: str = Field(default="", description="指令标识")
    account_id: str = Field(default="", description="账户标识")
    instruction: str = Field(default="", description="验证指令原文")
    account_data: dict = Field(default_factory=dict, description="IAM配置数据")
    constraints_list: str | None = Field(default=None, description="约束列表(JSON)")
    constraint_text: str | None = Field(default=None, description="约束列表的JSON数组字符串，每项包含id、description、category字段")
    generated_code: str | None = Field(default=None, description="生成的SMT-LIB V2代码")
    syntax_valid: bool | None = Field(default=None, description="语法是否通过")
    syntax_error_info: str | None = Field(default=None, description="语法错误信息")
    code_execution_result: str | None = Field(default=None, description="Z3执行结果")
    evaluation_result: str | None = Field(default=None, description="评估结果(JSON)")
    all_satisfied: bool | None = Field(default=None, description="是否全部约束满足")
    satisfied_count: int = Field(default=0, description="满足的约束数量")
    total_constraint_count: int = Field(default=0, description="约束总数")
    label_match: bool | None = Field(default=None, description="Z3结果是否与基准标签一致")
    num_iterations: int = Field(default=0, description="总迭代次数")
    num_syntax_retries: int = Field(default=0, description="语法修正次数")
    label: bool | None = Field(default=None, description="基准标签")
    model_used: str = Field(default="", description="使用的模型")
    total_time_ms: float = Field(default=0.0, description="总耗时(毫秒)")
    stages: list[StageTiming] = Field(default_factory=list, description="各阶段耗时")
    status: Literal["success", "failed", "error"] = Field(default="success", description="处理状态")
    error_message: str | None = Field(default=None, description="错误信息")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="时间戳",
    )
