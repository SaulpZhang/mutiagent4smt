from __future__ import annotations

from core.schemas import SMTLibCode, SyntaxResult
from utils.smt_executor import SMTExecutor


class VerificationModule:
    """验证模块：使用Z3求解器执行和验证SMT-LIB V2代码"""

    def __init__(self, z3_path: str | None = None, timeout: int = 30) -> None:
        self.executor = SMTExecutor(z3_path=z3_path, timeout=timeout)

    def check_syntax(self, code: SMTLibCode) -> SyntaxResult:
        """检查SMT-LIB V2代码的语法正确性"""
        is_valid, errors = self.executor.check_syntax(code.code)
        return SyntaxResult(is_valid=is_valid, errors=errors)

    def execute(self, code: SMTLibCode) -> tuple[bool, str, float]:
        """执行SMT-LIB V2代码并返回结果"""
        return self.executor.execute(code.code)
