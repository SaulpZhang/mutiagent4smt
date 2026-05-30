"""执行SMT-LIB V2代码并通过Z3求解器验证"""
from __future__ import annotations

from utils.smt_executor import SMTExecutor

PARAMETERS = {
    "type": "object",
    "properties": {
        "smt_code": {
            "type": "string",
            "description": "SMT-LIB V2代码",
        },
    },
    "required": ["smt_code"],
}

_executor = SMTExecutor(timeout=15)


def execute(smt_code: str) -> str:
    """通过Z3执行SMT代码，返回执行结果"""
    try:
        is_exec, output, elapsed_ms = _executor.execute(smt_code)
    except Exception as e:
        return f"Z3执行异常: {e}"

    if not is_exec:
        return f"Z3语法错误:\n{output[:500]}"

    result_line = output.strip().split("\n")[0] if output else ""
    return f"Z3结果: {result_line} (耗时{elapsed_ms:.0f}ms)"
