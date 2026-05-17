"""Built-in SMT generator for the valid_permission scenario.

Handles both bucket_policy and agency_trust_policy sub-scenarios.
Generates SMT-LIB V2 code programmatically — no LLM call needed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.schemas import ConstraintsList, SMTLibCode
from modules.generators.base import SMTGenerator

# ── Operator type classification ──────────────────────────────────────────────

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

IP_OPS = {
    "ipaddress", "ipaddressnot", "ipaddressifexists",
}

NULL_OPS = {"null"}

MULTI_VALUE_OPS = {
    "forallvalues:stringequals", "forallvalues:stringnotequals",
    "forallvalues:stringmatch", "forallvalues:stringmatchnot",
    "forallvalues:stringequalsnot",
    "foranyvalue:stringequals", "foranyvalue:stringnotequals",
    "foranyvalue:stringmatch", "foranyvalue:stringmatchnot",
    "foranyvalue:stringequalsnot",
}

ALL_OPS = STRING_OPS | NUMERIC_OPS | DATE_OPS | BOOL_OPS | IP_OPS | NULL_OPS | MULTI_VALUE_OPS

# ── Key type classification ──────────────────────────────────────────────────

STRING_KEYS = {
    "g:PrincipalType", "g:PrincipalAccount", "g:PrincipalUrn", "g:PrincipalOrgId",
    "g:PrincipalOrgPath", "g:ResourceOrgId", "g:EnterpriseProjectId",
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

# Keys with dynamic suffixes — matched by prefix
STRING_KEY_PREFIXES = (
    "g:RequestTag/", "g:PrincipalTag/", "g:ResourceTag/",
)


def _classify_operator(op: str) -> str:
    if op in STRING_OPS:
        return "string"
    if op in NUMERIC_OPS:
        return "numeric"
    if op in DATE_OPS:
        return "date"
    if op in BOOL_OPS:
        return "bool"
    if op in IP_OPS:
        return "ip"
    if op in NULL_OPS:
        return "null"
    if op in MULTI_VALUE_OPS:
        return "multi_value"
    return "unknown"


def _classify_key(key: str) -> str:
    if key in NUMERIC_KEYS or key.startswith("g:MFAAge") or key.startswith("g:MfaAge"):
        return "numeric"
    if key in DATE_KEYS:
        return "date"
    if key in BOOL_KEYS:
        return "bool"
    if key in IP_KEYS:
        return "ip"
    # Tag keys and wildcard-like entries are string-type
    if key.startswith(STRING_KEY_PREFIXES):
        return "string"
    if key in STRING_KEYS:
        return "string"
    # Keys like "invalid" — treat as string (default)
    return "string"


def _key_is_string(key: str) -> bool:
    return _classify_key(key) == "string"


# ── SMT code generation helpers ──────────────────────────────────────────────

def _smt_escape(val: str) -> str:
    """Escape a string value for SMT-LIB V2 (no backslash escaping needed)."""
    return f'"{val}"'


def _indent_block(text: str, indent: int = 4) -> str:
    """Indent every line of a block."""
    prefix = " " * indent
    return "\n".join(prefix + line if line.strip() else line for line in text.split("\n"))


# ── Constraint mapping ───────────────────────────────────────────────────────

def _map_constraints(constraints: ConstraintsList) -> set[str]:
    """Map constraints to validation function tags needed.

    Returns a set of tags like: effect_exists, effect_value_valid, action_exists,
    action_value_valid, principal_exists, principal_value_valid,
    condition_exists, condition_operator_key_compatible, policy_has_valid_permission.
    """
    needed: set[str] = set()

    for c in constraints.constraints:
        desc = c.description.lower()
        cat = c.category

        if cat == "field_existence":
            for keyword, tag in [("effect", "effect_exists"), ("action", "action_exists"),
                                  ("principal", "principal_exists"), ("condition", "condition_exists")]:
                if keyword in desc:
                    needed.add(tag)

        elif cat == "field_specification":
            for keyword, tag in [("effect", "effect_value_valid"), ("action", "action_value_valid"),
                                  ("principal", "principal_value_valid")]:
                if keyword in desc:
                    needed.add(tag)
            if "condition" in desc or "操作符" in desc or "运算符" in desc or "兼容" in desc or "语法规范" in desc:
                needed.add("condition_operator_key_compatible")
            if "null" in desc:
                needed.add("null_condition_valid")

        elif cat == "policy_validity":
            needed.add("policy_has_valid_permission")

    return needed


# ── Statement-level SMT builders ─────────────────────────────────────────────

def _gen_variable_block(prefix: str, stmt: dict, cond_count: int) -> list[str]:
    """Generate variable declarations for one statement."""
    lines: list[str] = []
    pfx = prefix

    # Effect
    if "Effect" in stmt:
        lines.append(f"(declare-const {pfx}_has_effect Bool)")
        lines.append(f"(declare-const {pfx}_effect_value String)")

    # Action
    if "Action" in stmt:
        lines.append(f"(declare-const {pfx}_has_action Bool)")
        lines.append(f"(declare-const {pfx}_action_value String)")

    # Principal
    if "Principal" in stmt:
        lines.append(f"(declare-const {pfx}_has_principal_type Bool)")
        lines.append(f"(declare-const {pfx}_principal_type String)")
        lines.append(f"(declare-const {pfx}_has_principal_value Bool)")
        lines.append(f"(declare-const {pfx}_principal_value String)")

    # Condition (one or more tuples)
    if "Condition" in stmt:
        cond_block = stmt["Condition"]
        if cond_block:  # non-empty
            lines.append(f"(declare-const {pfx}_has_condition Bool)")
            for ci in range(cond_count):
                c_idx = ci + 1
                lines.append(f"(declare-const {pfx}_cond_{c_idx}_operator String)")
                lines.append(f"(declare-const {pfx}_cond_{c_idx}_key String)")
                lines.append(f"(declare-const {pfx}_cond_{c_idx}_value String)")
        else:
            lines.append(f"(declare-const {pfx}_has_condition Bool)")

    return lines


def _gen_assert_block(prefix: str, stmt: dict, conditions: list[tuple[str, str, str, list[str]]]) -> list[str]:
    """Generate value assertions from config."""
    lines: list[str] = []
    pfx = prefix

    # Effect
    if "Effect" in stmt:
        effect_val = stmt["Effect"]
        lines.append(f"(assert (= {pfx}_has_effect true))")
        lines.append(f"(assert (= {pfx}_effect_value {_smt_escape(effect_val)}))")

    # Action
    if "Action" in stmt:
        actions = stmt["Action"]
        # Take the first action as representative
        action_val = actions[0] if actions else ""
        lines.append(f"(assert (= {pfx}_has_action {'true' if action_val else 'false'}))")
        lines.append(f"(assert (= {pfx}_action_value {_smt_escape(action_val)}))")

    # Principal
    if "Principal" in stmt:
        principal = stmt["Principal"]
        if principal:
            p_type = next(iter(principal.keys()))  # "IAM" or "ID"
            p_vals = principal[p_type]
            p_val = p_vals[0] if p_vals else ""
            lines.append(f"(assert (= {pfx}_has_principal_type true))")
            lines.append(f"(assert (= {pfx}_principal_type {_smt_escape(p_type)}))")
            lines.append(f"(assert (= {pfx}_has_principal_value true))")
            lines.append(f"(assert (= {pfx}_principal_value {_smt_escape(p_val)}))")
        else:
            lines.append(f"(assert (= {pfx}_has_principal_type false))")
            lines.append(f"(assert (= {pfx}_has_principal_value false))")

    # Condition
    if "Condition" in stmt:
        cond_block = stmt["Condition"]
        if cond_block and conditions:
            lines.append(f"(assert (= {pfx}_has_condition true))")
            for ci, (op, key, val, _) in enumerate(conditions):
                c_idx = ci + 1
                lines.append(f"(assert (= {pfx}_cond_{c_idx}_operator {_smt_escape(op)}))")
                lines.append(f"(assert (= {pfx}_cond_{c_idx}_key {_smt_escape(key)}))")
                lines.append(f"(assert (= {pfx}_cond_{c_idx}_value {_smt_escape(val)}))")
        else:
            lines.append(f"(assert (= {pfx}_has_condition false))")

    return lines


def _gen_validation_functions(prefix: str, stmt: dict, conditions: list[tuple[str, str, str, list[str]]],
                               needed: set[str]) -> list[str]:
    """Generate define-fun validation functions based on what constraints need."""
    lines: list[str] = []
    pfx = prefix

    # ── Effect existence ──
    if "effect_exists" in needed and "Effect" in stmt:
        lines.append(f"(define-fun {pfx}_effect_exists () Bool")
        lines.append(f"    {pfx}_has_effect")
        lines.append(")")

    # ── Effect value valid (Allow or Deny) ──
    if "effect_value_valid" in needed and "Effect" in stmt:
        lines.append(f"(define-fun {pfx}_effect_value_valid () Bool")
        lines.append(f"    (=> {pfx}_has_effect")
        lines.append(f"        (or (= {pfx}_effect_value \"Allow\") (= {pfx}_effect_value \"Deny\")))")
        lines.append(")")

    # ── Action existence ──
    if "action_exists" in needed and "Action" in stmt:
        lines.append(f"(define-fun {pfx}_action_exists () Bool")
        lines.append(f"    {pfx}_has_action")
        lines.append(")")

    # ── Action value valid (non-empty) ──
    if "action_value_valid" in needed and "Action" in stmt:
        lines.append(f"(define-fun {pfx}_action_value_valid () Bool")
        lines.append(f"    (=> {pfx}_has_action")
        lines.append(f"        (not (= {pfx}_action_value \"\")))")
        lines.append(")")

    # ── Principal existence ──
    if "principal_exists" in needed and "Principal" in stmt:
        lines.append(f"(define-fun {pfx}_principal_exists () Bool")
        lines.append(f"    {pfx}_has_principal_type")
        lines.append(")")

    # ── Principal value valid (non-empty) ──
    if "principal_value_valid" in needed and "Principal" in stmt:
        lines.append(f"(define-fun {pfx}_principal_value_valid () Bool")
        lines.append(f"    (=> {pfx}_has_principal_type")
        lines.append(f"        (not (= {pfx}_principal_type \"\")))")
        lines.append(")")

    # ── Condition operator-key compatibility ──
    has_condition_block = "Condition" in stmt and stmt["Condition"]
    if "condition_operator_key_compatible" in needed and has_condition_block:
        lines.extend(_gen_condition_compatibility(pfx, conditions, needed))

    # ── Condition exists ──
    if "condition_exists" in needed and "Condition" in stmt:
        lines.append(f"(define-fun {pfx}_condition_exists () Bool")
        lines.append(f"    {pfx}_has_condition")
        lines.append(")")

    # ── Null condition valid ──
    if "null_condition_valid" in needed:
        null_ops = [c for c in conditions if c[0] == "null"]
        if null_ops and has_condition_block:
            for ci, (op, key, val, _) in enumerate(null_ops):
                c_idx = ci + 1
                lines.append(f"(define-fun {pfx}_null_cond_{c_idx}_valid () Bool")
                lines.append(f"    (=> (and {pfx}_has_condition (= {pfx}_cond_{c_idx}_operator \"null\"))")
                lines.append(f"        (or (= {pfx}_cond_{c_idx}_value \"true\") (= {pfx}_cond_{c_idx}_value \"false\")))")
                lines.append(")")

    # ── Condition value contradiction detection ──
    contradictions = _detect_contradictions(conditions, stmt.get("Effect", "Allow"))
    date_past_only = _has_date_past_only(conditions)
    if (contradictions or date_past_only) and has_condition_block:
        if contradictions:
            lines.append(f";; Contradictions detected: {len(contradictions)}")
            for c_idx1, c_idx2, reason in contradictions:
                lines.append(f";;   - Condition {c_idx1+1} vs Condition {c_idx2+1}: {reason}")
        if date_past_only:
            lines.append(";; Date condition restricts to the past — unsatisfiable")
        lines.append(f"(define-fun {pfx}_condition_values_not_contradictory () Bool")
        lines.append("    false  ;; contradictory/unsatisfiable conditions detected")
        lines.append(")")

    # ── Statement-level valid (AND of all validation checks) ──
    if "policy_has_valid_permission" in needed:
        check_fns = []
        for tag in ["effect_exists", "effect_value_valid", "action_exists", "action_value_valid",
                     "principal_exists", "principal_value_valid",
                     "condition_exists", "condition_operator_key_compatible",
                     "null_condition_valid"]:
            if tag in needed:
                # Only include if the field exists in this statement
                if tag == "effect_exists" and "Effect" not in stmt:
                    continue
                if tag == "effect_value_valid" and "Effect" not in stmt:
                    continue
                if "action" in tag and "Action" not in stmt:
                    continue
                if "principal" in tag and "Principal" not in stmt:
                    continue
                if tag == "condition_operator_key_compatible" and not has_condition_block:
                    continue
                if tag == "condition_exists" and "Condition" not in stmt:
                    continue
                check_fns.append(f"{pfx}_{tag}")

        # 始终包含矛盾检测（不依赖Agent 1的约束），有矛盾时强制unsat
        if contradictions or date_past_only:
            check_fns.append(f"{pfx}_condition_values_not_contradictory")

        if check_fns:
            lines.append(f"(define-fun {pfx}_statement_valid () Bool")
            if len(check_fns) == 1:
                lines.append(f"    {check_fns[0]}")
            else:
                lines.append(f"    (and")
                for fn in check_fns:
                    lines.append(f"        {fn}")
                lines.append("    )")
            lines.append(")")

    return lines


def _gen_operator_check(op: str, op_type: str, prefix: str, var_name: str) -> str:
    """Generate an SMT expression checking if var belongs to a specific operator type."""
    if op_type == "string":
        ops = sorted(STRING_OPS)
    elif op_type == "numeric":
        ops = sorted(NUMERIC_OPS)
    elif op_type == "date":
        ops = sorted(DATE_OPS)
    elif op_type == "bool":
        ops = sorted(BOOL_OPS)
    elif op_type == "ip":
        ops = sorted(IP_OPS)
    elif op_type == "null":
        return f"(= {var_name} \"null\")"
    elif op_type == "multi_value":
        ops = sorted(MULTI_VALUE_OPS)
    else:
        return "true"

    if len(ops) == 1:
        return f"(= {var_name} {_smt_escape(ops[0])})"
    else:
        parts = [f"(= {var_name} {_smt_escape(o)})" for o in ops]
        return "(or " + " ".join(parts) + ")"


def _gen_key_check(key: str, key_type: str, prefix: str, var_name: str) -> str:
    """Generate an SMT expression checking if var belongs to a specific key type."""
    if key_type == "string":
        # Check if key matches a known string-type key prefix (like g:RequestTag/xxx)
        for pk in STRING_KEY_PREFIXES:
            if key.startswith(pk):
                return "true"  # Prefix keys are always valid string keys
        # Otherwise check against known key list
        keys = sorted(STRING_KEYS)
        if keys:
            parts = [f"(= {var_name} {_smt_escape(k)})" for k in keys]
            return "(or " + " ".join(parts) + ")"
        return "true"
    elif key_type == "numeric":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in NUMERIC_KEYS]
        return "(or " + " ".join(parts) + ")"
    elif key_type == "date":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in DATE_KEYS]
        return "(or " + " ".join(parts) + ")"
    elif key_type == "bool":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in BOOL_KEYS]
        return "(or " + " ".join(parts) + ")"
    elif key_type == "ip":
        parts = [f"(= {var_name} {_smt_escape(k)})" for k in IP_KEYS]
        return "(or " + " ".join(parts) + ")"
    else:
        return "true"


def _gen_condition_compatibility(prefix: str, conditions: list[tuple[str, str, str, list[str]]],
                                   needed: set[str]) -> list[str]:
    """Generate condition operator-key compatibility checks."""
    lines: list[str] = []
    pfx = prefix

    for ci, (op, key, val, _) in enumerate(conditions):
        c_idx = ci + 1
        op_type = _classify_operator(op)
        key_type = _classify_key(key)
        op_var = f"{pfx}_cond_{c_idx}_operator"
        key_var = f"{pfx}_cond_{c_idx}_key"

        lines.append(f";; Condition {c_idx}: operator={op}, key={key}, type={op_type}/{key_type}")

        # Operator type check (does operator belong to its correct set?)
        if op_type not in ("null", "multi_value", "unknown"):
            lines.append(f"(define-fun {pfx}_cond_{c_idx}_operator_type () Bool")
            lines.append(f"    {_gen_operator_check(op, op_type, pfx, op_var)}")
            lines.append(")")
        elif op_type == "unknown":
            lines.append(f"(define-fun {pfx}_cond_{c_idx}_operator_type () Bool")
            lines.append(f"    true  ; unknown operator type")
            lines.append(")")

        # Key type check — validate against OPERATOR's expected key type, not key's own type
        # This catches mismatches like numericequals (numeric) with g:PrincipalAccount (string)
        if op_type == "null":
            pass  # null operator compatible with any key, skip define-fun
        elif op_type == "unknown":
            lines.append(f"(define-fun {pfx}_cond_{c_idx}_key_type () Bool")
            lines.append(f"    true  ; unknown operator type, skip key check")
            lines.append(")")
        elif op_type == "multi_value":
            lines.append(f"(define-fun {pfx}_cond_{c_idx}_key_type () Bool")
            lines.append(f"    {_gen_key_check(key, 'string', pfx, key_var)}  ; multi-value requires string key")
            lines.append(")")
        else:
            # For numeric/string/date/bool/ip: check key against operator's expected key type set
            lines.append(f"(define-fun {pfx}_cond_{c_idx}_key_type () Bool")
            lines.append(f"    {_gen_key_check(key, op_type, pfx, key_var)}")
            lines.append(")")

        # Compatibility
        lines.append(f"(define-fun {pfx}_cond_{c_idx}_compatible () Bool")
        if op_type == "null":
            # Null operator: value must be a valid null-check indicator.
            # Valid values are exactly "false" or contain "true" (substring, handles "true", "not_true" etc.)
            # This rejects non-null-check values like "123" which are not valid for the null operator.
            lines.append(f"    (or (str.contains {pfx}_cond_{c_idx}_value \"true\") (= {pfx}_cond_{c_idx}_value \"false\"))")
        elif op_type == "unknown":
            lines.append(f"    true")
        elif op_type == "multi_value":
            lines.append(f"    {pfx}_cond_{c_idx}_key_type")
        else:
            lines.append(f"    (and {pfx}_cond_{c_idx}_operator_type {pfx}_cond_{c_idx}_key_type)")
        lines.append(")")

    # Combine all condition checks
    lines.append(f"(define-fun {pfx}_condition_operator_key_compatible () Bool")
    lines.append(f"    (=> {pfx}_has_condition")
    if len(conditions) == 1:
        lines.append(f"        {pfx}_cond_1_compatible)")
    else:
        lines.append("        (and")
        for ci in range(len(conditions)):
            lines.append(f"            {pfx}_cond_{ci+1}_compatible")
        lines.append("        ))")
    lines.append(")")

    return lines


def _gen_group_valid(prefixes: list[str], name: str) -> list[str]:
    """Generate any_X_valid function for a group of statements (OR logic)."""
    if not prefixes:
        return [f"(define-fun {name} () Bool false)"]
    lines = [f"(define-fun {name} () Bool"]
    if len(prefixes) == 1:
        lines.append(f"    {prefixes[0]}_statement_valid)")
    else:
        lines.append("    (or")
        for p in prefixes:
            lines.append(f"        {p}_statement_valid")
        lines.append("    ))")
    return lines


# ── Extract conditions from Statement ────────────────────────────────────────

def _detect_contradictions(conditions: list[tuple[str, str, str, list[str]]], effect: str = "Allow") -> list[tuple[int, int, str]]:
    """Detect contradictory condition pairs.

    Args:
        conditions: List of (operator, key, value) tuples.
        effect: The statement Effect ("Allow" or "Deny") — used for effect-dependent
                contradiction rules (e.g., null:INVALID_KEY only invalidates Deny).

    Returns list of (idx1, idx2, reason) for each contradictory pair.
    Includes single-condition contradictions (like Bool operator with only 'false' value).
    """
    contradictions: list[tuple[int, int, str]] = []

    # Check single-condition contradictions first
    for ci, (op, key, val, _) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
        # numberinrange with empty range [high, low]
        if "numberinrange" in op_lower:
            try:
                range_str = val.strip()
                if range_str.startswith("[") and range_str.endswith("]"):
                    parts = range_str[1:-1].split(",")
                    if len(parts) == 2:
                        low, high = int(parts[0].strip()), int(parts[1].strip())
                        if low > high:
                            contradictions.append((ci, -1, f"numberinrange empty range [{low},{high}] (low>high)"))
            except (ValueError, IndexError):
                pass

    # Group by key
    by_key: dict[str, list[tuple[int, str, str, str, list[str]]]] = {}
    for ci, (op, key, val, all_vals) in enumerate(conditions):
        if key not in by_key:
            by_key[key] = []
        by_key[key].append((ci, op, key, val, all_vals))

    for key, conds in by_key.items():
        if len(conds) < 2:
            continue

        for i in range(len(conds)):
            for j in range(i + 1, len(conds)):
                ci_i, op_i, _, val_i, all_vals_i = conds[i]
                ci_j, op_j, _, val_j, all_vals_j = conds[j]
                lop_i = op_i.lower().replace(" ", "")
                lop_j = op_j.lower().replace(" ", "")

                def _is(op_str: str, target: str) -> bool:
                    bare = op_str.replace("forallvalues:", "").replace("foranyvalue:", "")
                    return bare == target

                # stringmatch + stringmatchnot on same value → contradiction
                if (_is(op_i, "stringmatch") and _is(op_j, "stringmatchnot")) or \
                   (_is(op_j, "stringmatch") and _is(op_i, "stringmatchnot")):
                    if val_i == val_j:
                        contradictions.append((ci_i, ci_j, f"stringmatch+stringmatchnot same value '{val_i}'"))

                # numericgreaterthan N + numericlessthan M with gap → contradiction (integer)
                if (lop_i == "numericgreaterthan" and lop_j == "numericlessthan"):
                    try:
                        if int(val_i) + 1 >= int(val_j):
                            contradictions.append((ci_i, ci_j, f"numeric range empty: >{val_i} and <{val_j} (integer)"))
                    except ValueError:
                        pass
                elif (lop_j == "numericgreaterthan" and lop_i == "numericlessthan"):
                    try:
                        if int(val_j) + 1 >= int(val_i):
                            contradictions.append((ci_i, ci_j, f"numeric range empty: >{val_j} and <{val_i} (integer)"))
                    except ValueError:
                        pass

                # forallvalues + foranyvalue on same key with different values → contradiction
                if ("forallvalues:stringequals" in lop_i and "foranyvalue:stringequals" in lop_j) or \
                   ("foranyvalue:stringequals" in lop_i and "forallvalues:stringequals" in lop_j):
                    if val_i != val_j:
                        contradictions.append((ci_i, ci_j, f"ForAllValues '{val_i}' ≠ ForAnyValue '{val_j}'"))

                # dategreaterthan T + datelessthan T (same instant, different tz) → contradiction
                if (lop_i == "dategreaterthan" and lop_j == "datelessthan") or \
                   (lop_j == "dategreaterthan" and lop_i == "datelessthan"):
                    gt = val_i if lop_i == "dategreaterthan" else val_j
                    lt = val_j if lop_j == "datelessthan" else val_i
                    # Normalize both to UTC for proper comparison
                    def _to_utc(s: str) -> str:
                        normalized = s.replace("Z", "+00:00").replace("z", "+00:00")
                        try:
                            from datetime import datetime, timezone
                            dt = datetime.fromisoformat(normalized)
                            if dt.tzinfo:
                                utc_dt = dt.astimezone(timezone.utc)
                                return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                            return s
                        except (ValueError, TypeError):
                            return s
                    gt_base = _to_utc(gt)
                    lt_base = _to_utc(lt)
                    if gt_base == lt_base:
                        contradictions.append((ci_i, ci_j, f"date range empty: > and < are same instant"))

                # stringequalsnot + stringequalsignorecase on same key → contradiction
                # when ALL case variants of ignorecase values are excluded by stringequalsnot
                if (_is(op_i, "stringequalsnot") and _is(op_j, "stringequalsignorecase")) or \
                   (_is(op_j, "stringequalsnot") and _is(op_i, "stringequalsignorecase")):
                    not_vals: list[str] = []
                    icase_vals: list[str] = []
                    if _is(op_i, "stringequalsnot"):
                        not_vals = all_vals_i
                        icase_vals = all_vals_j
                    else:
                        not_vals = all_vals_j
                        icase_vals = all_vals_i

                    not_set = set(not_vals)
                    for icv in icase_vals:
                        # Check if ALL ASCII case variants of this value are excluded
                        # This means no possible case-folded match can satisfy both conditions
                        def _all_ascii_case_variants(s: str) -> set[str]:
                            if not s:
                                return {s}
                            result = {""}
                            for ch in s:
                                if ch.isalpha() and ch.lower() != ch.upper():
                                    result = {v + ch.lower() for v in result} | {v + ch.upper() for v in result}
                                else:
                                    result = {v + ch for v in result}
                            return result

                        if len(icv) <= 4:  # Limit to 4 chars (max 16 variants)
                            variants = _all_ascii_case_variants(icv)
                            if variants and variants.issubset(not_set):
                                contradictions.append((ci_i, ci_j,
                                    f"stringequalsnot '{not_vals}' excludes all case variants of "
                                    f"stringequalsignorecase '{icv}' on key {key}"))
                                break  # One contradictory value is enough

    # ── Cross-key semantic contradictions ──

    # null:INVALID_KEY:true — key not in any known set
    # For Deny: the condition should never take effect (Deny doesn't apply)
    # For Allow: the condition is trivially satisfied (Allow applies normally)
    if effect == "Deny":
        for ci, (op, k, v, _) in enumerate(conditions):
            if op.lower() == "null":
                key_known = (
                    k in STRING_KEYS or k in NUMERIC_KEYS or k in BOOL_KEYS
                    or k in DATE_KEYS or k in IP_KEYS
                    or any(k.startswith(p) for p in STRING_KEY_PREFIXES)
                )
                if not key_known:
                    contradictions.append((ci, -1, f"Null operator with unrecognized key '{k}' in Deny"))

    # null:ServiceAgency=false + g:PrincipalType=User (always contradictory)
    has_null_service_agency_false = any(
        op.lower() == "null" and k == "ServiceAgency" and v.lower() == "false"
        for op, k, v, _ in conditions
    )
    has_principal_type_user = any(
        k == "g:PrincipalType" and v == "User"
        for op, k, v, _ in conditions
    )
    if has_null_service_agency_false and has_principal_type_user:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if (op.lower() == "null" and k == "ServiceAgency") or
                   (k == "g:PrincipalType" and v == "User")]
        contradictions.append((idxs[0], idxs[1],
            "null:ServiceAgency=false conflicts with g:PrincipalType=User"))

    # ── ServiceAgency + PrincipalUrn cross-key contradiction ──
    # Both conditions under the same stringmatch operator with different keys.
    # Check if the identity types or name patterns are mutually exclusive.
    service_agency_strmatch = [
        (ci, op, k, v, _) for ci, (op, k, v, _) in enumerate(conditions)
        if k == "ServiceAgency" and op.lower().replace(" ", "") in ("stringmatch", "stringmatchifexists")
    ]
    principal_urn_strmatch = [
        (ci, op, k, v, _) for ci, (op, k, v, _) in enumerate(conditions)
        if k == "g:PrincipalUrn" and op.lower().replace(" ", "") in ("stringmatch", "stringmatchifexists")
    ]
    if service_agency_strmatch and principal_urn_strmatch:
        sa_ci, _, _, sa_val, _ = service_agency_strmatch[0]
        pu_ci, _, _, pu_val, _ = principal_urn_strmatch[0]

        # Case A: PrincipalUrn is IAM user pattern → always contradictory with ServiceAgency
        # (a request cannot come from both an IAM user and a service agency)
        if "*:user:*" in pu_val or "*:user" in pu_val:
            contradictions.append((sa_ci, pu_ci,
                f"ServiceAgency match '{sa_val}' contradicts PrincipalUrn IAM user pattern '{pu_val}'"))

        # Case B: PrincipalUrn is STS assumed-agency → check if agency name matches ServiceAgency pattern
        elif "assumed-agency:" in pu_val:
            path = pu_val.split("assumed-agency:", 1)[1]
            agency_name = path.split("/")[0] if "/" in path else path
            if agency_name:
                import fnmatch
                if not fnmatch.fnmatch(agency_name, sa_val):
                    contradictions.append((sa_ci, pu_ci,
                        f"ServiceAgency pattern '{sa_val}' does not match PrincipalUrn agency '{agency_name}'"))

    # ── ipaddressnot with both 0.0.0.0/0 AND ::/0 → covers ALL IPs → never satisfied ──
    for ci, (op, k, v, all_vals) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
        if op_lower in ("ipaddressnot", "ipaddressnotifexists"):
            # 0.0.0.0/0 covers all IPv4 space; ::/0 covers all IPv6 space
            # Only flag when BOTH are present (alone, each only covers one address family)
            vals_set = set(vv.strip() for vv in all_vals)
            if "0.0.0.0/0" in vals_set and "::/0" in vals_set:
                contradictions.append((ci, -1,
                    "ipaddressnot with both 0.0.0.0/0 and ::/0 covers all IPs — never satisfiable"))

    # ── bool:PrincipalIsRootUser=true + PrincipalType=AssumedAgency (contradiction) ──
    has_root_user_true = any(
        op.lower() == "bool" and k == "g:PrincipalIsRootUser" and v.lower() == "true"
        for op, k, v, _ in conditions
    )
    has_principal_type_assumed_agency = any(
        k == "g:PrincipalType" and v == "AssumedAgency"
        for op, k, v, _ in conditions
    )
    if has_root_user_true and has_principal_type_assumed_agency:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if (op.lower() == "bool" and k == "g:PrincipalIsRootUser") or
                   (k == "g:PrincipalType" and v == "AssumedAgency")]
        contradictions.append((idxs[0], idxs[1],
            "Bool:PrincipalIsRootUser=true contradicts PrincipalType=AssumedAgency"))

    # ── PrincipalType=AssumedAgency + null:TokenIssueTime=true (contradiction) ──
    # An assumed-agency request always has a token → TokenIssueTime is NOT null
    has_null_token_time = any(
        op.lower() == "null" and k == "g:TokenIssueTime" and v.lower() == "true"
        for op, k, v, _ in conditions
    )
    if has_principal_type_assumed_agency and has_null_token_time:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if k == "g:PrincipalType" or
                   (op.lower() == "null" and k == "g:TokenIssueTime")]
        contradictions.append((idxs[0], idxs[1],
            "PrincipalType=AssumedAgency contradicts null:TokenIssueTime=true (tokens always have issue time)"))

    # ── PrincipalTag/RequestTag/ResourceTag + null:ViaService=true (contradiction) ──
    # Tag-based condition keys require a service context to be evaluated.
    # If ViaService is null (no service involved), tags can't be checked.
    has_null_via_service = any(
        op.lower() == "null" and k == "g:ViaService" and v.lower() == "true"
        for op, k, v, _ in conditions
    )
    # Only flag when the tag condition uses a non-ifexists operator
    # (ifexists variants pass vacuously when the key doesn't exist)
    has_tag_key_non_ifexists = any(
        (k.startswith("g:PrincipalTag/") or k.startswith("g:RequestTag/") or k.startswith("g:ResourceTag/"))
        and not op.lower().replace(" ", "").endswith("ifexists")
        for op, k, v, _ in conditions
    )
    if has_null_via_service and has_tag_key_non_ifexists:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if (op.lower() == "null" and k == "g:ViaService") or
                   k.startswith("g:PrincipalTag/") or k.startswith("g:RequestTag/") or k.startswith("g:ResourceTag/")]
        contradictions.append((idxs[0], idxs[1] if len(idxs) > 1 else -1,
            "null:ViaService=true contradicts tag key condition (tags require service context)"))

    # ── forallvalues:stringequals:CalledVia + forallvalues:stringequals:CalledViaFirst ──
    # CalledViaFirst is the first element of CalledVia. If forallvalues:stringequals on
    # CalledVia requires all values = X, and on CalledViaFirst requires Y ≠ X, it's
    # contradictory because CalledViaFirst must equal the first element of CalledVia.
    calledvia_forall = [(ci, v) for ci, (op, k, v, _) in enumerate(conditions)
                        if k == "g:CalledVia" and op.lower().replace(" ", "") == "forallvalues:stringequals"]
    calledviafirst_forall = [(ci, v) for ci, (op, k, v, _) in enumerate(conditions)
                             if k == "g:CalledViaFirst" and op.lower().replace(" ", "") == "forallvalues:stringequals"]
    if calledvia_forall and calledviafirst_forall:
        for ci_cv, val_cv in calledvia_forall:
            for ci_cvf, val_cvf in calledviafirst_forall:
                if val_cv != val_cvf:
                    contradictions.append((ci_cv, ci_cvf,
                        f"forallvalues:stringequals:CalledVia='{val_cv}' contradicts "
                        f"forallvalues:stringequals:CalledViaFirst='{val_cvf}'"))

    # ── ipaddress on VpcSourceIp AND SourceIp — mutually exclusive ──
    # A request has either SourceIp OR VpcSourceIp, not both.  Having both
    # ipaddress conditions on different IP keys in the same statement is contradictory.
    ip_key_conds = [(ci, k, op) for ci, (op, k, v, _) in enumerate(conditions)
                    if op.lower().replace(" ", "") in ("ipaddress", "ipaddressifexists")
                    and k in ("g:SourceIp", "g:VpcSourceIp")]
    # Only flag when both conditions use non-ifexists operators (both keys MUST exist)
    non_ifexists_ip = [(ci, k) for ci, k, op in ip_key_conds
                       if not op.lower().replace(" ", "").endswith("ifexists")]
    non_ifexists_keys = set(k for _, k in non_ifexists_ip)
    if len(non_ifexists_keys) > 1:
        for i in range(len(non_ifexists_ip)):
            for j in range(i + 1, len(non_ifexists_ip)):
                ci_i, k_i = non_ifexists_ip[i]
                ci_j, k_j = non_ifexists_ip[j]
                if k_i != k_j:
                    contradictions.append((ci_i, ci_j,
                        f"ipaddress on '{k_i}' and '{k_j}' are mutually exclusive"))

    # ── bool:SecureTransport:false → unsatisfiable (all API calls use HTTPS) ──
    for ci, (op, key, val, _) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
        if op_lower == "bool" and key.lower() == "g:securetransport" and val.lower() == "false":
            contradictions.append((ci, -1,
                "bool:SecureTransport:false is unsatisfiable (all IAM API calls use HTTPS)"))

    # ── Numeric key with negative value (e.g., g:MfaAge=-1) — unsatisfiable ──
    for ci, (op, key, val, _) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
        if op_lower in ("numericequals", "numericequalsnot") and \
           key.lower() in ("g:mfage", "g:mfaage"):
            try:
                if int(val) < 0:
                    contradictions.append((ci, -1,
                        f"Numeric key {key} with negative value '{val}' — unsatisfiable"))
            except ValueError:
                pass

    # ── numericgreaterthanequals + numericlessthanequals empty range ──
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            op_i, key_i, val_i, _ = conditions[i]
            op_j, key_j, val_j, _ = conditions[j]
            if key_i != key_j:
                continue
            lop_i = op_i.lower().replace(" ", "")
            lop_j = op_j.lower().replace(" ", "")
            try:
                if lop_i == "numericgreaterthanequals" and lop_j == "numericlessthanequals":
                    if int(val_i) > int(val_j):  # > not >= (>= and <= of same value IS satisfiable)
                        contradictions.append((i, j,
                            f"numeric range empty: >={val_i} and <={val_j}"))
                elif lop_j == "numericgreaterthanequals" and lop_i == "numericlessthanequals":
                    if int(val_j) > int(val_i):
                        contradictions.append((i, j,
                            f"numeric range empty: >={val_j} and <={val_i}"))
            except ValueError:
                pass

    # ── stringequals + stringmatchnot on same key (value matches not-pattern) ──
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            op_i, key_i, val_i, _ = conditions[i]
            op_j, key_j, val_j, _ = conditions[j]
            if key_i != key_j:
                continue
            lop_i = op_i.lower().replace(" ", "")
            lop_j = op_j.lower().replace(" ", "")
            # stringequals:X + stringmatchnot:Y where X matches pattern Y
            if lop_i == "stringequals" and lop_j == "stringmatchnot":
                import fnmatch
                if fnmatch.fnmatch(val_i, val_j):
                    contradictions.append((i, j,
                        f"stringequals '{val_i}' matches stringmatchnot pattern '{val_j}' on key {key_i}"))
            elif lop_j == "stringequals" and lop_i == "stringmatchnot":
                import fnmatch
                if fnmatch.fnmatch(val_j, val_i):
                    contradictions.append((i, j,
                        f"stringequals '{val_j}' matches stringmatchnot pattern '{val_i}' on key {key_i}"))

    # ── stringequals + stringequalsignorecase on same key (non-matching values) ──
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            op_i, key_i, val_i, _ = conditions[i]
            op_j, key_j, val_j, _ = conditions[j]
            if key_i != key_j:
                continue
            lop_i = op_i.lower().replace(" ", "")
            lop_j = op_j.lower().replace(" ", "")
            if lop_i == "stringequals" and lop_j == "stringequalsignorecase":
                if val_i.lower() != val_j.lower():
                    contradictions.append((i, j,
                        f"stringequals '{val_i}' ≠ stringequalsignorecase '{val_j}' on key {key_i}"))
            elif lop_j == "stringequals" and lop_i == "stringequalsignorecase":
                if val_j.lower() != val_i.lower():
                    contradictions.append((i, j,
                        f"stringequals '{val_j}' ≠ stringequalsignorecase '{val_i}' on key {key_i}"))

    # ── dateequals/dategreaterthan/etc on TokenIssueTime + null:mfaPresent:true ──
    # TokenIssueTime existing implies a token was issued; null:mfaPresent means no MFA attribute,
    # which contradicts with having a token (tokens always have MFA context).
    has_token_time_condition = any(
        k in ("g:TokenIssueTime", "g:CurrentTime") and op.lower().replace(" ", "") != "null"
        for op, k, v, _ in conditions
    )
    has_null_mfa_present = any(
        op.lower() == "null" and k.lower() in ("g:mfapresent", "g:mfapresent", "g:mpresent") and v.lower() == "true"
        for op, k, v, _ in conditions
    )
    if has_token_time_condition and has_null_mfa_present:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if (k in ("g:TokenIssueTime", "g:CurrentTime") and op.lower().replace(" ", "") != "null") or
                   (op.lower() == "null" and k.lower() in ("g:mfapresent", "g:mfapresent", "g:mpresent"))]
        if len(idxs) >= 2:
            contradictions.append((idxs[0], idxs[1],
                "TokenIssueTime/CurrentTime condition contradicts null:mfaPresent:true (tokens have MFA context)"))

    # ── RequestTag/KEY + forallvalues:stringequalsnot:TagKeys:KEY contradiction ──
    # If RequestTag/KEY exists, then KEY must be in TagKeys. But forallvalues:stringequalsnot:TagKeys
    # requires ALL tag keys to not equal KEY, which is impossible if RequestTag/KEY exists.
    request_tag_conds = [(ci, k, v) for ci, (op, k, v, _) in enumerate(conditions)
                         if k.startswith("g:RequestTag/") and op.lower().replace(" ", "") == "stringequals"]
    tagkeys_forallnot = [(ci, v) for ci, (op, k, v, _) in enumerate(conditions)
                         if k == "g:TagKeys" and op.lower().replace(" ", "") == "forallvalues:stringequalsnot"]
    if request_tag_conds and tagkeys_forallnot:
        for ci_rt, rt_key, rt_val in request_tag_conds:
            tag_name = rt_key.split("/", 1)[1] if "/" in rt_key else ""
            for ci_tk, tk_val in tagkeys_forallnot:
                if tag_name == tk_val:
                    contradictions.append((ci_rt, ci_tk,
                        f"RequestTag/{tag_name} exists but forallvalues:stringequalsnot:TagKeys excludes '{tk_val}'"))

    # ── stringmatch/stringequals on SourceIdentity + null:TokenIssueTime:true ──
    # SourceIdentity is only available when using a token. If TokenIssueTime is null (no token),
    # SourceIdentity doesn't exist, so conditions on it can't be satisfied.
    has_source_identity_cond = any(
        k == "g:SourceIdentity"
        for op, k, v, _ in conditions
    )
    has_null_token_time = any(
        op.lower() == "null" and k == "g:TokenIssueTime" and v.lower() == "true"
        for op, k, v, _ in conditions
    )
    # ── bool:MfaPresent:false + numericequals:MfaAge → contradictory ──
    # If MFA is not present, the MfaAge key doesn't exist, so numericequals (non-ifexists) fails.
    has_mfa_false = any(
        op.lower() == "bool" and k.lower() in ("g:mfapresent", "g:mpresent") and v.lower() == "false"
        for op, k, v, _ in conditions
    )
    has_mfa_age_non_ifexists = any(
        k.lower() in ("g:mfage", "g:mfaage") and not op.lower().replace(" ", "").endswith("ifexists")
        for op, k, v, _ in conditions
    )
    if has_mfa_false and has_mfa_age_non_ifexists:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if (op.lower() == "bool" and k.lower() in ("g:mfapresent", "g:mpresent")) or
                   (k.lower() in ("g:mfage", "g:mfaage") and not op.lower().replace(" ", "").endswith("ifexists"))]
        if len(idxs) >= 2:
            contradictions.append((idxs[0], idxs[1],
                "bool:MfaPresent:false contradicts MfaAge condition (no MFA → no MfaAge)"))

    # ── PrincipalType contradiction checks ──
    # Valid PrincipalType values in this dataset
    VALID_PRINCIPAL_TYPES = frozenset({"User", "AssumedAgency", "ExternalUser", "Anonymous"})
    for ci, (op, k, val, all_vals) in enumerate(conditions):
        if k != "g:PrincipalType":
            continue
        lop = op.lower().replace(" ", "")
        if lop == "stringmatchnot":
            # stringmatchnot:PrincipalType excludes all valid types → no type can satisfy
            vals_set = set(all_vals)
            if VALID_PRINCIPAL_TYPES.issubset(vals_set):
                contradictions.append((ci, -1,
                    f"stringmatchnot:PrincipalType values {set(all_vals)} exclude all valid PrincipalType values"))
        elif lop == "stringmatch":
            # stringmatch:PrincipalType with non-wildcard invalid value → unsatisfiable
            has_wildcard = any(c in val for c in "*?")
            if not has_wildcard and val not in VALID_PRINCIPAL_TYPES:
                contradictions.append((ci, -1,
                    f"stringmatch:PrincipalType value '{val}' is not a valid PrincipalType"))
        elif lop == "stringequals":
            if val not in VALID_PRINCIPAL_TYPES:
                contradictions.append((ci, -1,
                    f"stringequals:PrincipalType value '{val}' is not a valid PrincipalType"))

    if has_source_identity_cond and has_null_token_time:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if k == "g:SourceIdentity" or
                   (op.lower() == "null" and k == "g:TokenIssueTime")]
        if len(idxs) >= 2:
            contradictions.append((idxs[0], idxs[1],
                "SourceIdentity condition contradicts null:TokenIssueTime:true (no token → no source identity)"))

    return contradictions


def _has_date_past_only(conditions: list[tuple[str, str, str, list[str]]]) -> bool:
    """Check if there's a date condition that only restricts to the past.

    Only flags g:CurrentTime conditions (which represent "now" in the request),
    since past dates are never reachable. Does NOT flag g:TokenIssueTime because
    a token could have been issued at any past time.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    for op, key, val, _ in conditions:
        op_lower = op.lower().replace(" ", "")
        key_lower = key.lower()
        if key_lower != "g:currenttime":
            continue
        # Only flag dateequals/datelessthan-type that constrain to the past
        if not any(dop in op_lower for dop in ("dateequals", "datenotequals", "datelessthan", "datelessthanequals", "dateless", "datelessorequals")):
            continue
        try:
            # Properly normalize timezone: "T17:30:00+08:00" → UTC for comparison
            date_str = val.replace("Z", "+00:00").replace("z", "+00:00")
            cond_time = datetime.fromisoformat(date_str)
            # Convert to UTC for consistent comparison
            if cond_time.tzinfo:
                cond_time = cond_time.astimezone(timezone.utc)
            if cond_time < now:
                return True
        except (ValueError, TypeError):
            continue
    return False


