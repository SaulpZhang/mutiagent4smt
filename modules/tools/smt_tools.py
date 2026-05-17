"""SMT-LIB V2 代码生成工具集（供 gen_mode=2 ToolAgent 调用）

每个工具封装一个 SMT 生成步骤：
1. parse_iam_policy       — 解析 IAM 配置，提取策略语句
2. smt_declare_variables  — 生成变量声明
3. smt_assert_config      — 生成配置值断言
4. smt_validation_funcs   — 生成验证函数
5. smt_contradiction_check — 检测条件矛盾
6. smt_allow_deny_combine  — 生成 Allow+Deny 组合逻辑
7. smt_assemble           — 组装最终代码
"""

from __future__ import annotations

import json
from typing import Any

from core.schemas import ConstraintsList

# ── 操作符 / 键分类（复用 builtin_valid_permission 的常量） ──

STRING_OPS = {
    "stringequals", "stringnotequals", "stringmatch", "stringmatchnot",
    "stringequalsignorecase", "stringequalsnot", "stringmatchnot",
    "stringstartwith", "stringendwith", "stringlike",
    "stringequalsifexists", "stringmatchifexists",
}

NUMERIC_OPS = {
    "numericequals", "numericnotequals", "numericgreaterthan",
    "numericlessthan", "numericgreaterthanorequals", "numericlessthanequals",
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


# ── 工具函数 ──

def tool_parse_iam_policy(account_data: dict) -> str:
    """解析 IAM 配置，提取策略语句。

    从 account_data 中提取 bucket_policy 或 trust_policy JSON 字符串，
    解析 Statement 数组，返回包含 statements, is_mixed, sub_scenario 的 JSON。
    """
    sub_scenario = "bucket_policy" if "buckets" in account_data else "agency_trust_policy"

    raw_str = ""
    if "buckets" in account_data:
        raw_str = account_data["buckets"].get("bucket_policy", "{}")
    elif "agencies" in account_data:
        raw_str = account_data["agencies"].get("trust_policy", "{}")
    else:
        return json.dumps({"error": "无法识别的配置格式", "statements": []})

    policy = json.loads(raw_str) if isinstance(raw_str, str) else raw_str
    statements = policy.get("Statement", [])

    effects = [s.get("Effect", "") for s in statements]
    has_allow = any(e == "Allow" for e in effects)
    has_deny = any(e == "Deny" for e in effects)
    is_mixed = len(statements) > 1 and has_allow and has_deny

    # 简化 statements 为可序列化格式
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
    }, ensure_ascii=False)


def _smt_escape(val: str) -> str:
    return f'"{val}"'


def tool_smt_declare_variables(statements_json: str) -> str:
    """为每个 Statement 生成 declare-const 变量声明。

    statements_json: tool_parse_iam_policy 的返回（JSON 字符串）
    返回: SMT-LIB V2 变量声明代码段
    """
    data = json.loads(statements_json)
    statements = data.get("statements", [])
    lines: list[str] = []

    for si, stmt in enumerate(statements):
        pfx = f"s{si + 1}"
        lines.append(f";; ── Statement {si + 1} variables ──")

        if "Effect" in stmt and stmt["Effect"]:
            lines.append(f"(declare-const {pfx}_has_effect Bool)")
            lines.append(f"(declare-const {pfx}_effect_value String)")

        if "Action" in stmt and stmt["Action"]:
            lines.append(f"(declare-const {pfx}_has_action Bool)")
            lines.append(f"(declare-const {pfx}_action_value String)")

        if "Principal" in stmt and stmt["Principal"]:
            lines.append(f"(declare-const {pfx}_has_principal_type Bool)")
            lines.append(f"(declare-const {pfx}_principal_type String)")
            lines.append(f"(declare-const {pfx}_has_principal_value Bool)")
            lines.append(f"(declare-const {pfx}_principal_value String)")

        cond_block = stmt.get("Condition", {})
        if cond_block:
            cond_count = _count_conditions(cond_block)
            lines.append(f"(declare-const {pfx}_has_condition Bool)")
            for ci in range(cond_count):
                cc = ci + 1
                lines.append(f"(declare-const {pfx}_cond_{cc}_operator String)")
                lines.append(f"(declare-const {pfx}_cond_{cc}_key String)")
                lines.append(f"(declare-const {pfx}_cond_{cc}_value String)")
        elif "Condition" in stmt:
            # 空 Condition {}
            lines.append(f"(declare-const {pfx}_has_condition Bool)")

        lines.append("")

    result = "\n".join(lines)
    return result if result else "; (no statements to declare)"


