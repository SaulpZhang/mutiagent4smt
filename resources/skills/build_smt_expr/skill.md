# build_smt_expr

构建单条 SMT-LIB 逻辑表达式（and/or/not/implies/eq/neq）。避免手写括号嵌套导致的语法错误。

## 参数
- `op`: 逻辑操作符: and(与)、or(或)、not(非)、implies(蕴含)、eq(相等)、neq(不相等)
- `operands`: 操作数列表。not只需一个操作数，eq需要两个

## 返回
SMT-LIB 表达式字符串，如 "(and x y)"、"(=> a b)"

## 使用方式
结果可嵌入 build_smt_model 的 constraints 中使用。
