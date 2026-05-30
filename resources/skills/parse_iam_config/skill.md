# parse_iam_config

解析IAM策略配置JSON，提取Statement、Effect、Action、Principal、Condition等结构化信息。输出结构化的策略摘要，帮助理解IAM配置内容。

## 何时使用
当需要分析IAM配置时使用。输入原始IAM配置JSON字符串，返回结构化的策略分析结果。

## 参数
- `config_json`: IAM配置的原始JSON字符串

## 返回
结构化IAM策略摘要，包含策略类型、每个Statement的Effect、Action列表、Principal信息、Condition详情。
