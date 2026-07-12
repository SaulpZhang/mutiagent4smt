from __future__ import annotations

from modules.tools.smt_tools import tool_check_condition_semantics as execute

PARAMETERS = {
    "type": "object",
    "properties": {
        "operator": {
            "type": "string",
            "description": "IAM条件操作符，如 bool、stringequals、numericequals 等",
        },
        "condition_key": {
            "type": "string",
            "description": "IAM条件键，如 g:SecureTransport、g:MfaAge 等",
        },
        "condition_value": {
            "type": "string",
            "description": "条件值数组（JSON格式字符串，传完整数组，非单个值），如 '[\"false\"]'、'[\"true\"]'、'[\"true\",\"false\"]'",
        },
    },
    "required": ["operator", "condition_key", "condition_value"],
}
