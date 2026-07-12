from __future__ import annotations

from modules.tools.smt_tools import tool_check_type_compatibility as execute

PARAMETERS = {
    "type": "object",
    "properties": {
        "operator": {
            "type": "string",
            "description": "IAM条件操作符，如 numericequals、stringequals、dateequals、bool、ipaddress、null。支持multi-value前缀（如 forallvalues:stringequals）",
        },
        "condition_key": {
            "type": "string",
            "description": "IAM条件键，如 g:PrincipalAccount、g:SourceIp、g:CurrentTime、g:MFAPresent 等",
        },
    },
    "required": ["operator", "condition_key"],
}