def _count_conditions(cond_block: dict) -> int:
    count = 0
    for op, cond_data in cond_block.items():
        if isinstance(cond_data, dict):
            count += len(cond_data)
        elif isinstance(cond_data, list):
            count += 1
    return count


def _extract_conditions(stmt: dict) -> list[tuple[str, str, str]]:
    """Extract (operator, key, first_value) from a Statement's Condition block."""
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


def tool_smt_assert_config(statements_json: str) -> str:
    """从配置值生成 assert 断言。

    statements_json: tool_parse_iam_policy 的返回
    返回: SMT-LIB V2 断言代码段
    """
    data = json.loads(statements_json)
    statements = data.get("statements", [])
    lines: list[str] = []

    for si, stmt in enumerate(statements):
        pfx = f"s{si + 1}"
        lines.append(f";; ── Statement {si + 1} assertions ──")

        if "Effect" in stmt and stmt["Effect"]:
            lines.append(f"(assert (= {pfx}_has_effect true))")
            lines.append(f"(assert (= {pfx}_effect_value {_smt_escape(stmt['Effect'])}))")

        if "Action" in stmt and stmt["Action"]:
            actions = stmt["Action"]
            val = actions[0] if actions else ""
            lines.append(f"(assert (= {pfx}_has_action {'true' if val else 'false'}))")
            lines.append(f"(assert (= {pfx}_action_value {_smt_escape(val)}))")

        if "Principal" in stmt:
            principal = stmt["Principal"]
            if principal:
                p_type = next(iter(principal.keys()))
                p_vals = principal[p_type]
                p_val = p_vals[0] if p_vals else ""
                lines.append(f"(assert (= {pfx}_has_principal_type true))")
                lines.append(f"(assert (= {pfx}_principal_type {_smt_escape(p_type)}))")
                lines.append(f"(assert (= {pfx}_has_principal_value true))")
                lines.append(f"(assert (= {pfx}_principal_value {_smt_escape(p_val)}))")
            else:
                lines.append(f"(assert (= {pfx}_has_principal_type false))")
                lines.append(f"(assert (= {pfx}_has_principal_value false))")

        cond_block = stmt.get("Condition", {})
        if cond_block:
            conds = _extract_conditions(stmt)
            lines.append(f"(assert (= {pfx}_has_condition true))")
            for ci, (op, key, val) in enumerate(conds):
                cc = ci + 1
                lines.append(f"(assert (= {pfx}_cond_{cc}_operator {_smt_escape(op)}))")
                lines.append(f"(assert (= {pfx}_cond_{cc}_key {_smt_escape(key)}))")
                lines.append(f"(assert (= {pfx}_cond_{cc}_value {_smt_escape(val)}))")
        elif "Condition" in stmt:
            lines.append(f"(assert (= {pfx}_has_condition false))")

        lines.append("")

    return "\n".join(lines)


