from __future__ import annotations


def execute(code: str) -> str:
    """提取并验证 SMT-LIB V2 代码

    验证规则：
    - 包含 (check-sat)
    - 包含 (exit)
    - 括号数量平衡
    """
    stripped = code.strip()

    if not stripped:
        return "错误：代码内容为空"

    # 检查 (check-sat)
    if "(check-sat)" not in stripped:
        return "错误：缺少 (check-sat)"

    # 检查 (exit)
    if "(exit)" not in stripped:
        return "错误：缺少 (exit)"

    # 检查括号平衡
    open_count = stripped.count("(")
    close_count = stripped.count(")")
    if open_count != close_count:
        return f"错误：括号不平衡，左括号 {open_count} 个，右括号 {close_count} 个"

    return stripped


PARAMETERS = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "完整 SMT-LIB V2 代码（含 declare-const、assert、check-sat、exit）",
        },
    },
    "required": ["code"],
}
