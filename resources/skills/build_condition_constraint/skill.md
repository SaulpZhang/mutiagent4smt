# build_condition_constraint

生成条件值的 SMT 约束表达式。将 IAM 条件的值约束编码为 SMT 表达式（如 (= v "User")、(> v 5)），使 Z3 能检测条件间的矛盾。

## 参数
- `operator`: IAM条件操作符，如 stringequals、numericequals、numericgreaterthan、bool 等
- `condition_value`: 条件值字符串，如 "5"、"false"、"User"、"prefix*suffix"
- `var_name`: SMT变量名，默认 "v"。应与 build_smt_model 中声明的条件值变量名一致

## 使用方式
生成的表达式应放入 build_smt_model 的 constraints 数组。