def tool_smt_validation_funcs(statements_json: str, constraints_json: str) -> str:
    """根据约束生成 define-fun 验证函数。

    从 constraints 中识别需要哪些验证，
    为每个 Statement 生成对应的 define-fun。
    """
    data = json.loads(statements_json)
    constraints = json.loads(constraints_json) if isinstance(constraints_json, str) else {}
    statements = data.get("statements", [])

    needed = _map_constraints(constraints)
    _enrich_needed(statements, needed)

    lines: list[str] = []

    for si, stmt in enumerate(statements):
        pfx = f"s{si + 1}"
        conds = _extract_conditions(stmt)
        has_cond_block = bool(stmt.get("Condition", {}))

        lines.append(f";; ── Statement {si + 1} validation ──")

        # Effect existence
        if "effect_exists" in needed and stmt.get("Effect"):
            lines.append(f"(define-fun {pfx}_effect_exists () Bool {pfx}_has_effect)")

        # Effect value valid
        if "effect_value_valid" in needed and stmt.get("Effect"):
            lines.append(f"(define-fun {pfx}_effect_value_valid () Bool")
            lines.append(f"    (=> {pfx}_has_effect")
            lines.append(f"        (or (= {pfx}_effect_value \"Allow\") (= {pfx}_effect_value \"Deny\"))))")

        # Action existence
        if "action_exists" in needed and stmt.get("Action") is not None:
            lines.append(f"(define-fun {pfx}_action_exists () Bool {pfx}_has_action)")

        # Action value valid
        if "action_value_valid" in needed and stmt.get("Action") is not None:
            lines.append(f"(define-fun {pfx}_action_value_valid () Bool")
            lines.append(f"    (=> {pfx}_has_action (not (= {pfx}_action_value \"\"))))")

        # Principal existence
        if "principal_exists" in needed and stmt.get("Principal") is not None:
            lines.append(f"(define-fun {pfx}_principal_exists () Bool {pfx}_has_principal_type)")

        # Principal value valid
        if "principal_value_valid" in needed and stmt.get("Principal") is not None:
            lines.append(f"(define-fun {pfx}_principal_value_valid () Bool")
            lines.append(f"    (=> {pfx}_has_principal_type (not (= {pfx}_principal_type \"\"))))")

        # Condition operator-key compatibility
        if "condition_operator_key_compatible" in needed and has_cond_block and conds:
            lines.extend(_gen_condition_compatibility(pfx, conds))

        # Condition exists
        if "condition_exists" in needed and "Condition" in stmt:
            lines.append(f"(define-fun {pfx}_condition_exists () Bool {pfx}_has_condition)")

        # Null condition valid
        if "null_condition_valid" in needed and has_cond_block:
            for ci, (op, key, val) in enumerate(conds):
                if op.lower().replace(" ", "") == "null":
                    cc = ci + 1
                    lines.append(f"(define-fun {pfx}_null_cond_{cc}_valid () Bool")
                    lines.append(f"    (=> (and {pfx}_has_condition (= {pfx}_cond_{cc}_operator \"null\"))")
                    lines.append(f"        (or (= {pfx}_cond_{cc}_value \"true\") (= {pfx}_cond_{cc}_value \"false\"))))")

        # Statement-level valid
        if "policy_has_valid_permission" in needed:
            checks = []
            for tag in ["effect_exists", "effect_value_valid", "action_exists", "action_value_valid",
                        "principal_exists", "principal_value_valid",
                        "condition_exists", "condition_operator_key_compatible",
                        "null_condition_valid"]:
                fn = f"{pfx}_{tag}"
                if tag in needed:
                    if tag == "effect_exists" and not stmt.get("Effect"):
                        continue
                    if tag == "effect_value_valid" and not stmt.get("Effect"):
                        continue
                    if "action" in tag and "Action" not in stmt:
                        continue
                    if "principal" in tag and "Principal" not in stmt:
                        continue
                    if tag == "condition_operator_key_compatible" and not has_cond_block:
                        continue
                    if tag == "condition_exists" and "Condition" not in stmt:
                        continue
                    checks.append(fn)

            if checks:
                lines.append(f"(define-fun {pfx}_statement_valid () Bool")
                if len(checks) == 1:
                    lines.append(f"    {checks[0]})")
                else:
                    lines.append("    (and")
                    for fn in checks:
                        lines.append(f"        {fn}")
                    lines.append("    ))")

        lines.append("")

    return "\n".join(lines)


def _map_constraints(constraints: dict | list) -> set[str]:
    """从 constraints 数据中提取需要的验证标签。"""
    needed: set[str] = set()
    items = constraints.get("constraints", []) if isinstance(constraints, dict) else constraints

    for c in items:
        desc = (c.get("description", "") if isinstance(c, dict) else str(c)).lower()
        cat = c.get("category", "") if isinstance(c, dict) else ""

        if cat == "field_existence":
            for kw, tag in [("effect", "effect_exists"), ("action", "action_exists"),
                           ("principal", "principal_exists"), ("condition", "condition_exists")]:
                if kw in desc:
                    needed.add(tag)
        elif cat == "field_specification":
            for kw, tag in [("effect", "effect_value_valid"), ("action", "action_value_valid"),
                           ("principal", "principal_value_valid")]:
                if kw in desc:
                    needed.add(tag)
            if "condition" in desc or "操作符" in desc or "运算符" in desc or "兼容" in desc:
                needed.add("condition_operator_key_compatible")
            if "null" in desc:
                needed.add("null_condition_valid")
        elif cat == "policy_validity":
            needed.add("policy_has_valid_permission")

    return needed


