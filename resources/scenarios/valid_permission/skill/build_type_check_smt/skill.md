# build_type_check_smt

生成类型兼容性检查的 SMT-LIB V2 代码片段（define-fun 形式）。与 check_type_compatibility 不同：check_type_compatibility 只返回 true/false，build_type_check_smt 返回显式编码操作符和键类型的 SMT 代码，评估器可以看到分类过程而非硬编码值。

## 参数
- `operator`: IAM条件操作符，如 numericequals、stringequals、dateequals、bool、ipaddress 等
- `condition_key`: IAM条件键，如 g:PrincipalAccount、g:SourceIp、g:CurrentTime 等
- `prefix`: 变量名前缀，如 's0_c0'（Statement 0 的 Condition 0）。默认 'type_ok'

## 使用方式
生成的 SMT 代码应传入 build_smt_model 的 define_funs_raw 参数。