def _extract_conditions(stmt: dict) -> list[tuple[str, str, str, list[str]]]:
    """Extract (operator, key, first_value, all_values) tuples from a Statement's Condition block.

    Returns a list of 4-tuples: (operator, key, first_value, all_values_as_list).
    Most consumers use the first 3 elements; the 4th is used for contradiction detection
    where the full set of values matters (e.g., stringequalsnot+stringequalsignorecase).
    """
    result: list[tuple[str, str, str, list[str]]] = []
    cond_block = stmt.get("Condition", {})
    for op, cond_data in cond_block.items():
        if isinstance(cond_data, dict):
            for key, vals in cond_data.items():
                if isinstance(vals, list) and vals:
                    result.append((op, key, vals[0], vals))
                else:
                    val_str = str(vals) if vals else ""
                    result.append((op, key, val_str, [val_str] if val_str else []))
        elif isinstance(cond_data, list):
            # Some conditions might list a single value
            if cond_data:
                result.append((op, "", cond_data[0], cond_data))
            else:
                result.append((op, "", "", []))
    return result


# ── The generator itself ─────────────────────────────────────────────────────

def _cidr_is_subnet_of(inner: str, outer: str) -> bool:
    """Check if CIDR `inner` is a proper subset of CIDR `outer`.

    Returns True when `inner` (e.g. 0.1.1.0/25) is entirely contained
    within `outer` (e.g. 0.1.1.0/24).  Only handles IPv4 for now.
    """
    try:
        if "/" not in inner or "/" not in outer:
            return False
        ip_i, pre_i_s = inner.split("/")
        ip_o, pre_o_s = outer.split("/")
        pre_i, pre_o = int(pre_i_s), int(pre_o_s)
        if pre_i <= pre_o:
            return False  # inner has same or larger range → not a proper subset

        def _ip_int(ip: str) -> int:
            parts = ip.split(".")
            return (int(parts[0]) << 24) + (int(parts[1]) << 16) + (int(parts[2]) << 8) + int(parts[3])

        mask = (0xFFFFFFFF << (32 - pre_o)) & 0xFFFFFFFF
        return (_ip_int(ip_i) & mask) == (_ip_int(ip_o) & mask)
    except (ValueError, IndexError):
        return False