def _enrich_needed(statements: list[dict], needed: set[str]) -> None:
    """根据 policy 实际存在的字段自动补充需要的验证。"""
    for stmt in statements:
        if stmt.get("Effect"):
            needed.add("effect_exists")
            needed.add("effect_value_valid")
        if stmt.get("Action") is not None:
            needed.add("action_exists")
            needed.add("action_value_valid")
        if stmt.get("Principal") is not None:
            needed.add("principal_exists")
            needed.add("principal_value_valid")
        if stmt.get("Condition", {}):
            needed.add("condition_operator_key_compatible")
    if statements:
        needed.add("policy_has_valid_permission")


def _gen_condition_compatibility(pfx: str, conditions: list[tuple[str, str, str]]) -> list[str]:
    """为每个 condition 生成操作符-键兼容性检查的 define-fun。"""
    from modules.tools.smt_helpers import (
        _classify_operator, _classify_key,
        STRING_KEYS, NUMERIC_KEYS, BOOL_KEYS, DATE_KEYS, IP_KEYS, STRING_KEY_PREFIXES,
    )

    lines: list[str] = []

    for ci, (op, key, val) in enumerate(conditions):
        cc = ci + 1
        op_type = _classify_operator(op)
        key_type = _classify_key(key)
        op_var = f"{pfx}_cond_{cc}_operator"
        key_var = f"{pfx}_cond_{cc}_key"

        lines.append(f";; Condition {cc}: operator={op}, key={key}")

        # operator type check
        if op_type not in ("null", "multi_value", "unknown"):
            lines.append(f"(define-fun {pfx}_cond_{cc}_operator_type () Bool")
        elif op_type == "unknown":
            lines.append(f"(define-fun {pfx}_cond_{cc}_operator_type () Bool")
            lines.append(f"    true  ; unknown operator type")
            lines.append(")")

        # key type check
        if op_type == "null":
            lines.append(f"(define-fun {pfx}_cond_{cc}_compatible () Bool")
            lines.append(f"    (or (str.contains {pfx}_cond_{cc}_value \"true\") (= {pfx}_cond_{cc}_value \"false\"))")
        elif op_type == "unknown":
            lines.append(f"(define-fun {pfx}_cond_{cc}_compatible () Bool true")
        elif op_type == "multi_value":
            lines.append(f"(define-fun {pfx}_cond_{cc}_key_type () Bool")
            # Multi-value requires string keys
            all_string_keys = sorted(STRING_KEYS)
            parts = [f"(= {key_var} {_smt_escape(k)})" for k in all_string_keys]
            lines.append(f"    (or {' '.join(parts)})" if parts else "    true")
            lines.append(")")
            lines.append(f"(define-fun {pfx}_cond_{cc}_compatible () Bool {pfx}_cond_{cc}_key_type")
        else:
            # operator type check
            all_ops = _get_ops_by_type(op_type)
            if len(all_ops) == 1:
                lines.append(f"    (= {op_var} {_smt_escape(list(all_ops)[0])})")
            else:
                parts = [f"(= {op_var} {_smt_escape(o)})" for o in sorted(all_ops)]
                lines.append(f"    (or {' '.join(parts)})")
            lines.append(")")

            # key type check
            lines.append(f"(define-fun {pfx}_cond_{cc}_key_type () Bool")
            lines.append(f"    {_gen_key_check(key, op_type, key_var)}")
            lines.append(")")

            lines.append(f"(define-fun {pfx}_cond_{cc}_compatible () Bool")
            lines.append(f"    (and {pfx}_cond_{cc}_operator_type {pfx}_cond_{cc}_key_type)")

        lines.append(")")

    # Combine all
    if len(conditions) == 1:
        lines.append(f"(define-fun {pfx}_condition_operator_key_compatible () Bool")
        lines.append(f"    (=> {pfx}_has_condition {pfx}_cond_1_compatible)")
    else:
        lines.append(f"(define-fun {pfx}_condition_operator_key_compatible () Bool")
        lines.append(f"    (=> {pfx}_has_condition (and")
        for ci in range(len(conditions)):
            lines.append(f"        {pfx}_cond_{ci+1}_compatible")
        lines.append("    ))")
    lines.append(")")

    return lines


def _get_ops_by_type(op_type: str) -> set[str]:
    mapping = {
        "string": STRING_OPS, "numeric": NUMERIC_OPS, "date": DATE_OPS,
        "bool": BOOL_OPS, "ip": IP_OPS, "null": NULL_OPS, "multi_value": MULTI_VALUE_OPS,
    }
    return mapping.get(op_type, set())


