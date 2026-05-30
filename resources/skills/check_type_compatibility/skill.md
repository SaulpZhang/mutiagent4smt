# check_type_compatibility

检查IAM条件操作符与条件键的类型兼容性（编译期检查）。

## 参数
- `operator`: IAM条件操作符，如 numericequals、stringequals、dateequals、bool、ipaddress、null。支持multi-value前缀（如 forallvalues:stringequals）
- `condition_key`: IAM条件键，如 g:PrincipalAccount、g:SourceIp、g:CurrentTime、g:MFAPresent 等

## 返回
- `"true"`: 类型兼容
- `"false"`: 类型不兼容——必须将"false"放入 build_smt_model 的 constraints 数组（勿作为 assignment value 使用），constraints 中的 false 被包装为 (assert false) 使 Z3 模型 UNSAT
