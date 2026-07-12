"""验证修复后的 SMT 代码是否能通过 Z3 执行"""
from __future__ import annotations

from utils.smt_executor import SMTExecutor

PARAMETERS = {
    "type": "object",
    "properties": {
        "patched_code": {
            "type": "string",
            "description": "修复后的完整 SMT-LIB V2 代码",
        },
        "fix_description": {
            "type": "string",
            "description": "修复内容的简要描述",
        },
    },
    "required": ["patched_code", "fix_description"],
}

_executor = SMTExecutor(timeout=15)


def execute(patched_code: str, fix_description: str) -> str:
    """验证修复后的代码"""
    try:
        is_exec, output, elapsed_ms = _executor.execute(patched_code)
    except Exception as e:
        return f"Z3执行异常: {e}"

    if not is_exec:
        return f"Z3语法错误:\n{output[:500]}"

    result_line = output.strip().split("\n")[0] if output else ""
    return f"Z3结果: {result_line} (耗时{elapsed_ms:.0f}ms)"