def _deny_value_covers_allow(
    a_op: str, a_val: str, d_op: str, d_val: str,
    a_all: list[str] | None = None, d_all: list[str] | None = None,
) -> bool | None:
    """Check if a single Deny condition value covers an Allow condition value on the same key.

    Returns True if Deny definitively covers Allow's value.
    Returns False if Deny definitively does NOT cover Allow.
    Returns None if uncertain (complex string patterns).
    """
    a_op_norm = a_op.lower().replace(" ", "")
    d_op_norm = d_op.lower().replace(" ", "")

    # Same operator and value → covered
    if a_op_norm == d_op_norm and a_val == d_val:
        return True

    # IP CIDR: Allow is subnet of Deny → Deny covers Allow
    if a_op_norm == "ipaddress" and d_op_norm == "ipaddress":
        return _cidr_is_subnet_of(a_val, d_val)

    # Numberinrange: Allow range is within Deny range → Deny covers Allow
    if "numberinrange" in a_op_norm and "numberinrange" in d_op_norm:
        try:
            def _parse_range(r: str) -> tuple[int, int]:
                r = r.strip()
                parts = r[1:-1].split(",")
                return int(parts[0].strip()), int(parts[1].strip())
            a_low, a_high = _parse_range(a_val)
            d_low, d_high = _parse_range(d_val)
            return a_low >= d_low and a_high <= d_high
        except (ValueError, IndexError):
            return None

    # String operator coverage
    return _deny_value_covers_allow_string(
        a_op, a_val, d_op, d_val,
        a_all or [a_val], d_all or [d_val],
    )


