def generate(config: dict, constraints: list) -> str:
    import json
    
    # 1. 解析配置
    bucket_policy_str = config.get("buckets", {}).get("bucket_policy", "{}")
    if isinstance(bucket_policy_str, str):
        policy = json.loads(bucket_policy_str)
    else:
        policy = bucket_policy_str
    
    # 2. 提取Statement
    statements = policy.get("Statement", [])
    
    # 3. 生成SMT变量声明和断言
    lines = []
    
    # 声明所有可能的变量
    lines.append("; 声明变量")
    for i, stmt in enumerate(statements):
        effect = stmt.get("Effect", "")
        action = stmt.get("Action", [])
        principal = stmt.get("Principal", {})
        condition = stmt.get("Condition", {})
        
        lines.append(f"(declare-const effect_{i} String)")
        lines.append(f"(declare-const action_{i} (Array Int String))")
        lines.append(f"(declare-const principal_type_{i} String)")
        lines.append(f"(declare-const principal_value_{i} String)")
        lines.append(f"(declare-const has_condition_{i} Bool)")
        lines.append(f"(declare-const condition_operator_{i} String)")
        lines.append(f"(declare-const condition_key_{i} String)")
        lines.append(f"(declare-const condition_value_{i} String)")
        
        # 设置变量值
        lines.append(f"(assert (= effect_{i} \"{effect}\"))")
        
        # 处理Action
        if action:
            lines.append(f"(assert (= (select action_{i} 0) \"{action[0]}\"))")
        else:
            lines.append(f"(assert (= (select action_{i} 0) \"\"))")
        
        # 处理Principal
        principal_type = ""
        principal_value = ""
        if principal:
            for key, value in principal.items():
                principal_type = key
                if isinstance(value, list) and value:
                    principal_value = value[0]
                else:
                    principal_value = str(value)
                break
        lines.append(f"(assert (= principal_type_{i} \"{principal_type}\"))")
        lines.append(f"(assert (= principal_value_{i} \"{principal_value}\"))")
        
        # 处理Condition
        has_condition = bool(condition)
        lines.append(f"(assert (= has_condition_{i} {str(has_condition).lower()}))")
        
        if has_condition:
            for op, conditions in condition.items():
                for key, values in conditions.items():
                    if values:
                        lines.append(f"(assert (= condition_operator_{i} \"{op}\"))")
                        lines.append(f"(assert (= condition_key_{i} \"{key}\"))")
                        lines.append(f"(assert (= condition_value_{i} \"{values[0]}\"))")
                        break
                break
        else:
            lines.append(f"(assert (= condition_operator_{i} \"\"))")
            lines.append(f"(assert (= condition_key_{i} \"\"))")
            lines.append(f"(assert (= condition_value_{i} \"\"))")
    
    # 4. 根据约束生成断言
    lines.append("; 根据约束生成断言")
    
    for c in constraints:
        constraint_id = c["id"]
        if constraint_id == "C1":
            # Effect字段存在性
            for i, stmt in enumerate(statements):
                lines.append(f"(assert (not (and (= effect_{i} \"\"))))")
        elif constraint_id == "C2":
            # Effect值规范——必须为Allow或Deny
            for i, stmt in enumerate(statements):
                lines.append(f"(assert (or (= effect_{i} \"Allow\") (= effect_{i} \"Deny\")))")
        elif constraint_id == "C3":
            # Action字段存在性
            for i, stmt in enumerate(statements):
                lines.append(f"(assert (not (and (= (select action_{i} 0) \"\"))))")
        elif constraint_id == "C4":
            # Action值规范——非空
            for i, stmt in enumerate(statements):
                lines.append(f"(assert (not (and (= (select action_{i} 0) \"\"))))")
        elif constraint_id == "C5":
            # Principal字段存在性
            for i, stmt in enumerate(statements):
                lines.append(f"(assert (not (and (= principal_type_{i} \"\"))))")
        elif constraint_id == "C6":
            # Principal值规范——非空即可
            for i, stmt in enumerate(statements):
                lines.append(f"(assert (not (and (= principal_value_{i} \"\"))))")
        elif constraint_id == "C8":
            # 策略有效性——汇总以上判断是否存在有效授权
            valid_effect = []
            for i, stmt in enumerate(statements):
                valid_effect.append(f"(and (not (and (= effect_{i} \"\"))) (or (= effect_{i} \"Allow\") (= effect_{i} \"Deny\")) (not (and (= (select action_{i} 0) \"\"))) (not (and (= principal_type_{i} \"\"))))")
            if valid_effect:
                lines.append(f"(assert (or { ' '.join(valid_effect) }))")
    
    # 5. 添加检查和退出命令
    lines.append("(check-sat)")
    lines.append("(exit)")
    
    return "\n".join(lines)