def _gen_key_check(key: str, expected_type: str, var_name: str) -> str:
    """生成 key 类型检查的 SMT 表达式。"""
    if expected_type == "string":
        for pk in STRING_KEY_PREFIXES:
            if key.startswith(pk):
                return "true"
        keys = sorted(STRING_KEYS)
        if keys:
            parts = [f"(= {var_name} {_smt_escape(k)})" for k in keys]
            return "(or " + " ".join(parts) + ")"
        return "true"
    elif expected_type == "numeric":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in NUMERIC_KEYS]
        return "(or " + " ".join(parts) + ")"
    elif expected_type == "date":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in DATE_KEYS]
        return "(or " + " ".join(parts) + ")"
    elif expected_type == "bool":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in BOOL_KEYS]
        return "(or " + " ".join(parts) + ")"
    elif expected_type == "ip":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in IP_KEYS]
        return "(or " + " ".join(parts) + ")"
    return "true"


def tool_smt_contradiction_check(statements_json: str) -> str:
    """检测条件矛盾并生成 SMT 代码。

    检查条件间的逻辑矛盾（同值stringmatch+stringmatchnot等），
    对矛盾的条件生成 unsat 断言。
    """
    from modules.tools.smt_helpers import (
        _detect_contradictions, _extract_conditions as _extract_full,
    )

    data = json.loads(statements_json)
    statements = data.get("statements", [])
    lines: list[str] = []

    for si, stmt in enumerate(statements):
        pfx = f"s{si + 1}"
        cond_block = stmt.get("Condition", {})
        if not cond_block:
            continue

        conds_full = _extract_full(stmt)
        if not conds_full:
            continue

        contradictions = _detect_contradictions(conds_full, stmt.get("Effect", "Allow"))
        from modules.tools.smt_helpers import _has_date_past_only
        date_past = _has_date_past_only(conds_full)

        if contradictions or date_past:
            lines.append(f";; ── Statement {si + 1} contradictions ──")
            lines.append(f";; Statement {si + 1}: {len(contradictions)} contradiction(s)")
            if date_past:
                lines.append(";; Date condition restricts to the past — unsatisfiable")

            lines.append(f"(define-fun {pfx}_condition_values_not_contradictory () Bool")
            lines.append("    false  ;; contradictory/unsatisfiable conditions")
            lines.append(")")

            # 将 contradiction 函数注入 statement_valid
            # 通过重新定义 statement_valid（如果之前已定义）或生成补充断言
            lines.append(f";; Contradiction forces overall unsat")
            lines.append(f"(assert (not {pfx}_condition_values_not_contradictory))")
            lines.append("")

    return "\n".join(lines)


def tool_smt_allow_deny_combine(statements_json: str) -> str:
    """为混合 Effect（Allow + Deny）生成组合逻辑。

    当 policy 同时有 Allow 和 Deny 时，生成
    - any_allow_valid: 任一 Allow 有效
    - any_deny_valid: 任一 Deny 有效
    - any_statement_valid: (and any_allow_valid (not any_deny_valid))
    """
    data = json.loads(statements_json)
    statements = data.get("statements", [])
    is_mixed = data.get("is_mixed", False)
    lines: list[str] = []

    if not is_mixed:
        # 单一 Effect 类型：OR 逻辑
        prefixes = [f"s{si + 1}" for si in range(len(statements))]
        if len(prefixes) == 0:
            return "(define-fun any_statement_valid () Bool false)"
        elif len(prefixes) == 1:
            lines.append(f"(define-fun any_statement_valid () Bool {prefixes[0]}_statement_valid)")
        else:
            lines.append("(define-fun any_statement_valid () Bool")
            lines.append("    (or")
            for p in prefixes:
                lines.append(f"        {p}_statement_valid")
            lines.append("    ))")
    else:
        allow_p = [f"s{si + 1}" for si, s in enumerate(statements) if s.get("Effect") == "Allow"]
        deny_p = [f"s{si + 1}" for si, s in enumerate(statements) if s.get("Effect") == "Deny"]

        def _or_group(prefixes: list[str], name: str) -> None:
            if len(prefixes) == 0:
                lines.append(f"(define-fun {name} () Bool false)")
            elif len(prefixes) == 1:
                lines.append(f"(define-fun {name} () Bool {prefixes[0]}_statement_valid)")
            else:
                lines.append(f"(define-fun {name} () Bool")
                lines.append("    (or")
                for p in prefixes:
                    lines.append(f"        {p}_statement_valid")
                lines.append("    ))")

        _or_group(allow_p, "any_allow_valid")
        lines.append("")
        _or_group(deny_p, "any_deny_valid")
        lines.append("")

        # 默认使用严格模式：Deny 覆盖 Allow
        lines.append("(define-fun any_statement_valid () Bool")
        lines.append("    (and any_allow_valid (not any_deny_valid))")
        lines.append(")")

    return "\n".join(lines)