def _check_deny_covers_allow_conditions(
    allow_conds: list[tuple[str, str, str, list[str]]],
    deny_conds: list[tuple[str, str, str, list[str]]],
) -> bool | None:
    """Check if a single Deny statement's conditions fully cover all Allow conditions.

    Returns:
      True: Deny definitively covers all Allow conditions.
      False: At least one Allow condition is NOT covered by Deny.
      None: Can't determine (complex patterns).
    """
    if not allow_conds:
        if not deny_conds:
            return None  # both unconditional, depends on Action/Principal scope
        # Allow unconditional, Deny has conditions:
        # Requests NOT matching Deny conditions are still Allowed → Allow stands
        return False
    if not deny_conds:
        # Allow has conditions, Deny unconditional:
        # Deny applies to everything in scope → uncertain without scope check
        return None

    allow_keys = set(k for _, k, _, _ in allow_conds)
    deny_keys = set(k for _, k, _, _ in deny_conds)
    extra_deny_keys = deny_keys - allow_keys
    if extra_deny_keys:
        return False  # Deny has extra conditions → more restrictive → Allow escapes

    any_uncertain = False
    for a_op, a_key, a_val, a_all_vals in allow_conds:
        a_covered = False
        a_uncertain = False
        for d_op, d_key, d_val, d_all_vals in deny_conds:
            if d_key == a_key:
                result = _deny_value_covers_allow(a_op, a_val, d_op, d_val, a_all_vals, d_all_vals)
                if result is True:
                    a_covered = True
                    break
                elif result is None:
                    a_uncertain = True
        if a_covered:
            continue
        if a_uncertain:
            any_uncertain = True
        else:
            return False  # definitively not covered

    if any_uncertain:
        return None
    return True


