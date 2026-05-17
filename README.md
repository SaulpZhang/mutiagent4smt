# CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

多LLM智能体集成系统，用于自动化IAM策略的形式化验证。通过3-Agent协作流水线生成SMT-LIB V2代码，使用Z3求解器验证云IAM策略中的权限配置。

## 实验汇总

所有实验运行在 126 个用例（49 个 `bucket_policy` + 77 个 `agency_trust_policy`），78 True / 48 False。

**已知标签异常**（5 个用例 label 与 IAM 语义不符，排除后有效 PASS@1 约提升 4%）：cases 96, 117, 121, 123, 125。

| 实验 | 方案 | 模型 | 总数 | PASS@1 | 有效PASS@1 | 说明 |
|------|------|------|------|--------|-----------|------|
| 🏆 **v15** | 3-Agent + Generator | deepseek-chat | 126 | **95.24%** | **98.35%** | 稳定最佳，6错误中5个为标签异常 |
| 🏆 **v14** | 3-Agent + Generator (httpx修复) | deepseek-chat | 125 | **96.00%** | **99.17%** | 不含缺失用例，100%约束满足 |
| 🏆 **v13** | Generator 规则引擎 | generator | 125 | **96.00%** | **100.00%** | 全部走程序化生成，排除标签异常后全对 |
| v11 | 3-Agent (Qwen3-Coder) | Qwen3-Coder-30B-A3B | 126 | 73.81% | 76.86% | 无Generator辅助 |
| run_063647 | 3-Agent (Prompt优化) | deepseek-chat | 126 | 67.46% | 70.25% | Prompt优化基线 |
| run_172206 | 3-Agent (Baseline) | deepseek-chat | 126 | 63.49% | 62.81% | 首次基线实验 |

## 方案演进

### Phase 1: Baseline — 3-Agent LLM 流水线（PASS@1 ≈ 63-74%）

纯LLM驱动的3-Agent协作：
1. **Agent 1（意图理解）** → 分析 IAM 配置生成结构化的约束列表
2. **Agent 2（代码生成）** → 根据约束生成 SMT-LIB V2 代码
3. **Agent 3（评估）** → 逐项检查约束满足情况，不满足则迭代修正

主要瓶颈：LLM 意图理解偏差、代码生成错误、httpx 连接泄漏导致进程崩溃。

### Phase 2: Prompt 优化 + 架构修复（PASS@1 ≈ 68-81%）

- 优化三个 Agent 的 System Prompt（约束格式、边界条件处理、评估准确性）
- 修复 httpx.AsyncClient 类级共享单例，解决 `resource_tracker: leaked semaphore` 崩溃

### Phase 3: Generator 规则引擎（🏆 最佳，PASS@1=95-96%）

开发 `ValidPermissionGenerator` 程序化生成器，直接解析 IAM 策略 JSON 结构：
- 策略语句解析（Allow/Deny Effect）
- Principal/Condition 覆盖关系计算
- 内置字符串模式匹配（stringequals, stringmatch 等）
- Allow+Deny 交叉覆盖检测（IP范围、字符串模式、数值范围）
- 跨条件矛盾检测（DateNotEquals+DateEquals、VpcSourceIp+SourceIp 互斥）

125/126 个用例由程序化生成器处理，仅 1 个走 LLM 回退。

### Phase 4: 基础设施增强

| 改进 | 说明 |
|------|------|
| gen_mode 0/1/2 | 纯LLM / Generator+LLM回退 / LLM-Managed Generator |
| 对话历史累积 | 用例内 Agent 携带完整历史，支持跨轮次修正 |
| 统一重试机制 | 任何 LLM 调用异常均 60s 后重试，最多 4 次 |
| 超时保护 | 单次 LLM 调用 300s 超时，单用例 600s 超时 |
| LLM-Managed Generator | gen_mode=2 时无匹配生成器则 LLM 自动创建新生成器 |

## 系统架构

### 目录结构

