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


# ── 工具 ②: execute_z3_python ──

def tool_execute_z3_python(code: str) -> str:
    """执行 Z3 Python 代码并返回 SMT-LIB V2 代码。

    代码必须定义一个 solver 变量 (z3.Solver())。
    工具自动执行 solver.to_smt2() 导出标准 SMT-LIB V2。

    Returns:
        SMT-LIB V2 代码（含 check-sat / exit），或错误信息（以"错误："或"执行错误："开头）。
    """
    import io
    import time
    import traceback
    from contextlib import redirect_stderr, redirect_stdout

    # 预导入 Z3，注入 globals
    import z3 as _z3
    safe_globals = {k: getattr(_z3, k) for k in dir(_z3) if not k.startswith("_")}
    # 补充安全内置
    safe_globals.update({
        "True": True, "False": False, "None": None,
        "range": range, "len": len, "str": str, "int": int,
        "float": float, "bool": bool, "list": list, "dict": dict,
        "tuple": tuple, "set": set, "enumerate": enumerate, "zip": zip,
        "isinstance": isinstance, "type": type, "object": object,
        "print": print, "Exception": Exception,
        "sorted": sorted, "min": min, "max": max,
        "any": any, "all": all,
        "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
        "reversed": reversed, "map": map, "filter": filter,
        "__builtins__": {},
    })

    # 自动去掉 from z3 import *（已在 safe_globals 中预导入）
    clean_code = "\n".join(
        line for line in code.split("\n")
        if "from z3 import" not in line and "import z3" not in line
    )

    f_out = io.StringIO()
    f_err = io.StringIO()
    start = time.time()

    try:
        with redirect_stdout(f_out), redirect_stderr(f_err):
            exec(clean_code, safe_globals)

        solver = safe_globals.get("solver")
        if solver is None:
            return "错误：代码未定义 'solver' 变量（请添加 solver = Solver()）"

        smt = solver.to_smt2()
        if not smt.strip():
            return "错误：solver 为空（请添加断言到 solver）"

        smt += "\n(exit)\n"
        elapsed = time.time() - start
        stdout = f_out.getvalue().strip()
        extra_parts = []
        if stdout:
            extra_parts.append(f"; print输出: {stdout[:200]}")
        extra_parts.append(f"; Z3执行: {elapsed:.2f}s")
        smt += "\n".join(extra_parts)
        return smt
    except Exception as e:
        tb = traceback.format_exc()
        tb_lines = tb.split("\n")
        tb_short = "\n".join(tb_lines[-8:]) if len(tb_lines) > 8 else tb
        return f"执行错误：{e}\n{tb_short}"


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
        "name": "execute_z3_python",
        "description": "执行 Z3 Python 代码并返回 SMT-LIB V2。代码必须定义 solver = Solver() 并添加断言。成功后返回标准 SMT-LIB V2（含 check-sat/exit）。失败返回错误信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "完整的 Z3 Python 代码。代码内必须: from z3 import *; solver = Solver(); ...添加断言... ",
                }
            },
            "required": ["code"],
        },
    },
]