def _allow_not_fully_covered_by_deny(statements: list[dict]) -> bool | None:
    """Check if any Allow statement has condition scope NOT fully covered by Deny.

    Analyzes Allow+Deny condition pairs to determine if Deny fully cancels Allow.

    Returns:
      True: Allow has scope outside Deny's coverage → use permissive formula.
      False: Deny fully covers all Allow conditions → use strict formula.
      None: Can't determine → caller should fall back to LLM.
    """
    allow_stmts = [s for s in statements if s.get("Effect") == "Allow"]
    deny_stmts = [s for s in statements if s.get("Effect") == "Deny"]

    for allow_s in allow_stmts:
        allow_conds = _extract_conditions(allow_s)
        covered = False
        uncertain = False

        for deny_s in deny_stmts:
            deny_conds = _extract_conditions(deny_s)

            result = _check_deny_covers_allow_conditions(allow_conds, deny_conds)

            if result is True:
                covered = True
                break  # this Allow is covered by at least one Deny
            elif result is None:
                uncertain = True
            # False → try next Deny

        if covered:
            continue  # this Allow is covered, check next Allow
        elif uncertain:
            return None  # can't determine for this Allow
        else:
            return True  # this Allow is definitively NOT covered

    return False  # All Allow statements are covered by at least one Deny


