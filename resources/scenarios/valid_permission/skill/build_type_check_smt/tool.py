from __future__ import annotations

from modules.tools.smt_tools import tool_build_type_check_smt as execute

PARAMETERS = {
    "type": "object",
    "properties": {
        "operator": {
            "type": "string",
            "description": "IAM条件操作符，如 numericequals、stringequals、dateequals、bool、ipaddress 等",
        },
        "condition_key": {
            "type": "string",
            "description": "IAM条件键，如 g:PrincipalAccount、g:SourceIp、g:CurrentTime 等",
        },
        "prefix": {
            "type": "string",
            "description": "变量名前缀，如 's0_c0'（Statement 0 的 Condition 0）。默认 'type_ok'",
        },
    },
    "required": ["operator", "condition_key"],
}