```
codev1/
├── main.py                    # 入口 + 用例循环
├── config.py                  # Pydantic Settings
├── core/
│   ├── schemas.py             # Pydantic Schema
│   ├── exceptions.py          # 异常层次
│   └── trace_logger.py        # 用例级跟踪日志
├── agent/
│   ├── base.py                # BaseAgent 抽象基类（对话历史积累）
│   └── llm_client.py          # LLM API 客户端（共享 httpx 连接池）
├── prompt/
│   ├── manager.py             # PromptManager 加载/渲染
│   └── templates/             # 模板文件
├── modules/
│   ├── input_module.py        # 数据加载
│   ├── generation_module.py   # Agent 1 + Agent 2（含 gen_mode 路由）
│   ├── evaluation_module.py   # Agent 3
│   ├── output_module.py       # 输出 SMT 文件
│   ├── verification_module.py # Z3 语法检查 + 执行
│   ├── agent_builder.py       # Agent 装配
│   └── generators/            # SMT 生成器
│       ├── base.py            # SMTGenerator + GeneratorRegistry
│       ├── builtin_valid_permission.py  # 内置生成器
│       └── user_defined/      # LLM 创建的用户自定义生成器
├── pipeline/
│   ├── state.py               # PipelineState TypedDict
│   ├── graph.py               # LangGraph StateGraph
│   └── nodes.py               # 节点适配器
├── experiment/                # SQLite 持久化
├── data/
│   ├── experiments.db         # 实验结果数据库
│   ├── results/               # 生成 SMT 代码
│   └── traces/                # 用例级跟踪日志
└── valid_permission/          # 数据集
```

### 工作流

```
main.py run
  │
  ├─ InputModule 加载 126 个用例
  │
  └─ for each case:
       └─ compile_pipeline() → LangGraph pipeline
            │
            ▼
       intent_agent (Agent 1)
        分析指令 + 配置 → ConstraintsList
            │
            ▼
       code_gen (Agent 2)
        ├─ gen_mode=0: 纯 LLM 生成
        ├─ gen_mode=1: GeneratorRegistry → 匹配则程序化，否则 LLM
        └─ gen_mode=2: UserDefinedGeneratorManager → 匹配则复用，
                         无匹配则 LLM 创建生成器，回退 LLM
            │
            ▼
       syntax_check (Z3)
        ├─ 通过 → evaluate
        ├─ 不满足 (≤5次) → syntax_fix 循环
        └─ 不满足 (>5次) → regenerate (≤2次) 或 output
            │
            ▼
       evaluate (Agent 3)
        逐项检查约束
        ├─ 全部满足 → output
        └─ 不满足 (≤3次) → semantic_fix 循环
            │
            ▼
       output → verify (Z3)
            │
            ▼
       记录 DB + 计算 label_match
```

### 生成模式

| 模式 | 值 | 说明 |
|------|-----|------|
| 纯LLM | 0 | 完全由 LLM 生成 SMT 代码，LLM 能力基线 |
| Generator+LLM | 1 | 优先程序化生成器，匹配失败回退 LLM（默认，PASS@1≈96%） |
| LLM-Managed | 2 | LLM 分发到用户自定义生成器，无匹配则自动创建 |

## 运行方法

```bash
conda activate AI_Normal

python main.py run --attempts 1                         # 全量实验
python main.py run --attempts 1 --runid my_id            # 指定实验ID
python main.py run --attempts 5                          # PASS@K 统计
python main.py run --gen-mode 0                         # 纯LLM模式
python main.py run --gen-mode 1                         # Generator+LLM（默认）
python main.py run --gen-mode 2                         # LLM-Managed Generator
python main.py run --index 1                            # 单用例
python main.py run --from 1 --to 10                     # 用例范围
python main.py stats                                    # 实验统计
python main.py init                                     # 配置检查
```

## 数据集

- 位于 `valid_permission/` 目录，共 126 个用例
- 指令: `instructs/instruct_1_1.json` ~ `instruct_1_126.json`
- 配置: `accounts/account_1_1.json` ~ `account_1_126.json`
- 标签: `answer_valid_permission.json`（78 True + 48 False）
- 48 个 `bucket_policy` + 77 个 `agency_trust_policy`
