# extract_smt_code

提取并验证最终 SMT-LIB V2 代码。这是 ReAct 循环中唯一输出 SMT 代码的方式，必须在每次代码生成流程的最后一步调用。

## 参数
- `code`: 完整 SMT-LIB V2 代码字符串，必须包含 `declare-const`/`assert`/`check-sat`/`exit`

## 返回
验证通过的 SMT-LIB V2 代码，或错误描述

## 说明
此工具会验证代码是否包含 `(check-sat)`、`(exit)`，以及括号是否平衡。代码通过验证后将作为最终输出。

## 使用规则
1. 调用 `generate_smt_from_policy` 成功后，将其返回的代码传入此工具
2. 如果 `generate_smt_from_policy` 失败，修复问题后手动构造代码，通过此工具输出
3. 此工具必须被调用，否则系统无法获取最终生成的代码
