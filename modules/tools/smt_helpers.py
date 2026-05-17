"""SMT-LIB V2 辅助函数：操作符/键类型分类、矛盾检测等。

从 generators/builtin_valid_permission.py 提取，
删除 generator 模块后保留给 smt_tools.py 使用。
"""

from __future__ import annotations

from typing import Any

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
    if key.startswith(STRING_KEY_PREFIXES):
        return "string"
    if key in STRING_KEYS:
        return "string"
    return "string"


def _smt_escape(val: str) -> str:
    return f'"{val}"'


def _extract_conditions(stmt: dict) -> list[tuple[str, str, str, list[str]]]:
    """Extract (operator, key, first_value, all_values) tuples from a Statement's Condition block."""
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
            if cond_data:
                result.append((op, "", cond_data[0], cond_data))
            else:
                result.append((op, "", "", []))
    return result


def _detect_contradictions(conditions: list[tuple[str, str, str, list[str]]], effect: str = "Allow") -> list[tuple[int, int, str]]:
    """Detect contradictory condition pairs.

    Args:
        conditions: List of (operator, key, value, all_values) tuples.
        effect: The statement Effect ("Allow" or "Deny").

    Returns list of (idx1, idx2, reason) for each contradictory pair.
    """
    contradictions: list[tuple[int, int, str]] = []

    # Single-condition contradiction: numberinrange with empty range
    for ci, (op, key, val, _) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
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

                # stringmatch + stringmatchnot on same value
                if (_is(op_i, "stringmatch") and _is(op_j, "stringmatchnot")) or \
                   (_is(op_j, "stringmatch") and _is(op_i, "stringmatchnot")):
                    if val_i == val_j:
                        contradictions.append((ci_i, ci_j, f"stringmatch+stringmatchnot same value '{val_i}'"))

                # numericgreaterthan N + numericlessthan M with gap
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

                # forallvalues + foranyvalue on same key with different values
                if ("forallvalues:stringequals" in lop_i and "foranyvalue:stringequals" in lop_j) or \
                   ("foranyvalue:stringequals" in lop_i and "forallvalues:stringequals" in lop_j):
                    if val_i != val_j:
                        contradictions.append((ci_i, ci_j, f"ForAllValues '{val_i}' ≠ ForAnyValue '{val_j}'"))

                # dategreaterthan T + datelessthan T (same instant, different tz)
                if (lop_i == "dategreaterthan" and lop_j == "datelessthan") or \
                   (lop_j == "dategreaterthan" and lop_i == "datelessthan"):
                    gt = val_i if lop_i == "dategreaterthan" else val_j
                    lt = val_j if lop_j == "datelessthan" else val_i

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

    # Cross-key: null:INVALID_KEY in Deny
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

    # null:ServiceAgency=false + g:PrincipalType=User
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

    # ServiceAgency + PrincipalUrn cross-key contradiction
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

        if "*:user:*" in pu_val or "*:user" in pu_val:
            contradictions.append((sa_ci, pu_ci,
                f"ServiceAgency match '{sa_val}' contradicts PrincipalUrn IAM user pattern '{pu_val}'"))
        elif "assumed-agency:" in pu_val:
            path = pu_val.split("assumed-agency:", 1)[1]
            agency_name = path.split("/")[0] if "/" in path else path
            if agency_name:
                import fnmatch
                if not fnmatch.fnmatch(agency_name, sa_val):
                    contradictions.append((sa_ci, pu_ci,
                        f"ServiceAgency pattern '{sa_val}' does not match PrincipalUrn agency '{agency_name}'"))

    # ipaddressnot with both 0.0.0.0/0 AND ::/0
    for ci, (op, k, v, all_vals) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
        if op_lower in ("ipaddressnot", "ipaddressnotifexists"):
            vals_set = set(vv.strip() for vv in all_vals)
            if "0.0.0.0/0" in vals_set and "::/0" in vals_set:
                contradictions.append((ci, -1,
                    "ipaddressnot with both 0.0.0.0/0 and ::/0 covers all IPs — never satisfiable"))

    # bool:PrincipalIsRootUser=true + PrincipalType=AssumedAgency
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

    # PrincipalType=AssumedAgency + null:TokenIssueTime=true
    has_null_token_time = any(
        op.lower() == "null" and k == "g:TokenIssueTime" and v.lower() == "true"
        for op, k, v, _ in conditions
    )
    if has_principal_type_assumed_agency and has_null_token_time:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if k == "g:PrincipalType" or
                   (op.lower() == "null" and k == "g:TokenIssueTime")]
        contradictions.append((idxs[0], idxs[1],
            "PrincipalType=AssumedAgency contradicts null:TokenIssueTime=true"))

    # PrincipalTag/RequestTag/ResourceTag + null:ViaService=true
    has_null_via_service = any(
        op.lower() == "null" and k == "g:ViaService" and v.lower() == "true"
        for op, k, v, _ in conditions
    )
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
            "null:ViaService=true contradicts tag key condition"))

    # bool:SecureTransport:false
    for ci, (op, key, val, _) in enumerate(conditions):
        op_lower = op.lower().replace(" ", "")
        if op_lower == "bool" and key.lower() == "g:securetransport" and val.lower() == "false":
            contradictions.append((ci, -1,
                "bool:SecureTransport:false is unsatisfiable (all IAM API calls use HTTPS)"))

    # Numeric key with negative value
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

    # numericgreaterthanequals + numericlessthanequals empty range
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
                    if int(val_i) > int(val_j):
                        contradictions.append((i, j, f"numeric range empty: >={val_i} and <={val_j}"))
                elif lop_j == "numericgreaterthanequals" and lop_i == "numericlessthanequals":
                    if int(val_j) > int(val_i):
                        contradictions.append((i, j, f"numeric range empty: >={val_j} and <={val_i}"))
            except ValueError:
                pass

    # stringequals + stringmatchnot on same key (value matches not-pattern)
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            op_i, key_i, val_i, _ = conditions[i]
            op_j, key_j, val_j, _ = conditions[j]
            if key_i != key_j:
                continue
            lop_i = op_i.lower().replace(" ", "")
            lop_j = op_j.lower().replace(" ", "")
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

    # stringequals + stringequalsignorecase (non-matching values)
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

    # stringequalsnot + stringequalsignorecase on same key
    for i in range(len(conditions)):
        for j in range(i + 1, len(conditions)):
            op_i, key_i, val_i, all_i = conditions[i]
            op_j, key_j, val_j, all_j = conditions[j]
            if key_i != key_j:
                continue

            def _is(op_str: str, target: str) -> bool:
                bare = op_str.replace("forallvalues:", "").replace("foranyvalue:", "")
                return bare == target

            if (_is(op_i, "stringequalsnot") and _is(op_j, "stringequalsignorecase")) or \
               (_is(op_j, "stringequalsnot") and _is(op_i, "stringequalsignorecase")):
                not_vals = all_i if _is(op_i, "stringequalsnot") else all_j
                icase_vals = all_j if _is(op_i, "stringequalsnot") else all_i

                not_set = set(not_vals)
                for icv in icase_vals:
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

                    if len(icv) <= 4:
                        variants = _all_ascii_case_variants(icv)
                        if variants and variants.issubset(not_set):
                            contradictions.append((i, j,
                                f"stringequalsnot '{not_vals}' excludes all case variants of "
                                f"stringequalsignorecase '{icv}' on key {key_i}"))
                            break

    # Bool:false missing unsatisfiable conditions
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

    # stringmatch/stringequals on SourceIdentity + null:TokenIssueTime:true
    has_source_identity_cond = any(
        k == "g:SourceIdentity" for op, k, v, _ in conditions
    )
    if has_source_identity_cond and has_null_token_time:
        idxs = [ci for ci, (op, k, v, _) in enumerate(conditions)
                if k == "g:SourceIdentity" or
                   (op.lower() == "null" and k == "g:TokenIssueTime")]
        if len(idxs) >= 2:
            contradictions.append((idxs[0], idxs[1],
                "SourceIdentity condition contradicts null:TokenIssueTime:true (no token → no source identity)"))

    return contradictions


def _has_date_past_only(conditions: list[tuple[str, str, str, list[str]]]) -> bool:
    """Check if date conditions restrict entirely to the past (unsatisfiable)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    for op, key, val, _ in conditions:
        if key not in ("g:CurrentTime", "g:TokenIssueTime"):
            continue
        op_lower = op.lower().replace(" ", "")
        if op_lower in ("datelessthan", "datelessthanequals", "dateless", "datelessorequals"):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00").replace("z", "+00:00"))
                if dt.tzinfo:
                    dt = dt.astimezone(timezone.utc)
                if dt < now:
                    return True
            except (ValueError, TypeError):
                pass
        if op_lower in ("dateequals", "dateequalsnot"):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00").replace("z", "+00:00"))
                if dt.tzinfo:
                    dt = dt.astimezone(timezone.utc)
                if dt < now:
                    return True
            except (ValueError, TypeError):
                pass
    return False
