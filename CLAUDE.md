# CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

## 项目目标

本项目的核心目标是设计并实现一个**多LLM智能体集成系统**，用于自动化IAM（身份与访问管理）策略的形式化验证。系统通过生成高质量的SMT-LIB V2代码，实现云端IAM策略的自动化安全审计。

**所有后续实现的代码、优化和改进，均以完善、增强或优化此方法为最终目的。**

> **项目架构**：所有代码实现须遵循 [项目架构设计文档.md](项目架构设计文档.md) 定义的目录结构、分层职责和接口规范。新增或修改功能时，须以此架构文档为准则，确保模块间低耦合、高内聚。
>
> **开发需求**：具体的功能开发项、验收标准和优先级详见 [需求开发规格说明.md](需求开发规格说明.md)。所有开发工作应按照 P0→P1→P2→P3 的优先级顺序推进。

---

## 方法概述：多智能体协作的SMT-LIB V2代码生成流水线

### 系统架构（5大模块）

```
┌─────────────┐     ┌──────────────────────────────────┐     ┌──────────────┐
│ Input Module │────▶│        Generation Module         │────▶│  Evaluation  │
│  (输入模块)   │     │  ┌──────────────────┐  ┌──────┐ │     │   Module     │
│              │     │  │  Agent 1          │  │Agent2│ │     │  (评估模块)   │
│ 接收指令+配置  │     │  │ (意图理解智能体)   │→│(代码生成)│ │     │              │
│  → 形成指令-  │     │  │  → 生成约束列表    │  │      │ │     │  Agent 3     │
│   配置对      │     │  └──────────────────┘  └──┬───┘ │     │  (评估智能体)  │
└─────────────┘     └─────────────┬────────────────┘     └──────┬───────┘
                                  │ ① 约束列表                   │ ② 评估反馈
                                  └──────────────────────────────┘
                                        (迭代修改循环)

┌──────────────┐     ┌──────────────────┐
│    Output    │◀────│  Verification    │
│    Module    │     │    Module        │
│  (输出模块)   │     │  (验证模块)       │
│              │     │                  │
│ 生成最终输出   │     │  Z3求解器验证     │
│ 提高可解释性   │     │                  │
└──────────────┘     └──────────────────┘
```

### 模块详解

#### 1. Input Module（输入模块）
- 接收用户的**自然语言验证指令**和**IAM配置文件**
- 功能：将验证指令与相关IAM配置匹配，形成指令-配置对
- 输出传递给Generation Module

#### 2. Generation Module（生成模块）— 核心模块
该模块由两个智能体协作完成代码生成：

**Agent 1：意图理解智能体（运行独立，不受其他信息干扰）**
- 分析输入的验证指令和IAM配置
- 提取关键验证要求与目标
- 从IAM配置中提取相关属性和策略细节
- **输出：约束列表（Constraints List）** — 结构化表示关键属性和验证点
- 受DRIFT方法启发，约束列表是实现可解释性和语义对齐的关键

**Agent 2：代码生成智能体**
- 输入：验证指令 + IAM配置 + 约束列表
- 职责：生成可执行的SMT-LIB V2代码
- 语法修正：执行生成的代码，根据报错信息迭代修改直至无语法错误（有最大尝试次数限制）
- 语义修正：接收Evaluation Module的评估结果，根据反馈进行语义修正
- 迭代修改循环持续进行，直至所有约束满足或达到最大迭代次数

#### 3. Evaluation Module（评估模块）— 核心模块
**Agent 3：评估智能体（独立运行，保持客观性）**
- 使用约束列表作为参考，评估生成的SMT-LIB V2代码
- 逐项检查约束是否满足：
  - ✅ **全部满足** → 将代码和评估结果发送至Output Module
  - ❌ **存在不满足项** → 将标记为"不满足"的评估结果返回Agent 2进行修改
- 迭代持续到全部满足或达到最大迭代次数
- 保持评估过程的中立客观性

#### 4. Output Module（输出模块）
- 生成最终输出文件：包含生成的SMT-LIB V2代码和评估结果
- 评估结果以注释形式写入最终文件（提高可解释性）
- 可传递给Verification Module进一步验证

#### 5. Verification Module（验证模块）
- 使用Z3求解器验证生成的SMT-LIB V2代码
- 确保代码可执行
- 验证结果用于系统性能评估指标

---

### 方法核心创新点

1. **约束列表（Constraints List）机制**
   - 桥接自然语言与形式化代码之间的语义鸿沟
   - 作为代码生成和评估的共同参考标准
   - 大幅提高生成代码的可解释性

2. **三智能体隔离设计**
   - 每个智能体拥有隔离的记忆和明确的职责范围
   - 互不干扰，专注各自任务
   - 提供更好的可扩展性和灵活性

3. **迭代修改循环**
   - 语法层面：Agent 2根据执行错误自修正
   - 语义层面：Evaluation Module反馈驱动Agent 2修正
   - 双重反馈机制有效缩小搜索空间，提高代码质量

4. **可解释性提升**
   - 约束列表作为代码生成和评估的语义桥梁
   - 评估结果以结构化形式呈现（逐项标记满足/不满足）
   - 最终输出中包含评估结果注释

