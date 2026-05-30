# build_smt_model

从结构化JSON描述生成语法正确的完整SMT-LIB V2程序。自动处理括号、引号、关键字等格式，避免手写SMT语法错误。

## 参数
- `variables`: 变量声明列表，每项含 name(变量名)和 sort/type(类型: Bool/String/Int)
- `assignments`: 赋值断言列表，每项含 var(变量名)、type(赋值类型: bool/string/int/raw)、value(值)
- `constraints`: 约束断言列表，每项为一个SMT表达式字符串，自动包装为(assert ...)
- `define_funs`: 结构化函数定义列表，每项含 name、sort、body
- `define_funs_raw`: 原始 define-fun SMT 代码（如 build_type_check_smt 的输出），直接注入
- `check_sat`: 是否添加(check-sat)，默认true
- `exit_`: 是否添加(exit)，默认true

## 注意
build_smt_model 是 ReAct 循环中唯一的 SMT 代码输出方式。所有变量声明、赋值、约束都必须通过它生成，禁止在 LLM 消息中手写 SMT 代码块。
