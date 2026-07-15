请生成 {{ count }} 条验证指令和 IAM 配置对。

要求：
- 约 60% 用 agencies 格式，约 40% 用 buckets 格式
- 大多数单 Statement，最多不超过 2 个
- 覆盖 String/Number/Bool/Date/IP/Null 各类操作符
- 包含 Allow + Deny 混合的策略
- 约 70% 中文，30% 英文
- instruction 必须是简短的验证性问题
- 约 70% 有效配置，约 30% 无效配置
- policy 和 trust_policy 字段是 JSON 对象，不是字符串

仅输出 JSON 数组。