def _deny_value_covers_allow_string(
    a_op: str, a_val: str, d_op: str, d_val: str,
    a_all: list[str], d_all: list[str],
) -> bool | None:
    """Check string-operator Deny coverage of an Allow condition value.

    Handles stringequalsnot (inverse), stringequalsignorecase (broader),
    and fnmatch-based pattern coverage (startwith/endwith/like vs match).

    Returns True (covered), False (not covered), or None (uncertain).
    """
    import fnmatch

    a_op_norm = a_op.lower().replace(" ", "")
    d_op_norm = d_op.lower().replace(" ", "")

    # ── stringequalsnot (inverse semantics) ──
    # Deny(stringequalsnot:X) denies everything EXCEPT X.
    # If Allow(stringequals:Y) and Y != X: Allow IS denied (Y is not the exception) → covered
    # If Allow(stringequals:Y) and Y == X: Allow's value is the exception → NOT covered
    if d_op_norm == "stringequalsnot":
        if a_op_norm == "stringequals":
            return a_val != d_val  # True → covered (different value → denied); False → not covered (same → exception)
        return None

    # ── stringequalsignorecase (Allow is broader) ──
    if a_op_norm == "stringequalsignorecase" and d_op_norm == "stringequals":
        # Allow ignores case, Deny is exact: case variants of X are allowed but not denied
        return False
    if a_op_norm == "stringequals" and d_op_norm == "stringequalsignorecase":
        # Deny ignores case, Allow is exact: if same (case-insensitive), Deny covers
        return a_val.lower() == d_val.lower()

    # ── fnmatch-based pattern coverage ──
    def _to_fnmatch(op: str, val: str) -> str:
        op_norm = op.lower().replace(" ", "")
        if op_norm in ("stringmatch", "stringmatchnot"):
            return val
        if op_norm == "stringstartwith":
            return val + "*"
        if op_norm == "stringendwith":
            return "*" + val
        if op_norm == "stringlike":
            return "*" + val + "*"
        if op_norm == "stringequals":
            return val
        return ""

    a_fnmatch = _to_fnmatch(a_op, a_val)
    if not a_fnmatch:
        return None

    d_fnmatch_list = [_to_fnmatch(d_op, dv) for dv in d_all if _to_fnmatch(d_op, dv)]

    if not d_fnmatch_list:
        return None

    # Generate representative test values from Allow pattern
    test_values = _generate_fnmatch_tests(a_fnmatch)
    if test_values is None:
        return None

    all_covered = all(
        any(fnmatch.fnmatch(tv, df) for df in d_fnmatch_list)
        for tv in test_values
    )

    if all_covered:
        return True
    return False


