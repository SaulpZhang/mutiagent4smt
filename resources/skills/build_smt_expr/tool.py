from __future__ import annotations

from modules.tools.smt_tools import tool_build_smt_expr as execute

PARAMETERS = {
    "type": "object",
    "properties": {
        "op": {
            "type": "string",
            "enum": ["and", "or", "not", "implies", "eq", "neq"],
            "description": "逻辑操作符: and(与), or(或), not(非), implies(蕴含), eq(相等), neq(不相等)",
        },
        "operands": {
            "type": "array",
            "description": "操作数列表。not只需一个操作数，eq需要两个",
            "items": {"type": "string"},
        },
    },
    "required": ["op", "operands"],
}