def tool_smt_assemble(code_sections: list[str]) -> str:
    """组装所有 SMT 代码段为最终完整代码。

    code_sections: 各阶段的 SMT 代码片段列表
    返回: 包含 check-sat 和 exit 的完整 SMT-LIB V2 代码
    """
    # 过滤空段
    sections = [s for s in code_sections if s and s.strip()]

    # 确保有 check-sat 和 exit
    all_text = "\n\n".join(sections)

    if "(check-sat)" not in all_text:
        if not all_text.endswith("\n"):
            all_text += "\n"
        all_text += "\n(assert any_statement_valid)\n(check-sat)\n(exit)"
    elif "(exit)" not in all_text:
        all_text += "\n(exit)"

    return all_text


def tool_smt_verify(code: str) -> str:
    """检查 SMT 代码的语法正确性。

    使用 Z3 check-syntax 验证，返回错误信息和 Z3 执行结果。
    """
    from utils.smt_executor import SMTExecutor
    executor = SMTExecutor()
    is_executable, output, _ = executor.execute(code)
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
        "description": "解析 IAM 配置，提取策略语句。入参 account_data 是原始配置字典。返回 JSON 包含 statements, is_mixed, sub_scenario。",
        "parameters": {
            "type": "object",
            "properties": {
                "account_data": {
                    "type": "object",
                    "description": "原始 IAM 配置字典（含 bucket_policy 或 trust_policy）",
                }
            },
            "required": ["account_data"],
        },
    },
    {
        "name": "smt_declare_variables",
        "description": "为每个 Statement 生成 declare-const 变量声明（Effect/Action/Principal/Condition 的 has_X 和 X_value 变量）。入参 statements_json 是 parse_iam_policy 的返回。",
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
        "name": "smt_assert_config",
        "description": "根据配置值生成 assert 断言，将实际 IAM 配置值映射到 SMT 变量。",
        "parameters": {
            "type": "object",
            "properties": {
                "statements_json": {"type": "string", "description": "parse_iam_policy 返回的 JSON"},
            },
            "required": ["statements_json"],
        },
    },
    {
        "name": "smt_validation_funcs",
        "description": "根据约束列表生成 define-fun 验证函数（effect_value_valid, action_exists, condition_compatible 等）。入参 constraints_json 是 Agent 1 输出的约束列表 JSON。",
        "parameters": {
            "type": "object",
            "properties": {
                "statements_json": {"type": "string"},
                "constraints_json": {"type": "string", "description": "约束列表 JSON（含 constraints 数组）"},
            },
            "required": ["statements_json", "constraints_json"],
        },
    },
    {
        "name": "smt_contradiction_check",
        "description": "检测策略中条件间的逻辑矛盾（stringmatch+stringmatchnot 同值、数值范围空、Allow+Deny 不兼容等），生成 unsat 断言。",
        "parameters": {
            "type": "object",
            "properties": {
                "statements_json": {"type": "string"},
            },
            "required": ["statements_json"],
        },
    },
    {
        "name": "smt_allow_deny_combine",
        "description": "生成 Statement 间的组合逻辑（单一 Effect 类型用 OR，混合 Allow+Deny 用 AND-NOT），包含 any_statement_valid 定义。",
        "parameters": {
            "type": "object",
            "properties": {
                "statements_json": {"type": "string"},
            },
            "required": ["statements_json"],
        },
    },
    {
        "name": "smt_assemble",
        "description": "组装所有代码段为完整 SMT-LIB V2 代码，添加 check-sat 和 exit。入参 code_sections 是代码段列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "code_sections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "各 SMT 代码段（变量声明、断言、验证函数等）",
                }
            },
            "required": ["code_sections"],
        },
    },
    {
        "name": "smt_verify",
        "description": "用 Z3 检查 SMT 代码的语法正确性。入参 code 是待检查的 SMT 代码文本。返回语法检查结果和 Z3 输出。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "完整的 SMT-LIB V2 代码文本"},
            },
            "required": ["code"],
        },
    },
]