---

### 评价指标

| 指标 | 描述 |
|------|------|
| **Correctness** | 生成的SMT-LIB V2代码语法正确率 |
| **Alignment with User Intent** | 生成的代码满足约束列表中约束的百分比 |
| **Pass@K** | 在K次尝试内生成正确代码的成功率 |
| **Efficiency** | 代码生成全流程耗时 |

---

### 实验设计

1. **系统实现**: 用Python实现上述5模块系统，确保智能体记忆隔离
2. **LLM微调**: 探索使用LoRA对领域数据进行SFT微调，对比微调前后的性能提升
3. **鲁棒性实验**: 在不同LLM上测试系统性能，评估系统的模型无关性

---

## 数据库规则

`experiments` 表中的**每一条记录**对应且仅对应：**一次实验中，一个dataset用例的完整实验结果**。

具体约束：
- 每条记录的 `run_id` 标识所属的实验批次，同一批实验的所有记录共享同一个 `run_id`
- 每条记录的 `instruct_id` 标识具体的dataset用例
- 每次完整实验运行（`python main.py run`）产生 N 条记录，N = 该次实验运行的用例总数（通常为126）
- 对同一个用例的多次重复实验，通过 `run_id` 区分，保留多条记录

## 数据保护规则

除非用户明确要求，否则不得删除或清空以下数据：
- `experiments.db` 数据库文件及其中任何实验记录
- `data/results/` 目录下的任何生成结果文件
- 实验日志文件（如 `full_run.log`）

清理操作（删除数据库、结果文件、日志）必须等待用户明确指令。

## 实验记录日志

每次运行实验，必须在 `data/实验记录.log` 中追加一条记录，格式如下：

```
[run_id] | 时间 | prompt类型 | 模型 | 并行数 | 尝试次数
```

例如：
```
[run_20260515_013621] | 2026-05-15 01:36:21 | default | deepseek-chat | 10 | 5
```

此日志用于追溯所有历史实验的运行配置。

---

---

## 数据集说明

### 数据位置

所有数据集位于 `valid_permission/` 目录下。

### 数据结构

```
valid_permission/
├── account_schema.json              # IAM配置文件的JSON Schema定义
├── instructs/                       # 验证指令文件（126个）
│   ├── instruct_1_1.json
│   ├── instruct_1_2.json
│   └── ...
├── accounts/                        # IAM配置文件（126个）
│   ├── account_1_1.json
│   ├── account_1_2.json
│   └── ...
└── answer_valid_permission.json     # 正确结果标签（126个boolean值）
```

### 指令文件（instructs/）

JSON格式，包含以下字段：
- `scenario`: 场景名称，固定为 `"valid_permission"`
- `sub_scenario`: 子场景类型，有两种：
  - `"bucket_policy"`（49个）：验证存储桶策略是否包含有效授权
  - `"agency_trust_policy"`（77个）：验证委托信任策略是否包含有效权限
- `instruct`: 自然语言验证指令，中英文混合。示例：
  - "验证桶 compatible-special-format-0 的绑定策略中是否存在有效的授权配置"
  - "Check if the trust policy of agency 9f87af10-bd03-4dee-89cd-bd4b8e67f867 has effective authorization"

### IAM配置文件（accounts/）

JSON格式，包含以下字段（根据场景不同包含不同字段）：

| 字段 | 出现场景 | 说明 |
|------|---------|------|
| `account_id` | 全部 | 账户唯一标识 |
| `buckets` | bucket_policy | 存储桶列表，含 `bucket_name`, `bucket_policy`（JSON字符串）, `bucket_acl`（XML字符串） |
| `agencies` | agency_trust_policy | 委托列表，含 `agency_name`, `agency_id`, `attached_policy_ids`, `trust_policy`（JSON字符串） |

完整字段定义见 `account_schema.json`。

### 答案文件

`answer_valid_permission.json` 包含126个boolean值，78个true，48个false。

### 配对规则

**指令、配置、答案三者通过文件名后缀数字按顺序一一对应：**

```
instructs/instruct_1_1.json   →  accounts/account_1_1.json   →  answer_valid_permission.json[0]
instructs/instruct_1_2.json   →  accounts/account_1_2.json   →  answer_valid_permission.json[1]
...
instructs/instruct_1_126.json →  accounts/account_1_126.json →  answer_valid_permission.json[125]
```

---

## 项目状态

- [x] 基准实验完成（初步性能分析）
- [x] 项目架构设计（详见 [项目架构设计文档.md](项目架构设计文档.md)）
- [x] 需求开发规格说明（详见 [需求开发规格说明.md](需求开发规格说明.md)）
- [x] 项目整体框架实现（框架搭建完毕，可正常导入运行）
- [ ] Generation Module实现（Agent 1 + Agent 2 业务逻辑）
- [ ] Evaluation Module实现（Agent 3 业务逻辑）
- [ ] Input/Output/Verification Module实现（框架已完成，需细化）
- [ ] Pipeline流水线完整集成（LangGraph图构建）
- [ ] 实验追踪系统完整实现（SQLite记录+指标计算）
- [ ] 端到端集成测试
- [ ] 消融实验（不同LLM、约束列表影响）
