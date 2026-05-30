# check_condition_semantics

检查IAM条件语义是否矛盾（如 bool 条件值为 false）。返回 false（语义矛盾→放入 constraints→UNSAT）或 true（语义正常）。

## 参数
- `operator`: IAM条件操作符，如 bool、stringequals、numericequals 等
- `condition_key`: IAM条件键，如 g:SecureTransport、g:MfaAge 等
- `condition_value`: 条件值数组（JSON格式字符串，传完整数组，非单个值），如 '["false"]'、'["true"]'、'["true","false"]'

## 注意
与 check_type_compatibility 不同：check_type_compatibility 检查操作符与键的类型兼容性，此工具检查条件值的语义正确性。condition_value 接受 JSON 数组字符串，工具内部处理 OR 语义：同时包含 true 和 false 覆盖所有可能，不视为矛盾。
