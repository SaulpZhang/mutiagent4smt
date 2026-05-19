"""SMT-LIB V2 代码生成工具集

工具列表:
1. parse_iam_policy   — 自动执行，解析IAM配置
2. execute_z3_python  — 执行 Z3 Python 代码并导出 SMT-LIB V2
"""

from __future__ import annotations

import json
from typing import Any

from core.schemas import ConstraintsList


# ── 操作符 / 键分类 ──

STRING_OPS = {
    "stringequals", "stringnotequals", "stringmatch", "stringmatchnot",
    "stringequalsignorecase", "stringequalsnot", "stringmatchnot",
    "stringstartwith", "stringendwith", "stringlike",
    "stringequalsifexists", "stringmatchifexists",
}

NUMERIC_OPS = {
    "numericequals", "numericnotequals", "numericgreaterthan",
    "numericlessthan", "numericgreaterthanequals", "numericlessthanequals",
    "numericequalsnot", "numberinrange",
    "numericgreaterthanifexists",
}

DATE_OPS = {
    "dateequals", "datenotequals", "dateless", "dategreater",
    "dategreaterorequals", "datelessorequals",
    "dategreaterthan", "datelessthan", "dategreaterthanequals", "datelessthanequals",
    "timeequals", "timenotequals", "timeless", "timegreater",
}

BOOL_OPS = {"bool"}

IP_OPS = {"ipaddress", "ipaddressnot", "ipaddressifexists"}

NULL_OPS = {"null"}

MULTI_VALUE_OPS = {
    "forallvalues:stringequals", "forallvalues:stringnotequals",
    "forallvalues:stringmatch", "forallvalues:stringmatchnot",
    "forallvalues:stringequalsnot",
    "foranyvalue:stringequals", "foranyvalue:stringnotequals",
    "foranyvalue:stringmatch", "foranyvalue:stringmatchnot",
    "foranyvalue:stringequalsnot",
}

STRING_KEYS = {
    "g:PrincipalType", "g:PrincipalAccount", "g:PrincipalUrn", "g:PrincipalOrgId",
    "g:PrincipalOrgPath", "g:EnterpriseProjectId",
    "g:UserName", "g:SourceIdentity", "g:RequestedRegion",
    "g:SourceVpc", "g:UserAgent", "g:Referer",
    "g:CalledVia", "g:CalledViaFirst", "g:CalledViaLast",
    "g:TagKeys",
    "ServiceAgency", "g:SourceIdentity",
}

NUMERIC_KEYS = {"g:MFAAge", "g:MfaAge"}

BOOL_KEYS = {
    "g:MFAPresent", "g:SecureTransport", "g:PrincipalIsRootUser",
    "g:ViaService", "g:MfaPresent", "g:mfaPresent",
}

DATE_KEYS = {"g:CurrentTime", "g:TokenIssueTime"}

IP_KEYS = {"g:SourceIp", "g:VpcSourceIp"}

STRING_KEY_PREFIXES = (
    "g:RequestTag/", "g:PrincipalTag/", "g:ResourceTag/",
)


# ── 通用工具函数 ──

def _smt_escape(val: str) -> str:
    return f'"{val}"'


def _count_conditions(cond_block: dict) -> int:
    count = 0
    for op, cond_data in cond_block.items():
        if isinstance(cond_data, dict):
            count += len(cond_data)
        elif isinstance(cond_data, list):
            count += 1
    return count


def _extract_conditions(stmt: dict) -> list[tuple[str, str, str]]:
    """从 Statement 的 Condition 块中提取 (operator, key, first_value)。"""
    result: list[tuple[str, str, str]] = []
    cond_block = stmt.get("Condition", {})
    for op, cond_data in cond_block.items():
        if isinstance(cond_data, dict):
            for key, vals in cond_data.items():
                if isinstance(vals, list) and vals:
                    result.append((op, key, str(vals[0])))
                else:
                    result.append((op, key, str(vals) if vals else ""))
        elif isinstance(cond_data, list):
            if cond_data:
                result.append((op, "", str(cond_data[0])))
            else:
                result.append((op, "", ""))
    return result


# ── 工具 ①: parse_iam_policy ──

