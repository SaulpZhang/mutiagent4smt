from __future__ import annotations

import json
import re


def _fix_json(text: str) -> str:
    """修复 LLM 生成的 JSON 中常见语法问题"""
    # 修复中文字符上下文中的未转义引号
    text = re.sub(r'([一-鿿])"([^"]*?)"([一-鿿\s，。、；：])', r'\1「\2」\3', text)
    text = re.sub(r'([一-鿿])"([^"]*?)"', r'\1「\2」', text)
    text = re.sub(r'"([^"]*?)"([一-鿿])', r'「\1」\2', text)
    return text


def execute(constraints_json: str) -> str:
    """提取并验证意图理解的约束列表 JSON"""
    stripped = constraints_json.strip()

    if not stripped:
        return '{"error": "内容为空"}'

    # 尝试直接解析
    data = None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 尝试提取代码块
    if data is None:
        match = re.search(r'```(?:json)?\s*\n(.*?)```', stripped, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # 尝试修复后解析
    if data is None:
        try:
            data = json.loads(_fix_json(stripped))
        except json.JSONDecodeError:
            pass

    if data is None:
        return '{"error": "JSON 解析失败，请检查格式"}'

    constraints = data.get("constraints", [])
    if not constraints:
        return '{"error": "约束列表为空"}'

    # 验证每个约束的格式
    for i, item in enumerate(constraints):
        cid = item.get("id", f"C{i + 1}")
        desc = item.get("description") or item.get("constraint", "")
        cat = item.get("category", "instruction_derived")
        if not desc:
            return f'{{"error": "约束 {cid} 缺少 description"}}'

    # 返回规范的 JSON
    result = {
        "constraints": [
            {
                "id": item.get("id", f"C{i + 1}"),
                "description": item.get("description") or item.get("constraint", ""),
                "category": item.get("category", "instruction_derived"),
            }
            for i, item in enumerate(constraints)
        ]
    }
    return json.dumps(result, ensure_ascii=False)


PARAMETERS = {
    "type": "object",
    "properties": {
        "constraints_json": {
            "type": "string",
            "description": "约束列表JSON字符串，包含 constraints 数组",
        },
    },
    "required": ["constraints_json"],
}
