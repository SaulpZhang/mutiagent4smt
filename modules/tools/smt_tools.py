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


# ── 类型分类共享逻辑 ──

OP_CLASSES: dict[str, set[str]] = {
    "string": STRING_OPS,
    "numeric": NUMERIC_OPS,
    "date": DATE_OPS,
    "bool": BOOL_OPS,
    "ip": IP_OPS,
    "null": NULL_OPS,
}

KEY_CLASSIFIERS: list[tuple[str, set[str], tuple[str, ...]]] = [
    ("string", STRING_KEYS, STRING_KEY_PREFIXES),
    ("numeric", NUMERIC_KEYS, ()),
    ("bool", BOOL_KEYS, ()),
    ("date", DATE_KEYS, ()),
    ("ip", IP_KEYS, ()),
]


def _classify_operator(operator: str) -> str | None:
    """返回操作符的类型（string/numeric/date/bool/ip/null），无法分类返回 None。"""
    op_lower = operator.lower().strip()
    for cls_name, ops_set in OP_CLASSES.items():
        if op_lower in ops_set:
            return cls_name
    # Multi-value: "forallvalues:stringequals" → inner="stringequals"
    if ":" in op_lower:
        inner = op_lower.split(":", 1)[1]
        for cls_name, ops_set in OP_CLASSES.items():
            if inner in ops_set:
                return cls_name
    return None