def tool_parse_iam_policy(account_data: dict) -> str:
    """解析 IAM 配置，提取策略语句及账号上下文信息。"""
    sub_scenario = "bucket_policy" if "buckets" in account_data else "agency_trust_policy"

    raw_str = ""
    meta: dict = {}
    if "buckets" in account_data:
        bucket = account_data["buckets"]
        raw_str = bucket.get("bucket_policy", "{}")
        meta = {
            "account_id": account_data.get("account_id", ""),
            "bucket_name": bucket.get("bucket_name", ""),
        }
    elif "agencies" in account_data:
        agency = account_data["agencies"]
        raw_str = agency.get("trust_policy", "{}")
        meta = {
            "account_id": account_data.get("account_id", ""),
            "agency_name": agency.get("agency_name", ""),
            "agency_id": agency.get("agency_id", ""),
            "attached_policy_ids": agency.get("attached_policy_ids", []),
        }
    else:
        return json.dumps({"error": "无法识别的配置格式", "statements": []})

    policy = json.loads(raw_str) if isinstance(raw_str, str) else raw_str
    statements = policy.get("Statement", [])

    effects = [s.get("Effect", "") for s in statements]
    has_allow = any(e == "Allow" for e in effects)
    has_deny = any(e == "Deny" for e in effects)
    is_mixed = len(statements) > 1 and has_allow and has_deny

    clean = []
    for s in statements:
        clean.append({
            "Effect": s.get("Effect", ""),
            "Action": s.get("Action", []),
            "Principal": s.get("Principal", {}),
            "Condition": s.get("Condition", {}),
        })

    return json.dumps({
        "statements": clean,
        "statement_count": len(clean),
        "is_mixed": is_mixed,
        "sub_scenario": sub_scenario,
        "account_meta": meta,
    }, ensure_ascii=False)


# ── 工具 ②: build_smt_model ──

def tool_build_smt_model(
    variables: list | None = None,
    assignments: list | None = None,
    constraints: list | None = None,
    define_funs: list | None = None,
    check_sat: bool = True,
    exit_: bool = True,
) -> str:
    """从结构化描述生成语法正确的完整 SMT-LIB V2 程序。

    Python 处理所有格式细节（括号、引号、关键字），避免手写语法错误。
    当标准编译器不适用时，作为 execute_z3_python 的替代方案。

    Args:
        variables: 变量声明，如 [{"name": "x", "sort": "Bool"}, {"name": "y", "sort": "String"}]
        assignments: 赋值断言，如 [{"var": "x", "type": "bool", "value": true}, {"var": "y", "type": "string", "value": "hello"}]
            type 支持: "bool" / "string" / "int" / "raw"（原始SMT表达式）
        constraints: 约束断言列表，每项为 SMT 表达式字符串，自动包装为 (assert ...)
            如 ["x", "(=> x y)", "(or x y)"]
        define_funs: 函数定义，如 [{"name": "f", "sort": "Bool", "body": "x"}]
        check_sat: 是否添加 (check-sat)
        exit_: 是否添加 (exit)

    Returns:
        完整 SMT-LIB V2 代码，或错误信息
    """
    from modules.tools.smt_builder import (
        build_declarations, build_assignments, build_assertions,
        build_define_funs as _build_define_funs, assemble_program,
    )

    try:
        var_text = ""
        if variables:
            var_text = build_declarations(variables)

        assign_text = ""
        if assignments:
            assign_text = build_assignments(assignments)

        constraint_text = ""
        if constraints:
            constraint_text = build_assertions(constraints)

        define_text = ""
        if define_funs:
            define_text = _build_define_funs(define_funs)

        # 合并 assertions
        all_assertions = []
        for t in [assign_text, constraint_text]:
            if t.strip():
                all_assertions.append(t.strip())
        combined_assertions = "\n".join(all_assertions)

        return assemble_program(
            declarations=var_text,
            assertions=combined_assertions,
            define_funs=define_text,
            check_sat=check_sat,
            exit_=exit_,
        )
    except Exception as e:
        return f"错误：build_smt_model 生成失败 - {e}"


# ── 工具 ③: check_type_compatibility ──

