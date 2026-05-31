# extract_intent_json

提取并验证意图理解结果的结构化JSON。这是ReAct循环中唯一输出约束列表的方式，必须在意图分析的最后一步调用。

## 参数
- `constraints_json`: 约束列表JSON字符串，包含 `constraints` 数组，每项含 `id`、`description`、`category`

## 返回
验证通过的结构化约束列表JSON，或错误描述

## 说明
此工具会验证JSON格式是否正确、约束列表是否非空。通过验证后将作为最终输出。

## 使用规则
1. 调用 `parse_iam_config` 分析IAM配置后，构造约束列表
2. 将构造好的约束列表JSON传入此工具
3. 此工具必须被调用，否则系统无法获取最终生成的约束列表
