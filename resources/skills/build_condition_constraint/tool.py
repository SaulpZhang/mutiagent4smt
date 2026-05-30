from __future__ import annotations

from modules.tools.smt_tools import tool_build_condition_constraint as execute

PARAMETERS = {
    "type": "object",
    "properties": {
        "operator": {
            "type": "string",
            "description": "IAM条件操作符，如 stringequals、numericequals、numericgreaterthan、bool 等",
        },
        "condition_value": {
            "type": "string",
            "description": "条件值字符串，如 \"5\"、\"false\"、\"User\"、\"prefix*suffix\"",
        },
        "var_name": {
            "type": "string",
            "description": "SMT变量名，默认 \"v\"。应与 build_smt_model 中声明的条件值变量名一致",
        },
    },
    "required": ["operator", "condition_value"],
}
