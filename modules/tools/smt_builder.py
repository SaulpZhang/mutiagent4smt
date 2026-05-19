"""SMT-LIB V2 代码构建工具集

提供一组 Python 函数生成语法正确的 SMT-LIB V2 代码片段。
Agent 2 (ToolAgent) 的 LLM 可调用这些函数替代手写 SMT，减少语法错误。

函数职责：
1. build_declarations   — 批量声明变量
2. build_assignments    — 批量生成赋值断言
3. build_expression     — 构建逻辑表达式 (and/or/not/implies/eq)
4. build_define         — 定义函数
5. assemble_program     — 组装完整 SMT-LIB V2 程序

所有函数的输出保证语法正确。LLM 自主决定使用哪些函数。
"""

from __future__ import annotations

from typing import Any


def build_declarations(variables: list[dict[str, str]]) -> str:
    """批量生成变量声明 (declare-fun)。

    Args:
        variables: [{"name": "x", "sort": "Bool"}, {"name": "y", "sort": "String"}, ...]
                  兼容 {"name": "x", "type": "Bool"}（自动映射 type → sort）

    Returns:
        多个 (declare-fun ...) 行，用换行符连接。
    """
    lines = []
    for v in variables:
        name = v["name"].strip()
        sort = v.get("sort") or v.get("type", "").strip()
        if not sort:
            raise ValueError(f"variables 每项需要 'sort' 或 'type' 字段，但收到: {v}")
        lines.append(f"(declare-fun {name} () {sort})")
    return "\n".join(lines)


def build_assignments(assignments: list[dict[str, Any]]) -> str:
    """批量生成赋值断言。

    Args:
        assignments: 列表，每项包含:
            - "var": 变量名
            - "type": 赋值类型
                "bool"      → (= var true/false)
                "string"    → (= var "value")
                "int"       → (= var 123)
                "raw"       → (= var value)   value 为原始 SMT 表达式
            - "value": 值

    Returns:
        多个 (assert ...) 行，用换行符连接。
    """
    lines = []
    for a in assignments:
        if "var" not in a:
            raise ValueError(f"assignments 每项需要 'var' 字段，但收到: {a}")
        var = str(a["var"]).strip()
        if not var:
            raise ValueError(f"assignments 中 'var' 不能为空")
        value = a.get("value")
        t = a.get("type", "raw")

        if t == "bool":
            val = "true" if value else "false"
            lines.append(f"(assert (= {var} {val}))")
        elif t == "string":
            lines.append(f'(assert (= {var} "{value}"))')
        elif t == "int":
            lines.append(f"(assert (= {var} {int(value)}))")
        else:  # raw
            lines.append(f"(assert (= {var} {value}))")

    return "\n".join(lines)


def build_expression(op: str, args: list[str]) -> str:
    """构建 SMT-LIB 逻辑表达式。

    Args:
        op: "and" | "or" | "not" | "implies" | "eq" | "neq" | "xor"
        args: 操作数（"not" 只需一个）

    Returns:
        SMT-LIB 表达式字符串，如 "(and x y)"、"(=> a b)"
    """
    if not args:
        raise ValueError("build_expression 需要至少一个参数")

    op_map = {
        "and": "and",
        "or": "or",
        "not": "not",
        "implies": "=>",
        "eq": "=",
        "neq": "not (=",
        "xor": "xor",
    }

    smt_op = op_map.get(op)
    if smt_op is None:
        raise ValueError(f"不支持的操作符: {op}，支持: {', '.join(op_map.keys())}")

    parts = " ".join(args)

    if op == "neq":
        return f"(not (= {parts}))"
    if op == "not":
        return f"(not {parts})"

    return f"({smt_op} {parts})"


def build_assertions(expressions: list[str]) -> str:
    """将多个表达式包装为 (assert ...)。

    Args:
        expressions: SMT 表达式列表

    Returns:
        多个 (assert ...) 行
    """
    return "\n".join(f"(assert {e})" for e in expressions)


def build_define(name: str, args: list[dict[str, str]], sort: str, body: str) -> str:
    """生成 define-fun。

    Args:
        name: 函数名
        args: 参数列表，如 [{"name": "x", "sort": "Bool"}]
        sort: 返回类型
        body: 函数体表达式

    Returns:
        (define-fun ...) 字符串
    """
    if args:
        args_str = " ".join(f"({a['name']} {a['sort']})" for a in args)
    else:
        args_str = ""
    return f"(define-fun {name} ({args_str}) {sort} {body})"


def build_define_funs(defines: list[dict[str, Any]]) -> str:
    """批量生成 define-fun。

    Args:
        defines: 列表，每项含 name, args(可选), sort, body

    Returns:
        多个 (define-fun ...) 行
    """
    lines = []
    for d in defines:
        lines.append(build_define(
            d["name"],
            d.get("args", []),
            d["sort"],
            d["body"],
        ))
    return "\n".join(lines)


def assemble_program(
    declarations: str = "",
    assertions: str = "",
    define_funs: str = "",
    check_sat: bool = True,
    exit_: bool = True,
) -> str:
    """组装完整 SMT-LIB V2 程序。

    顺序: declarations → define_funs → assertions → (check-sat) → (exit)

    Args:
        declarations: variable declarations
        assertions: assertions
        define_funs: function definitions
        check_sat: 是否添加 (check-sat)
        exit_: 是否添加 (exit)

    Returns:
        完整的 SMT-LIB V2 代码
    """
    parts = []
    for p in [declarations, define_funs, assertions]:
        stripped = p.strip()
        if stripped:
            parts.append(stripped)

    if check_sat:
        parts.append("(check-sat)")
    if exit_:
        parts.append("(exit)")

    return "\n\n".join(parts) + "\n"