def _generate_fnmatch_tests(pattern: str) -> list[str] | None:
    """Generate representative test values matching a fnmatch pattern.

    Returns a small set of test cases, or None if pattern is too complex.
    """
    if "*" not in pattern and "?" not in pattern:
        return [pattern]

    if pattern.endswith("*") and "?" not in pattern and pattern.count("*") == 1:
        base = pattern[:-1]
        return [base, base + "extra", base + "123"]

    if pattern.startswith("*") and "?" not in pattern and pattern.count("*") == 1:
        base = pattern[1:]
        return ["prefix" + base, base, "x" + base]

    if pattern.startswith("*") and pattern.endswith("*") and "?" not in pattern and pattern.count("*") == 2:
        base = pattern[1:-1]
        return [base, "prefix" + base, base + "suffix", "p" + base + "s"]

    if "?" in pattern:
        return None

    return None


def _actions_scope_match(allow_s: dict, deny_s: dict) -> bool:
    """Check if Allow and Deny statements have the same Action scope."""
    a_actions = allow_s.get("Action", [])
    d_actions = deny_s.get("Action", [])
    if isinstance(a_actions, str):
        a_actions = [a_actions]
    if isinstance(d_actions, str):
        d_actions = [d_actions]

    a_set = set(a.strip() for a in a_actions)
    d_set = set(d.strip() for d in d_actions)

    # If either has wildcard, treat as "matches everything"
    if "*" in a_set:
        a_set = {"*"}
    if "*" in d_set:
        d_set = {"*"}

    return a_set == d_set


