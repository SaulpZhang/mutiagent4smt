# CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

## 项目目标

多LLM智能体集成系统，用于自动化IAM策略的形式化验证。通过3-Agent协作流水线生成SMT-LIB V2代码，使用Z3求解器验证云IAM策略中的权限配置。

## 运行环境

```bash
conda activate AI_Normal
```

该环境已安装所有依赖（`pydantic-settings`、`z3-solver`、`langgraph` 等）。所有命令、脚本和代码执行必须在此环境下运行。

## 运行方法

```bash
python main.py run --attempts 1                         # 全量实验（126个用例）
python main.py run --attempts 1 --runid my_id            # 指定实验ID
python main.py run --attempts 5                          # 5次尝试计算PASS@K
python main.py run --gen-mode 0                         # 纯LLM模式（无Generator）
python main.py run --gen-mode 2                         # LLM-Managed Generator模式
python main.py run --from 1 --to 10                     # 运行用例1-10（左开右闭）
python main.py run --index 1                            # 只运行第1个用例
python main.py stats                                    # 查看实验结果统计
python main.py init                                     # 检查项目配置
```

## 数据集

位于 `valid_permission/` 目录，共126个用例。

| 项目 | 说明 |
|------|------|
| 指令文件 | `instructs/instruct_1_1.json` ~ `instruct_1_126.json` |
| 配置文件 | `accounts/account_1_1.json` ~ `account_1_126.json` |
| 答案标签 | `answer_valid_permission.json`（78 true + 48 false） |
| 配对规则 | 指令、配置、答案按索引一一对应 |
| 子场景 | `bucket_policy`（49个） + `agency_trust_policy`（77个） |

### 已知标签异常

以下5个用例的label与IAM策略语义不符（Generator和LLM流水线均一致报错）：
- **96, 117, 121, 123, 125** — Z3=unsat 但 label=True

排除标签异常后，有效PASS@1可提升约4个百分点。

## 系统架构

### 目录结构

```
codev1/
├── main.py                    # 入口 + 用例循环
├── config.py                  # Pydantic Settings（模型/超参数/路径）
├── core/
│   ├── schemas.py             # 全数据流 Pydantic Schema
│   ├── exceptions.py          # 自定义异常
│   └── trace_logger.py        # 用例级跟踪日志
├── agent/
│   ├── base.py                # BaseAgent 抽象基类
│   └── llm_client.py          # LLM API客户端（类级共享httpx单例）
├── prompt/
│   ├── manager.py             # PromptManager 加载/渲染
│   └── templates/             # 模板文件：
│       ├── intent_understanding.txt
│       ├── code_generation.txt
│       ├── code_modification.txt
│       ├── syntax_fix.txt
│       └── evaluation.txt
├── modules/
│   ├── input_module.py        # 加载+配对指令和配置
│   ├── generation_module.py   # Agent1(意图) + Agent2(代码生成)
│   ├── evaluation_module.py   # Agent3(语义评估)
│   ├── output_module.py       # 输出SMT文件
│   ├── verification_module.py # Z3语法检查+执行
│   ├── agent_builder.py       # 装配3个Agent
│   └── generators/            # 程序化SMT生成器
│       ├── base.py            # SMTGenerator + GeneratorRegistry
│       └── builtin_valid_permission.py  # ValidPermissionGenerator
├── pipeline/
│   ├── state.py               # PipelineState TypedDict
│   ├── graph.py               # LangGraph StateGraph 定义
│   └── nodes.py               # 节点适配器(modules→图节点)
├── experiment/
│   ├── models.py              # SQLite ORM
│   └── recorder.py            # SQLite持久化
├── utils/
│   └── smt_executor.py        # Z3安全执行
├── data/
│   ├── experiments.db         # 实验记录数据库
│   ├── results/               # 生成SMT代码
│   └── traces/                # 用例级跟踪日志
├── record/                    # 完整实验备份（gitignored）
├── valid_permission/          # 数据集（gitignored）
└── 项目架构设计文档.md         # 架构设计说明
```

### 完整工作流

```
main.py run
  │
  ├─ InputModule 加载126个用例
  ├─ ExperimentRecorder 初始化DB
  │
  └─ for each case (1~126):
       └─ compile_pipeline() → LangGraph
       └─ pipeline.ainvoke(state)
            │
            ▼
       intent_agent (Agent 1 ─ LLM)
        分析指令+配置 → ConstraintsList
            │
            ▼
       code_gen (Agent 2)
        ┌─ 首次生成:
        │   GeneratorRegistry.find(instruction)?
        │   ├─ 匹配 → ValidPermissionGenerator.generate() (程序化)
        │   └─ 不匹配 → LLM code_gen_agent.run() (LLM)
        │
        ├─ 语义修正(iteration>0, 评估未通过):
        │   LLM根据evaluation_feedback修正
        │
        └─ 重新生成(syntax重试达上限):
            LLM从头重新生成
            │
            ▼
       syntax_check (Z3 check-syntax)
        ├─ 通过 → evaluate
        ├─ 不满足(≤5次) → syntax_fix循环
        └─ 不满足(>5次) → regenerate(≤2次) 或 output
            │
            ▼
       evaluate (Agent 3 ─ LLM)
        逐项检查约束是否满足
        ├─ 全部满足 → output
        └─ 不满足(≤3次) → semantic_fix循环
            │
            ▼
       output → verify (Z3 check-sat)
            │
            ▼
       记录到DB + 计算label_match
```

