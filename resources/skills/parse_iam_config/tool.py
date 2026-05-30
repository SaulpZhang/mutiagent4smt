"""解析IAM策略配置JSON"""
from __future__ import annotations

import json

PARAMETERS = {
    "type": "object",
    "properties": {
        "config_json": {
            "type": "string",
            "description": "IAM配置JSON字符串",
        },
    },
    "required": ["config_json"],
}


def execute(config_json: str) -> str:
    """解析IAM配置JSON，返回结构化摘要"""
    try:
        data = json.loads(config_json)
    except json.JSONDecodeError as e:
        return f"JSON解析错误: {e}"

    version = data.get("Version", "unknown")
    stmts = data.get("Statement", [])
    if isinstance(stmts, dict):
        stmts = [stmts]

    lines = [
        f"IAM策略分析结果",
        f"  Version: {version}",
        f"  Statement数量: {len(stmts)}",
        "",
    ]

    for i, stmt in enumerate(stmts):
        effect = stmt.get("Effect", "unknown")
        action = stmt.get("Action", [])
        if isinstance(action, str):
            action = [action]
        not_action = stmt.get("NotAction", [])
        if isinstance(not_action, str):
            not_action = [not_action]
        principal = stmt.get("Principal", {})
        not_principal = stmt.get("NotPrincipal", {})
        condition = stmt.get("Condition", {})

        lines.append(f"Statement {i}:")
        lines.append(f"  Effect: {effect}")

        lines.append(f"  Action ({len(action)}): {', '.join(action[:8])}{'...' if len(action) > 8 else ''}")
        if not_action:
            lines.append(f"  NotAction ({len(not_action)}): {', '.join(not_action[:3])}")

        if isinstance(principal, dict):
            for k, v in principal.items():
                vals = v if isinstance(v, list) else [v]
                lines.append(f"  Principal [{k}]: {', '.join(str(x) for x in vals[:3])}{'...' if len(vals) > 3 else ''}")
        if isinstance(not_principal, dict):
            for k, v in not_principal.items():
                vals = v if isinstance(v, list) else [v]
                lines.append(f"  NotPrincipal [{k}]: {', '.join(str(x) for x in vals[:3])}")

        if condition:
            lines.append(f"  Condition 数量: {len(condition)}")
            for op, cond_data in condition.items():
                if isinstance(cond_data, dict):
                    for key, vals in cond_data.items():
                        v_str = ", ".join(str(x) for x in (vals if isinstance(vals, list) else [vals]))
                        lines.append(f"    [{op}] {key} = {v_str}")
        lines.append("")

    return "\n".join(lines)
