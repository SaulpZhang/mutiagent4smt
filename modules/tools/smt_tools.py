"""SMT-LIB V2 代码生成工具集

工具列表:
1. parse_iam_policy       — 自动执行，解析IAM配置
2. smt_declare_and_assign — IAM JSON → declare-const + assert 赋值
3. smt_verify             — Z3 语法检查
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


# ── 工具 ②: smt_declare_and_assign ──

def tool_smt_declare_and_assign(statements_json: str) -> str:
    """IAM JSON → declare-const + assert 赋值代码段。"""
    data = json.loads(statements_json)
    statements = data.get("statements", [])
    lines: list[str] = []

    for si, stmt in enumerate(statements):
        pfx = f"s{si + 1}"
        lines.append(f";; ── Statement {si + 1} ──")

        # Effect
        if stmt.get("Effect"):
            lines.append(f"(declare-const {pfx}_has_effect Bool)")
            lines.append(f"(declare-const {pfx}_effect_value String)")
            lines.append(f"(assert (= {pfx}_has_effect true))")
            lines.append(f"(assert (= {pfx}_effect_value {_smt_escape(stmt['Effect'])}))")

        # Action
        if stmt.get("Action"):
            lines.append(f"(declare-const {pfx}_has_action Bool)")
            lines.append(f"(declare-const {pfx}_action_value String)")
            actions = stmt["Action"]
            val = actions[0] if actions else ""
            lines.append(f"(assert (= {pfx}_has_action {'true' if val else 'false'}))")
            lines.append(f"(assert (= {pfx}_action_value {_smt_escape(val)}))")

        # Principal
        if stmt.get("Principal"):
            principal = stmt["Principal"]
            if principal:
                p_type = next(iter(principal.keys()))
                p_vals = principal[p_type]
                p_val = p_vals[0] if p_vals else ""
                lines.append(f"(declare-const {pfx}_has_principal Bool)")
                lines.append(f"(declare-const {pfx}_has_principal_type Bool)")
                lines.append(f"(declare-const {pfx}_principal_type String)")
                lines.append(f"(declare-const {pfx}_has_principal_value Bool)")
                lines.append(f"(declare-const {pfx}_principal_value String)")
                lines.append(f"(assert (= {pfx}_has_principal true))")
                lines.append(f"(assert (= {pfx}_has_principal_type true))")
                lines.append(f"(assert (= {pfx}_principal_type {_smt_escape(p_type)}))")
                lines.append(f"(assert (= {pfx}_has_principal_value true))")
                lines.append(f"(assert (= {pfx}_principal_value {_smt_escape(p_val)}))")
            else:
                lines.append(f"(declare-const {pfx}_has_principal Bool)")
                lines.append(f"(declare-const {pfx}_has_principal_type Bool)")
                lines.append(f"(declare-const {pfx}_has_principal_value Bool)")
                lines.append(f"(assert (= {pfx}_has_principal false))")
                lines.append(f"(assert (= {pfx}_has_principal_type false))")
                lines.append(f"(assert (= {pfx}_has_principal_value false))")

        # Condition
        cond_block = stmt.get("Condition", {})
        if cond_block:
            conds = _extract_conditions(stmt)
            cond_count = len(conds)
            lines.append(f"(declare-const {pfx}_has_condition Bool)")
            lines.append(f"(assert (= {pfx}_has_condition true))")
            for ci, (op, key, val) in enumerate(conds):
                cc = ci + 1
                lines.append(f"(declare-const {pfx}_cond_{cc}_operator String)")
                lines.append(f"(declare-const {pfx}_cond_{cc}_key String)")
                lines.append(f"(declare-const {pfx}_cond_{cc}_value String)")
                lines.append(f"(assert (= {pfx}_cond_{cc}_operator {_smt_escape(op)}))")
                lines.append(f"(assert (= {pfx}_cond_{cc}_key {_smt_escape(key)}))")
                lines.append(f"(assert (= {pfx}_cond_{cc}_value {_smt_escape(val)}))")
        elif "Condition" in stmt:
            lines.append(f"(declare-const {pfx}_has_condition Bool)")
            lines.append(f"(assert (= {pfx}_has_condition false))")

        lines.append("")

    return "\n".join(lines)


# ── 工具 ③: smt_verify ──

def tool_smt_verify(code: str) -> str:
    """检查 SMT 代码的语法正确性（含未定义常量检测）。"""
    from utils.smt_executor import SMTExecutor
    executor = SMTExecutor()
    is_executable, output, _ = executor.execute(code)

    # Z3 对未定义常量会当作自由变量处理并返回 sat，但输出中会包含 (error
    if "(error" in output.lower():
        return f"语法错误:\n{output[:500]}"

    if is_executable:
        if "sat" in output:
            return "语法正确，Z3 返回: sat"
        elif "unsat" in output:
            return f"语法正确，Z3 返回: unsat"
        return f"语法正确，Z3 返回: {output[:200]}"
    else:
        return f"语法错误:\n{output[:500]}"


# ── 工具注册元数据 ──

TOOL_DEFINITIONS = [
    {
        "name": "parse_iam_policy",
        "description": "解析IAM配置。入参 account_data 是原始配置字典。返回JSON包含 statements, is_mixed, sub_scenario。",
        "parameters": {
            "type": "object",
            "properties": {
                "account_data": {
                    "type": "object",
                    "description": "原始IAM配置字典（含 bucket_policy 或 trust_policy）",
                }
            },
            "required": ["account_data"],
        },
    },
    {
        "name": "smt_declare_and_assign",
        "description": "接收 parse_iam_policy 的输出JSON，生成declare-const变量声明和assert赋值，返回SMT变量声明+断言代码段。",
        "parameters": {
            "type": "object",
            "properties": {
                "statements_json": {
                    "type": "string",
                    "description": "parse_iam_policy 返回的 JSON 字符串",
                }
            },
            "required": ["statements_json"],
        },
    },
    {
        "name": "smt_verify",
        "description": "用Z3检查SMT代码的语法正确性。入参 code 是完整的SMT-LIB V2代码文本。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "完整的SMT-LIB V2代码文本"},
            },
            "required": ["code"],
        },
    },
]
