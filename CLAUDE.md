# CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

## 项目目标

多LLM智能体集成系统，用于自动化IAM策略的形式化验证。LLM 负责自然语言理解和语义评估，**确定性 IAM→SMT 编译器** 负责代码生成，使用 Z3 求解器验证云IAM策略中的权限配置。

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
│   ├── compiler/              # ★ 确定性 IAM→SMT 编译器
│   │   ├── __init__.py        #     编译包
│   │   └── iam_compiler.py    #     核心编译器
│   ├── input_module.py        # 加载+配对指令和配置
│   ├── generation_module.py   # Agent1(意图) + IAMCompiler(代码生成)
│   ├── evaluation_module.py   # Agent3(语义评估)
│   ├── output_module.py       # 输出SMT文件
│   ├── verification_module.py # Z3语法检查+执行
│   └── agent_builder.py       # 装配 Agent1 + Agent3（Agent2已替换为编译器）
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
        分析指令+配置 → ConstraintsList（供评估用）
            │
            ▼
       code_gen (IAMCompiler ─ 确定性)
        IAM JSON → Z3 Python 模型 → solver.to_smt2() → SMT-LIB V2
        编译期检查：操作符/键类型兼容、bool:false 矛盾、tag 键前缀
            │
            ▼
       evaluate (Agent 3 ─ LLM)
        逐项检查 SMT 代码是否满足约束列表
            │
            ▼
       output → verify (Z3 check-sat)
            │
            ▼
       记录到DB + 计算label_match
```

**关键变化**：
- Agent 2 (代码生成) 已替换为确定性 `IAMCompiler`
- 无语义修正循环（编译器一次性生成正确代码）
- 无语法修正循环（编译器不会产生语法错误）
- 线性流水线：intent → compile → evaluate → output → verify

### 关键超参数（config.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| llm_temperature | 0.1 | LLM温度 |
| llm_request_timeout | 120s | LLM请求超时 |
| case_timeout | 600s | 单用例超时（hard coded in main.py） |

### IAMCompiler 设计要点

`modules/compiler/iam_compiler.py` 是确定性编译器，无LLM参与：

| 特性 | 实现方式 |
|------|----------|
| IAM解析 | Python json.loads，支持 bucket_policy / trust_policy |
| Effect建模 | Bool + String 变量，断言实际值与有效性 |
| Action/Principal | 存在性检查 |
| 条件类型兼容 | **编译期** Python 级别检查（operator lowercased + key prefix matching） |
| Tag键前缀 | `key.startswith("g:RequestTag/")` 等编译期匹配 |
| bool:false | 编译期直接添加 `BoolVal(False)` |
| 多Statement组合 | Allow+Deny → `And(Or(allow), Not(Or(deny)))` |
| SMT导出 | `solver.to_smt2()` + `(exit)` |

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
[run_id] | 时间 | 方案 | 模型 | 尝试次数
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
