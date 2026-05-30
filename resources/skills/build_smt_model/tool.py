from __future__ import annotations

from modules.tools.smt_tools import tool_build_smt_model as execute

PARAMETERS = {
    "type": "object",
    "properties": {
        "variables": {
            "type": "array",
            "description": "变量声明列表，每项含 name(变量名) 和 sort 或 type(类型:Bool/String/Int)",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "变量名"},
                    "sort": {"type": "string", "description": "类型: Bool/String/Int（可用 type 代替）"},
                },
            },
        },
        "assignments": {
            "type": "array",
            "description": "赋值断言列表，每项含 var(变量名)、type(赋值类型:bool/string/int/raw)、value(值)",
            "items": {
                "type": "object",
                "properties": {
                    "var": {"type": "string", "description": "变量名"},
                    "type": {"type": "string", "description": "赋值类型: bool/string/int/raw"},
                    "value": {"description": "值（bool类型用true/false，string类型不用加引号）"},
                },
            },
        },
        "constraints": {
            "type": "array",
            "description": "约束断言列表，每项为一个SMT表达式字符串，自动包装为(assert ...)",
            "items": {"type": "string"},
        },
        "define_funs": {
            "type": "array",
            "description": "函数定义列表（结构化），每项含 name、sort、body",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "sort": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
        "define_funs_raw": {"type": "string", "description": "原始 define-fun SMT 代码（如 build_type_check_smt 的输出）"},
        "check_sat": {"type": "boolean", "description": "是否添加(check-sat)，默认true"},
        "exit_": {"type": "boolean", "description": "是否添加(exit)，默认true"},
    },
}
