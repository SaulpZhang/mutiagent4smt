# generate_smt_from_policy

根据IAM配置和约束列表，程序化生成语法正确的完整SMT-LIB V2代码。

## 参数
- `account_data`: IAM配置JSON字符串（含buckets或agencies字段）
- `constraints`: 约束列表JSON字符串（含constraints数组，每项有id/description/category）

## 返回
完整SMT-LIB V2代码（含declare-const、assert、define-fun、check-sat、exit）

## 说明
此工具实现了经过验证的代码生成逻辑，准确率高于LLM手写SMT代码。对于它能处理的用例，应优先使用此工具。当配置过于复杂（如空条件值、交叉键条件）时，工具会返回错误，此时请回退到build_smt_model等工具手动构造。

## 工作流程
1. 解析IAM配置中的Policy JSON（Statement数组）
2. 根据约束列表确定需要验证的字段（Effect/Action/Principal/Condition）
3. 为每个Statement声明SMT变量
4. 断言配置中的实际字段值
5. 生成验证函数（存在性、值合规性、操作符-键类型兼容性、语义矛盾检测）
6. 处理多Statement场景（Allow+Deny混合时进行交叉分析）
7. 组装完整SMT代码