def _classify_key(condition_key: str) -> str | None:
    """返回条件键的类型（string/numeric/bool/date/ip），无法分类返回 None。"""
    for cls_name, key_set, prefixes in KEY_CLASSIFIERS:
        if condition_key in key_set:
            return cls_name
        for p in prefixes:
            if condition_key.startswith(p):
                return cls_name
    return None


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
    define_funs_raw: str | None = None,
    check_sat: bool = True,
    exit_: bool = True,
) -> str:
    """从结构化描述生成语法正确的完整 SMT-LIB V2 程序。

    Python 处理所有格式细节（括号、引号、关键字），避免手写语法错误。
    当标准编译器不适用时，作为 execute_z3_python 的替代方案。

    支持两种 define-fun 注入方式：
    - define_funs: 结构化列表，自动构建 (define-fun ...) 语法
    - define_funs_raw: 原始 SMT 代码字符串（如 build_type_check_smt 的输出），直接注入

    Args:
        variables: 变量声明，如 [{"name": "x", "sort": "Bool"}, {"name": "y", "sort": "String"}]
        assignments: 赋值断言，如 [{"var": "x", "type": "bool", "value": true}, {"var": "y", "type": "string", "value": "hello"}]
            type 支持: "bool" / "string" / "int" / "raw"（原始SMT表达式）
        constraints: 约束断言列表，每项为 SMT 表达式字符串，自动包装为 (assert ...)
            如 ["x", "(=> x y)", "(or x y)"]
        define_funs: 函数定义，如 [{"name": "f", "sort": "Bool", "body": "x"}]
        define_funs_raw: 原始 define-fun SMT 代码（如 build_type_check_smt 的输出），直接注入
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

        define_raw_text = define_funs_raw or ""

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
            define_funs_raw=define_raw_text,
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
    op_type = _classify_operator(operator)
    key_type = _classify_key(condition_key)

    if op_type is not None and op_type != "null" and key_type is not None and op_type != key_type:
        return "false"
    return "true"


# ── 工具 ④: build_type_check_smt ──

def tool_build_type_check_smt(operator: str, condition_key: str, prefix: str = "type_ok") -> str:
    """生成类型兼容性检查的 SMT-LIB V2 define-fun 代码片段。

    生成三个 define-fun，显式编码操作符和条件键的类型分类：
      {prefix}_op_type — 操作符的类型 (String)
      {prefix}_key_type — 条件键的类型 (String)
      {prefix} — 类型兼容性结果 (Bool)

    评估器可以看到分类过程（如 op_type="string", key_type="string"），
    而非"硬编码"的值。

    生成的代码片段应传入 build_smt_model 的 define_funs 参数。

    Args:
        operator: IAM条件操作符
        condition_key: IAM条件键
        prefix: 变量名前缀，如 "s0_c0"、"s1_c0"

    Returns:
        SMT-LIB V2 define-fun 代码段（不含 declare-fun，define-fun 自带声明）
    """
    op_type = _classify_operator(operator)
    key_type = _classify_key(condition_key)

    # 若两者类型明确且不同 → 不兼容
    is_incompatible = (
        op_type is not None and op_type != "null"
        and key_type is not None and op_type != key_type
    )

    if op_type is not None:
        op_line = f'(define-fun {prefix}_op_type () String "{op_type}")'
    else:
        op_line = f"(define-fun {prefix}_op_type () String \"unknown\")"

    if key_type is not None:
        key_line = f'(define-fun {prefix}_key_type () String "{key_type}")'
    else:
        key_line = f"(define-fun {prefix}_key_type () String \"unknown\")"

    if op_type is None or key_type is None:
        # 无法分类 → 假设兼容
        type_line = f"(define-fun {prefix} () Bool true)"
    else:
        # 显式类型比较
        type_line = f"(define-fun {prefix} () Bool (= {prefix}_op_type {prefix}_key_type))"

    return f"{op_line}\n{key_line}\n{type_line}"


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


# ── 工具 ⑥: check_condition_semantics ──

def tool_check_condition_semantics(operator: str, condition_key: str, condition_value: str) -> str:
    """检查IAM条件语义是否矛盾。

    检测模式：
    - bool + ["false"] → 语义矛盾，必返回 "false"
    - bool + ["true", "false"] → 同时包含true/false覆盖所有可能，不矛盾
    - 其他模式可后续扩展

    condition_value 参数接受 JSON 数组字符串，代表 IAM 条件值的完整数组。
    工具内部处理 OR 语义：bool + ["true", "false"] 不是矛盾。

    Args:
        operator: IAM条件操作符
        condition_key: IAM条件键
        condition_value: 条件值数组（JSON格式字符串，如 '["false"]'、'["true","false"]'、'"true"'）

    Returns:
        "false"（语义矛盾→放入 constraints→UNSAT）或 "true"（语义正常）
    """
    op_lower = operator.lower().strip()

    # 尝试将 condition_value 解析为 JSON 数组
    try:
        parsed = json.loads(condition_value) if condition_value else ""
    except (json.JSONDecodeError, TypeError):
        parsed = condition_value

    if isinstance(parsed, list):
        str_vals = [str(v).lower().strip() for v in parsed]
        # IAM 条件值数组是 OR 关系：同时包含 true 和 false → 覆盖所有可能，不矛盾
        if "true" in str_vals and "false" in str_vals:
            return "true"
        val_lower = str_vals[0] if str_vals else ""
    else:
        val_lower = str(parsed).lower().strip() if parsed else ""

    if op_lower == "bool" and val_lower == "false":
        return "false"

    return "true"


# ── 工具 ⑦: build_condition_constraint ──

def tool_build_condition_constraint(operator: str, condition_value: str, var_name: str = "v") -> str:
    """生成条件值的 SMT 约束表达式。

    将 IAM 条件的值约束编码为 SMT 表达式，使 Z3 能检测条件间的矛盾。
    生成的表达式应放入 build_smt_model 的 constraints 数组。

    不同操作符的编码方式：
    - stringequals → (= v "value")
    - stringnotequals → (not (= v "value"))
    - numericequals → (= v 123)
    - numericnotequals → (not (= v 123))
    - numericgreaterthan → (> v 123)
    - numericlessthan → (< v 123)
    - numericgreaterthanequals → (>= v 123)
    - numericlessthanequals → (<= v 123)
    - bool → (= v true) 或 (= v false)
    - null → (= v "")
    - ipaddress, date* → 不编码（复杂语义）

    Args:
        operator: IAM条件操作符
        condition_value: 条件值（支持纯值或JSON数组格式，如 "5"、'["5"]'）
        var_name: SMT 变量名，默认 "v"

    Returns:
        SMT 约束表达式字符串，如 "(= v \"User\")"、"(> v 5)"
    """
    op_lower = operator.lower().strip()
    raw = condition_value.strip()

    if not raw:
        return "true"

    # 兼容 JSON 数组输入（如 '["2"]' → "2"、'["true","false"]' → "true"）
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            val = str(parsed[0]).strip() if parsed else ""
        else:
            val = str(parsed).strip()
    except (json.JSONDecodeError, TypeError):
        val = raw

    # Bool
    if op_lower == "bool":
        if val.lower() == "true":
            return f"(= {var_name} true)"
        elif val.lower() == "false":
            return f"(= {var_name} false)"

    # String equality operators
    if op_lower in {"stringequals", "stringequalsifexists"}:
        return f'(= {var_name} "{val}")'

    if op_lower in {"stringnotequals"}:
        return f'(not (= {var_name} "{val}"))'

    # Numeric operators
    try:
        int_val = int(val)
        if op_lower in {"numericequals", "numericequalsnot"}:
            return f"(= {var_name} {int_val})"
        if op_lower in {"numericnotequals"}:
            return f"(not (= {var_name} {int_val}))"
        if op_lower == "numericgreaterthan":
            return f"(> {var_name} {int_val})"
        if op_lower == "numericlessthan":
            return f"(< {var_name} {int_val})"
        if op_lower == "numericgreaterthanequals":
            return f"(>= {var_name} {int_val})"
        if op_lower == "numericlessthanequals":
            return f"(<= {var_name} {int_val})"
    except (ValueError, TypeError):
        pass

    # Null operator
    if op_lower == "null":
        if val.lower() == "true":
            return f"(= {var_name} \"\")"
        elif val.lower() == "false":
            return f'(not (= {var_name} ""))'

    # Fallback: string equality
    return f'(= {var_name} "{val}")'


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
        "name": "build_type_check_smt",
        "description": "生成类型兼容性检查的SMT-LIB V2代码片段（define-fun形式）。与check_type_compatibility不同：check_type_compatibility只返回true/false，build_type_check_smt返回显式编码操作符和键类型的SMT代码，评估器可以看到分类过程而非硬编码值。生成的SMT代码应传入build_smt_model的define_funs参数。",
        "parameters": {
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "IAM条件操作符，如numericequals、stringequals、dateequals、bool、ipaddress等",
                },
                "condition_key": {
                    "type": "string",
                    "description": "IAM条件键，如g:PrincipalAccount、g:SourceIp、g:CurrentTime等",
                },
                "prefix": {
                    "type": "string",
                    "description": "变量名前缀，如's0_c0'（Statement 0的Condition 0）。默认'type_ok'",
                },
            },
            "required": ["operator", "condition_key"],
        },
    },
    {
        "name": "build_smt_model",
        "description": "从结构化JSON描述生成语法正确的完整SMT-LIB V2程序。Python处理格式（括号、引号、关键字），避免手写SMT语法错误。入参包括variables(变量声明)、assignments(赋值)、constraints(约束表达式列表)、define_funs(结构化函数定义)、define_funs_raw(原始SMT define-fun代码如build_type_check_smt的输出)。需要生成自定义SMT代码时使用。",
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
                    "description": "函数定义列表（结构化），每项含 name(函数名)、sort(返回类型)、body(函数体表达式)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "sort": {"type": "string"},
                            "body": {"type": "string"},
                        },
                    },
                },
                "define_funs_raw": {
                    "type": "string",
                    "description": "原始 define-fun SMT 代码（如 build_type_check_smt 的输出），直接注入到程序的define-fun区域。适用于需要评估器看到分类逻辑的场景。与 define_funs 可同时使用。",
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
    {
        "name": "check_condition_semantics",
        "description": "检查IAM条件语义是否矛盾（如bool条件值为false）。返回false（语义矛盾→放入constraints→UNSAT）或true（语义正常）。condition_value接受JSON数组字符串（如'[\"false\"]'、'[\"true\",\"false\"]'），工具内部处理OR语义：同时包含true和false覆盖所有可能，不视为矛盾。与check_type_compatibility不同：check_type_compatibility检查操作符与键的类型兼容性，此工具检查条件值的语义正确性。",
        "parameters": {
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "IAM条件操作符，如bool、stringequals、numericequals等",
                },
                "condition_key": {
                    "type": "string",
                    "description": "IAM条件键，如g:SecureTransport、g:MfaAge等",
                },
                "condition_value": {
                    "type": "string",
                    "description": "条件值数组（JSON格式字符串，传完整数组，非单个值），如'[\"false\"]'、'[\"true\"]'、'[\"true\",\"false\"]'",
                },
            },
            "required": ["operator", "condition_key", "condition_value"],
        },
    },
    {
        "name": "build_condition_constraint",
        "description": "生成条件值的SMT约束表达式。将IAM条件的值约束编码为SMT表达式（如(= v \"User\")、(> v 5)），使Z3能检测条件间的矛盾。生成的表达式应放入build_smt_model的constraints数组。支持JSON数组格式的条件值（如'[\"2\"]'、'[\"false\"]'、'[\"true\",\"false\"]'），自动提取数组第一个元素。",
        "parameters": {
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "IAM条件操作符，如stringequals、numericequals、numericgreaterthan、bool等",
                },
                "condition_value": {
                    "type": "string",
                    "description": "条件值（支持纯值或JSON数组格式），如\"5\"、'[\"5\"]'、\"false\"、'[\"false\"]'、\"User\"",
                },
                "var_name": {
                    "type": "string",
                    "description": "SMT变量名，默认\"v\"。应与build_smt_model中声明的条件值变量名一致",
                },
            },
            "required": ["operator", "condition_value"],
        },
    },
]
