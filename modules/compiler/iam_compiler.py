"""IAM → Z3/SMT 确定性编译器

将IAM JSON配置转换为Z3 SMT-LIB V2形式化模型。
完全确定性，无需LLM参与代码生成环节。
"""

from __future__ import annotations

import json

from z3 import Bool, BoolVal, String, StringVal, Solver, Or, And, Not, Implies

from core.schemas import SMTLibCode
from modules.tools.iam_z3_utils import (
    STRING_OPS, NUMERIC_OPS, DATE_OPS, BOOL_OPS, IP_OPS, NULL_OPS,
    STRING_KEYS, NUMERIC_KEYS, BOOL_KEYS, DATE_KEYS, IP_KEYS,
    STRING_KEY_PREFIXES,
)


class IAMCompiler:
    """Deterministic IAM JSON → SMT-LIB V2 compiler.

    Takes IAM policy JSON, builds a Z3 model, and exports SMT-LIB V2.
    No LLM involvement — fully deterministic.
    """

    _OP_CLASSES: dict[str, set[str]] = {
        "string": STRING_OPS,
        "numeric": NUMERIC_OPS,
        "date": DATE_OPS,
        "bool": BOOL_OPS,
        "ip": IP_OPS,
        "null": NULL_OPS,
    }

    _KEY_CLASSES: dict[str, tuple[set[str], tuple[str, ...]]] = {
        "string": (STRING_KEYS, STRING_KEY_PREFIXES),
        "numeric": (NUMERIC_KEYS, ()),
        "bool": (BOOL_KEYS, ()),
        "date": (DATE_KEYS, ()),
        "ip": (IP_KEYS, ()),
    }

    def compile(self, account_data: dict) -> SMTLibCode:
        """Compile IAM config to SMT-LIB V2."""
        _, statements = self._parse(account_data)
        solver = Solver()
        self._build_model(solver, statements)
        smt = solver.to_smt2().strip()
        if not smt:
            raise RuntimeError("compiler generated empty SMT-LIB V2")
        smt += "\n(exit)\n"
        return SMTLibCode(code=smt)

    # ── parsing ──

    def _parse(self, account_data: dict) -> tuple[str, list[dict]]:
        if "buckets" in account_data:
            bucket = account_data["buckets"]
            policy = json.loads(bucket.get("bucket_policy", "{}"))
            return "bucket_policy", policy.get("Statement", [])
        if "agencies" in account_data:
            agency = account_data["agencies"]
            policy = json.loads(agency.get("trust_policy", "{}"))
            return "agency_trust_policy", policy.get("Statement", [])
        raise ValueError(f"无法识别的配置格式：缺少 buckets 或 agencies")

    # ── operator / key classification (Python-level, handles prefix keys) ──

    def _classify_operator(self, op: str) -> str | None:
        op_lower = op.lower()
        for cls, ops in self._OP_CLASSES.items():
            if op_lower in ops:
                return cls
        # Multi-value operators (forallvalues:*, foranyvalue:*)
        if ":" in op_lower:
            inner = op_lower.split(":", 1)[1]
            for cls, ops in self._OP_CLASSES.items():
                if inner in ops:
                    return cls
        return None

    def _classify_key(self, key: str) -> str | None:
        for cls, (keys, prefixes) in self._KEY_CLASSES.items():
            if key in keys:
                return cls
            for p in prefixes:
                if key.startswith(p):
                    return cls
        return None

    # ── model construction ──

    def _build_model(self, solver: Solver, statements: list[dict]) -> None:
        allow_valids: list[BoolRef] = []
        deny_valids: list[BoolRef] = []

        for i, stmt in enumerate(statements):
            stmt_valid = self._encode_statement(solver, i, stmt)
            effect = stmt.get("Effect", "")
            if effect == "Allow":
                allow_valids.append(stmt_valid)
            elif effect == "Deny":
                deny_valids.append(stmt_valid)

        if allow_valids and deny_valids:
            policy_valid = And(Or(*allow_valids), Not(Or(*deny_valids)))
        elif allow_valids:
            policy_valid = Or(*allow_valids)
        elif deny_valids:
            policy_valid = BoolVal(False)
        else:
            policy_valid = BoolVal(False)

        solver.add(policy_valid)

    def _encode_statement(self, solver: Solver, i: int, stmt: dict) -> BoolRef:
        """Encode a single statement. Returns its validity BoolRef."""
        # ── Effect ──
        s_has_effect = Bool(f"s{i}_has_effect")
        s_effect_value = String(f"s{i}_effect_value")
        solver.add(s_has_effect == True)
        solver.add(s_effect_value == StringVal(stmt.get("Effect", "")))
        solver.add(Implies(s_has_effect,
            Or(s_effect_value == StringVal("Allow"), s_effect_value == StringVal("Deny"))))

        # ── Action ──
        s_has_action = Bool(f"s{i}_has_action")
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        solver.add(s_has_action == (len(actions) > 0))

        # ── Principal (presence check) ──
        principal = stmt.get("Principal", {})
        has_principal = any(v for v in principal.values() if v)
        s_has_principal = Bool(f"s{i}_has_principal")
        solver.add(s_has_principal == has_principal)

        # ── Conditions ──
        cond_block = stmt.get("Condition", {})
        s_has_condition = Bool(f"s{i}_has_condition")
        solver.add(s_has_condition == (len(cond_block) > 0))

        c_idx = 0
        for op, cond_data in cond_block.items():
            if isinstance(cond_data, dict):
                for key, vals in cond_data.items():
                    self._encode_condition(solver, i, c_idx, op, key, vals)
                    c_idx += 1
            elif isinstance(cond_data, list):
                self._encode_condition(solver, i, c_idx, op, "", cond_data)
                c_idx += 1

        return BoolVal(True)

    def _encode_condition(
        self, solver: Solver, s_idx: int, c_idx: int,
        op: str, key: str, vals,
    ) -> None:
        """Encode a single condition clause."""
        c_has = Bool(f"s{s_idx}_c{c_idx}_has")
        c_op = String(f"s{s_idx}_c{c_idx}_op")
        c_key = String(f"s{s_idx}_c{c_idx}_key")
        c_value = String(f"s{s_idx}_c{c_idx}_value")

        solver.add(c_has == True)
        solver.add(c_op == StringVal(op))
        solver.add(c_key == StringVal(key))

        first_val = str(vals[0]) if isinstance(vals, list) and vals else str(vals)
        solver.add(c_value == StringVal(first_val))

        # ── Compile-time type compatibility check ──
        op_type = self._classify_operator(op)
        key_type = self._classify_key(key)

        if op_type is not None and op_type != "null" and key_type is not None and op_type != key_type:
            solver.add(BoolVal(False))

        # ── bool:false contradiction (operator normalized to lowercase) ──
        if op.lower() == "bool" and first_val == "false":
            solver.add(BoolVal(False))