def tool_check_type_compatibility(operator: str, condition_key: str) -> str:
    """检查IAM条件操作符与条件键的类型兼容性（同IAMCompiler的编译期检查）。

    使用IAMCompiler相同的分类逻辑：
    1. 将操作符归类到 numeric/string/date/bool/ip/null
    2. 将条件键归类到相同类型体系
    3. 如果类型不一致（且都不是null），返回 "false"
    4. 如果兼容或无法分类，返回 "true"

    重要：返回的 "false" 必须放入 build_smt_model 的 constraints 数组，
    不可作为 assignment 的 value。
    constraints 中的 "false" 被包装为 (assert false)，使 Z3 模型 UNSAT。

    Args:
        operator: IAM条件操作符，如 numericequals、stringequals、bool、ipaddress 等
        condition_key: IAM条件键，如 g:PrincipalAccount、g:SourceIp、g:CurrentTime 等

    Returns:
        "false"（类型不兼容→放入constraints→UNSAT）或 "true"（类型兼容）
    """
    op_lower = operator.lower().strip()

    # ── 操作符分类（同IAMCompiler._classify_operator） ──
    OP_CLASSES: dict[str, set[str]] = {
        "string": STRING_OPS,
        "numeric": NUMERIC_OPS,
        "date": DATE_OPS,
        "bool": BOOL_OPS,
        "ip": IP_OPS,
        "null": NULL_OPS,
    }
    op_type: str | None = None
    for cls_name, ops_set in OP_CLASSES.items():
        if op_lower in ops_set:
            op_type = cls_name
            break

    # Multi-value operator: "forallvalues:stringequals" → inner="stringequals"
    if op_type is None and ":" in op_lower:
        inner = op_lower.split(":", 1)[1]
        for cls_name, ops_set in OP_CLASSES.items():
            if inner in ops_set:
                op_type = cls_name
                break

    # ── 键分类（同IAMCompiler._classify_key） ──
    key_type: str | None = None
    for cls_name, key_set, prefixes in [
        ("string", STRING_KEYS, STRING_KEY_PREFIXES),
        ("numeric", NUMERIC_KEYS, ()),
        ("bool", BOOL_KEYS, ()),
        ("date", DATE_KEYS, ()),
        ("ip", IP_KEYS, ()),
    ]:
        if condition_key in key_set:
            key_type = cls_name
            break
        for p in prefixes:
            if condition_key.startswith(p):
                key_type = cls_name
                break

    # ── 判定不兼容 ──
    if op_type is not None and op_type != "null" and key_type is not None and op_type != key_type:
        return "false"
    return "true"


# ── 工具 ⑤: build_smt_expr ──

def tool_build_smt_expr(op: str, operands: list[str]) -> str:
    """构建 SMT-LIB 逻辑表达式，避免括号/关键字语法错误。

    Args:
        op: 逻辑操作符 — "and", "or", "not", "implies", "eq", "neq"
        operands: 操作数列表（"not" 只需一个）

    Returns:
        SMT 表达式字符串，如 "(and x y)"、"(=> a b)"
    """
    from modules.tools.smt_builder import build_expression
    try:
        return build_expression(op, operands)
    except Exception as e:
        return f"错误：build_smt_expr 生成失败 - {e}"


# ── 工具注册元数据 ──

TOOL_DEFINITIONS = [
    {
        "name": "check_type_compatibility",
        "description": "检查IAM条件操作符与条件键的类型兼容性（同IAMCompiler的编译期检查）。返回false或true。重要：返回的false必须放入build_smt_model的constraints数组（勿作为assignment value使用），constraints中的false被包装为(assert false)使Z3模型UNSAT。",
        "parameters": {
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "IAM条件操作符，如numericequals、stringequals、dateequals、bool、ipaddress、null。支持multi-value前缀（如forallvalues:stringequals）",
                },
                "condition_key": {
                    "type": "string",
                    "description": "IAM条件键，如g:PrincipalAccount、g:SourceIp、g:CurrentTime、g:MFAPresent等",
                },
            },
            "required": ["operator", "condition_key"],
        },
    },
    {
        "name": "build_smt_model",
        "description": "从结构化JSON描述生成语法正确的完整SMT-LIB V2程序。Python处理格式（括号、引号、关键字），避免手写SMT语法错误。入参包括variables(变量声明)、assignments(赋值)、constraints(约束表达式列表)、define_funs(函数定义)。需要生成自定义SMT代码时使用。",
        "parameters": {
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
                    "description": "约束断言列表，每项为一个SMT表达式字符串，自动包装为(assert ...)。需要手动写SMT表达式时使用",
                    "items": {"type": "string"},
                },
                "define_funs": {
                    "type": "array",
                    "description": "函数定义列表，每项含 name(函数名)、sort(返回类型)、body(函数体表达式)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "sort": {"type": "string"},
                            "body": {"type": "string"},
                        },
                    },
                },
                "check_sat": {
                    "type": "boolean",
                    "description": "是否添加(check-sat)，默认true",
                },
                "exit_": {
                    "type": "boolean",
                    "description": "是否添加(exit)，默认true",
                },
            },
        },
    },
    {
        "name": "build_smt_expr",
        "description": "构建单条 SMT-LIB 逻辑表达式（and/or/not/implies/eq/neq）。避免手写括号嵌套导致的语法错误。结果可嵌入 build_smt_model 的 constraints 中使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "op": {
                    "type": "string",
                    "enum": ["and", "or", "not", "implies", "eq", "neq"],
                    "description": "逻辑操作符: and(与), or(或), not(非), implies(蕴含), eq(相等), neq(不相等)",
                },
                "operands": {
                    "type": "array",
                    "description": "操作数列表，每个元素为变量名。not只需一个操作数，eq需要两个",
                    "items": {"type": "string"},
                },
            },
            "required": ["op", "operands"],
        },
    },
]
