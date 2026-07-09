# apply_smt_fix

验证修复后的 SMT-LIB V2 代码是否能通过 Z3 执行。用于反馈循环中验证修复是否正确。

## 何时使用
在根据评估反馈修改代码后，调用此工具验证修改后的代码语法正确且 Z3 可执行。

## 参数
- `patched_code`: 修复后的完整 SMT-LIB V2 代码
- `fix_description`: 修复内容的简要描述

## 返回
Z3 执行结果（sat / unsat / 语法错误）