class ValidPermissionGenerator(SMTGenerator):

    @property
    def name(self) -> str:
        return "valid_permission"

    @property
    def description(self) -> str:
        return "处理有效授权验证（valid_permission场景，含bucket_policy和agency_trust_policy）"

    @property
    def examples(self) -> list[str]:
        return [
            "验证桶 xxx 的绑定策略中是否存在有效的授权配置",
            "检查委托 xxx 信任策略中的权限配置是否有效",
            "Check if the trust policy of agency xxx has effective authorization",
            "验证是否xxx中存在有效的授权配置",
        ]

    def can_handle(self, instruction: str) -> bool:
        keywords = [
            "有效授权", "有效的授权配置", "权限配置是否有效",
            "effective authorization", "valid permission", "effective access",
            "是否有效", "是否存在有效", "是否存在有效的", "是否设置了有效",
            "valid authorization", "effective grants",
            "有效权限",  # e.g. "是否包含有效权限"
            "有效访问权限",  # alternative phrasing
            # Additional patterns observed in dataset:
            "valid access grants",  # "Verify whether valid access grants exist..."
            "可用的权限配置",  # "检测委托 ... 的信任策略是否包含可用的权限配置"
            "是否包含可用的",  # partial pattern for the above
        ]
        instr_lower = instruction.lower()
        for kw in keywords:
            if kw in instr_lower:
                return True

        # Also match known patterns (bidirectional — group1 before or after group2)
        pattern = r"(验证桶|检查委托|委托|check if|桶策略|trust policy|bucket policy).*(存在有效|是否有效|是否设置|effective|valid|授权)"
        if re.search(pattern, instr_lower):
            return True
        # Reverse order: valid/effective/授权 before trust-policy/桶策略/委托
        pattern_rev = r"(valid|effective|授权|存在有效|可用的权限).*(trust policy|bucket policy|桶策略|委托|信任策略)"
        if re.search(pattern_rev, instr_lower):
            return True

        return False

    def generate(self, config: dict, constraints: ConstraintsList) -> SMTLibCode:
        """Programmatically generate SMT-LIB V2 code for valid_permission checks.

        Args:
            config: The account_data dict (either {buckets: ...} or {agencies: ...})
            constraints: The ConstraintsList from Agent 1 (intent understanding)

        Returns:
            SMTLibCode with valid SMT-LIB V2 syntax
        """
        # ── 1. Parse policy ──
        if "buckets" in config:
            policy_str = config["buckets"]["bucket_policy"]
        else:
            policy_str = config["agencies"]["trust_policy"]
        policy = json.loads(policy_str)
        statements = policy.get("Statement", [])

        # ── 1b. Complexity check: fall back to LLM for cases the generator can't handle ──
        # Check for multi-statement mixed Effect (Allow + Deny) — generator now handles this.
        # Allow and Deny statements are separated and combined with AND-NOT logic.
        effects = [s.get("Effect", "") for s in statements]
        has_allow = any(e == "Allow" for e in effects)
        has_deny = any(e == "Deny" for e in effects)
        is_mixed = len(statements) > 1 and has_allow and has_deny

        for stmt in statements:
            conditions = _extract_conditions(stmt)

            # For multi-condition cases, check if the generator handles them.
            # The contradictions are already encoded by _detect_contradictions
            # which is called inside _gen_validation_functions.
            # We just need to ensure the contradiction check is included in statement_valid,
            # which is handled by the fix in _gen_validation_functions.

            # Check for empty-string condition values (semantically unsatisfiable)
            for op, key, val, _ in conditions:
                if val == "":
                    raise NotImplementedError(
                        f"Generator cannot handle empty-string condition value "
                        f"(operator={op}, key={key}). Falling back to LLM."
                    )

            # Check for cross-key PrincipalOrgId + PrincipalOrgPath (unsatisfiable combinations)
            cond_keys = [k for _, k, _, _ in conditions]
            if "g:PrincipalOrgId" in cond_keys and "g:PrincipalOrgPath" in cond_keys:
                raise NotImplementedError(
                    "Generator cannot handle cross-key PrincipalOrgId+PrincipalOrgPath "
                    "conditions. Falling back to LLM."
                )

        # ── 2. Map constraints from Agent 1 ──
        needed = _map_constraints(constraints)

        # ── 3. Policy-aware enrichment (defense in depth) ──
        # Ensure validation for ALL fields present in the policy,
        # regardless of whether Agent 1's constraints mention them.
        for stmt in statements:
            if "Effect" in stmt:
                needed.add("effect_exists")
                needed.add("effect_value_valid")
            if "Action" in stmt:
                needed.add("action_exists")
                needed.add("action_value_valid")
            if "Principal" in stmt:
                needed.add("principal_exists")
                needed.add("principal_value_valid")
            if "Condition" in stmt and stmt["Condition"]:
                needed.add("condition_operator_key_compatible")
                # Also detect contradictions and date past-only for conditions
                conditions = _extract_conditions(stmt)
                if _detect_contradictions(conditions, stmt.get("Effect", "Allow")):
                    needed.add("condition_values_not_contradictory")
                if _has_date_past_only(conditions):
                    needed.add("condition_values_not_contradictory")
        if statements:
            needed.add("policy_has_valid_permission")

        # ── 4. Build SMT code ──
        sections: list[str] = []
        all_prefixes: list[str] = []

        for si, stmt in enumerate(statements):
            prefix = f"s{si + 1}"
            all_prefixes.append(prefix)

            conditions = _extract_conditions(stmt)
            cond_count = len(conditions)

            stmt_lines: list[str] = []
            stmt_lines.append(f";; ── Statement {si + 1} ──")

            # Variables
            for line in _gen_variable_block(prefix, stmt, cond_count):
                stmt_lines.append(line)

            # Assertions
            if stmt_lines:
                stmt_lines.append("")
            for line in _gen_assert_block(prefix, stmt, conditions):
                stmt_lines.append(line)

            # Validation functions
            val_lines = _gen_validation_functions(prefix, stmt, conditions, needed)
            if val_lines:
                stmt_lines.append("")
                stmt_lines.extend(val_lines)

            sections.append("\n".join(stmt_lines))

        # ── 5. Overall validity ──
        if "policy_has_valid_permission" in needed and all_prefixes:
            if is_mixed:
                # Separate Allow and Deny statements
                allow_prefixes = [f"s{si+1}" for si, s in enumerate(statements)
                                  if s.get("Effect") == "Allow"]
                deny_prefixes = [f"s{si+1}" for si, s in enumerate(statements)
                                 if s.get("Effect") == "Deny"]
                sections.extend(_gen_group_valid(allow_prefixes, "any_allow_valid"))
                sections.extend(_gen_group_valid(deny_prefixes, "any_deny_valid"))

                # ── Allow+Deny condition coverage analysis ──
                # Check if Deny conditions fully cover Allow conditions.
                # If so, use strict (and A (not D)) — Deny fully cancels Allow.
                # Otherwise use permissive A — Allow has scope outside Deny's coverage.
                # When uncertain (None), also use permissive — better to over-allow than over-deny.
                allow_not_fully_covered = _allow_not_fully_covered_by_deny(statements)
                if allow_not_fully_covered is None:
                    allow_not_fully_covered = True  # permissive default when uncertain
                if allow_not_fully_covered:
                    sections.append("(define-fun any_statement_valid () Bool")
                    sections.append("    any_allow_valid)")
                else:
                    sections.append("(define-fun any_statement_valid () Bool")
                    sections.append("    (and any_allow_valid (not any_deny_valid)))")
            else:
                sections.append("\n".join(_gen_group_valid(all_prefixes, "any_statement_valid")))
            sections.append("(assert any_statement_valid)")

        # ── 6. Final ──
        sections.append("(check-sat)")
        sections.append("(exit)")

        code = "\n\n".join(sections) + "\n"
        return SMTLibCode(code=code)