### GeneratorRegistry 匹配逻辑

`ValidPermissionGenerator.can_handle(instruction)`:
1. **关键词匹配**：检查 instruction 是否包含 `"有效授权"`, `"effective authorization"`, `"是否存在有效"` 等15个关键词
2. **正则兜底**：正反两种语序匹配 `(验证桶|trust policy).*(是否有效|valid)` 和反向模式

匹配率：126个用例中匹配125个，仅1个走LLM。

### 关键超参数（config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_iterations | 3 | 语义修正循环上限 |
| max_syntax_retries | 5 | 语法修正循环上限 |
| llm_temperature | 0.1 | LLM温度 |
| llm_request_timeout | 120s | LLM请求超时 |
| case_timeout | 600s | 单用例超时（hard coded in main.py） |

### SMT代码生成模式（--gen-mode）

| 模式 | 值 | 说明 | 适用场景 |
|------|-----|------|----------|
| 纯LLM | 0 | 完全由LLM生成SMT代码，不使用任何生成器 | LLM代码生成能力baseline测试 |
| Generator+LLM | 1 | 优先匹配内置生成器（ValidPermissionGenerator），匹配失败走LLM | 当前默认模式（PASS@1≈96%） |
| LLM-Managed | 2 | 通过LLM分发到 user_defined/ 目录下的用户自定义生成器 | 扩展实验：LLM逐步创建/改进生成器 |

### 用户自定义生成器（gen_mode=2）

存储在 `modules/generators/user_defined/` 目录：
```
user_defined/
├── index.json                    # 生成器注册索引
├── generators/{name}/
│   ├── spec.json                 # 生成器说明（name/version/description/input/output）
│   └── generator.py              # Python实现（定义 generate() 函数）
└── ...
```

**工作流**：
1. 首次生成时，LLM根据验证指令判断是否有匹配的用户自定义生成器
2. 有匹配 → 动态加载并执行 generator.py 的 generate() 函数
3. 无匹配或执行失败 → 回退到 LLM 生成

初始状态为空，生成器由LLM随着实验推进逐步创建和改进。

## 基础设施注意事项

### httpx.AsyncClient 泄漏（已修复）

**根因**：每个 `LLMClient` 实例创建独立的 `httpx.AsyncClient`，每个 pipeline 创建3个 LLMClient（126用例×3≈378个），这些 AsyncClient 从未被 `aclose()`，导致 OS 级信号量泄漏→ macOS 内存压力 SIGTERM。

**修复**：`LLMClient._shared_async_client` 类级共享单例 + `LLMClient.close_all()` 在实验结束时释放。

### 数据库规则

`experiments` 表每条记录对应：一次实验中一个dataset用例的完整实验结果。同一批实验共享 `run_id`，不同用例通过 `instruct_id` 区分。

### 数据保护

除非用户明确要求，不得删除：
- `data/experiments.db` 及其中任何记录
- `data/results/` 下的生成结果
- `data/实验记录.log`

## 实验记录

每次运行实验，必须在 `data/实验记录.log` 中追加：
```
[run_id] | 时间 | prompt类型 | 模型 | 并行数 | 尝试次数 | gen_mode
```

### 已完成实验汇总

| 实验 | 方案 | 模型 | 总数 | PASS@1 | 有效PASS@1 |
|------|------|------|------|--------|-----------|
| 🏆 **v14** | 3-Agent + httpx修复 | deepseek-chat | 125 | **96.00%** | **99.17%** |
| **v15** | 3-Agent + 完整126用例 | deepseek-chat | 126 | **95.24%** | **98.36%** |
| **v13** | Generator规则引擎 | generator | 126 | **95.24%** | **100.00%** |
| v11 | 3-Agent (Qwen3-Coder) | Qwen3-Coder | 126 | 73.81% | 76.86% |
| run_063647 | 3-Agent (Prompt优化) | deepseek-chat | 126 | 68.55% | 71.43% |
| run_172206 | 3-Agent (Baseline) | deepseek-chat | 126 | 68.38% | 68.97% |

**关键结论**：
- 前3名（v13/v14/v15）均稳定在 **95-96%**，前2名排除标签异常后 **~99%**
- Generator 路径（125/126用例走程序化生成）纯LLM流水线路径性能一致
- httpx泄漏修复使LLM流水线首次能完整跑完126个用例
- 6个错误中5个是已知数据集标签异常（cases 96, 117, 121, 123, 125）

### 实验记录备份

完整实验（5个）的 results（SMT代码）、traces（跟踪日志）和数据库已备份至 `record/` 目录。

## 运行命令速查

```bash
# 启动全量实验（推荐）
conda activate AI_Normal
nohup python main.py run --attempts 1 --runid run_xxx > data/results/run_xxx.log 2>&1 &

# 查看进度
tail -f data/results/run_xxx.log
python3 -c "import sqlite3; db=sqlite3.connect('data/experiments.db'); cur=db.cursor(); cur.execute(\"SELECT COUNT(*), SUM(label_match) FROM experiments WHERE run_id='run_xxx'\"); print(cur.fetchall())"

# 统计指标
python main.py stats
```
