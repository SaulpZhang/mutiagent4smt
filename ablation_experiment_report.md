# 消融实验报告

## 实验设置

| 参数 | 值 |
|------|-----|
| 数据集 | valid_permission (126 个用例) |
| 模型 | deepseek-chat |
| Attempts | 1 (PASS@1) |
| Workers | 8 |
| 最大迭代次数 | 3 |
| Run ID (full) | exp_full_v2 |
| Run ID (gen_only) | exp_gen_only |
| Run ID (no_eval) | exp_no_eval |

### 消融模式

| 模式 | Agent1 意图理解 | Agent2 代码生成 | Agent3 评估反馈 |
|------|:---:|:---:|:---:|
| **Full** | ✅ | ✅ | ✅ (含反馈循环) |
| **no_eval** | ✅ | ✅ | ❌ |
| **gen_only** | ❌ (mock) | ✅ | ❌ |

---

## 实验结果对比

| 指标 | gen_only | no_eval | full |
|------|:--------:|:-------:|:----:|
| **PASS@1** | **95.24%** (120/126) | **96.03%** (121/126) | 92.06% (116/126) |
| **Accuracy** | 95.24% | **96.03%** | 92.80% |
| **Precision** | 97.37% | **98.67%** | 94.81% |
| **Recall** | **94.87%** | **94.87%** | 93.59% |
| **F1 Score** | 96.10% | **96.73%** | 94.19% |
| **约束满足率** | 0%* | 0%* | 96.83% |

> *注：gen_only 和 no_eval 模式无 Agent3 评估，故约束满足率不适用。PASS@1 基于 label_match（Z3 输出与预期标签的一致性）。

### 混淆矩阵

| | gen_only | no_eval | full |
|--|:--------:|:-------:|:----:|
| TP | 74 | 74 | 73 |
| TN | 46 | 47 | 43 |
| FP | **2** | **1** | 4 |
| FN | **4** | **4** | 5 |

---

## 核心发现

### 1. Full 流水线表现最差

加入 Agent3 评估反馈循环后，**每个指标都劣化**：

- 相比 gen_only：FP 翻倍 (2→4)，FN +1 (4→5)，新增 1 个错误
- 相比 no_eval：FP 翻 4 倍 (1→4)，FN +1 (4→5)

### 2. 迭代次数越多，性能越差

| 迭代次数 | 用例数 | 其中失败数 | 失败率 |
|:--------:|:------:|:----------:|:------:|
| 1 | 79 | 3 | 3.8% |
| 2 | 31 | 4 | 12.9% |
| 3 | 15 | 2 | 13.3% |

迭代次数越高，失败率越高，说明 **A3 反馈循环引入的错误多于修复的错误**。

### 3. 两类 Agent3 失败模式

#### A. A3 过度约束导致 FN（label=true, Z3=unsat）

Agent3 判定 "not satisfied" 后，Agent2 过度添加约束（如冲突检测、额外条件），使 Z3 模型过约束：

- **instruct_1_100**：gen_only 正常输出 sat，full 经 3 次迭代后代码膨胀 28% (3159→4030 bytes)，新增 `allow_deny_conflict_exists` 断言导致 unsat。根本原因是冲突检测过于粗糙——Allow 和 Deny 操作/主体部分重叠就判定冲突，未考虑条件差异。
- **instruct_1_26**：gen_only 正常 (sat)，full 经 2 次迭代后 unsat。
- **instruct_1_123**：3 次迭代后代码膨胀至 7646 bytes，unsat。

#### B. A3 无法纠正 FP（label=false, Z3=sat）

Agent3 虽能检测到约束不满足，但其反馈无法有效引导 Agent2 修复：

- **instruct_1_37**：2 次迭代仍 sat（FP）
- **instruct_1_49**：2 次迭代仍 sat（FP）。注意 no_eval 模式此 case 为 TN（正确），说明 A1 意图理解本身能帮助生成正确代码，但加上 A3 后反而被破坏。
- **instruct_1_70**：2 次迭代仍 sat（FP）
- **instruct_1_96**：1 次迭代 sat（FP），所有模式均失败

### 4. Agent3 并非完全无用

有 **1 个用例 (instruct_1_121)** gen_only 失败 (unsat) 而 full 成功 (sat)，说明 A3 反馈循环确实能修复部分问题。但修复 1 个 vs 引入 4 个新错误，净收益为负。

---

## 失败用例交叉分析

### 所有模式共有的失败

| 用例 | 类型 | 标签 | Z3 | 根因 |
|------|:----:|:----:|:--:|------|
| instruct_1_117 | FN | true | unsat | A2 代码生成工具无法处理该 IAM 模式 |
| instruct_1_123 | FN | true | unsat | A2 工具局限 + A3 加剧 |
| instruct_1_125 | FN | true | unsat | A2 工具局限 |
| instruct_1_49 | FP | false | sat | A2 工具局限 |
| instruct_1_96 | FP | false | sat | A2 工具局限 |

### Full 独有的失败（回归）

| 用例 | 类型 | 标签 | Z3 | 根因 |
|------|:----:|:----:|:--:|------|
| instruct_1_100 | FN | true | unsat | **A3 过约束**：冲突检测过于宽泛 |
| instruct_1_26 | FN | true | unsat | A1 提取约束过于严格，A3 加剧 |
| instruct_1_37 | FP | false | sat | **A3 无法修复**：2 次迭代后仍 FP |
| instruct_1_70 | FP | false | sat | A3 无法修复：2 次迭代后仍 FP |

### Full 修复的用例

| 用例 | 修复模式 | gen_only | no_eval | full |
|------|:--------:|:--------:|:-------:|:----:|
| instruct_1_121 | FN→TP | unsat | unsat | **sat** |

### 其他差异

| 用例 | gen_only | no_eval | 说明 |
|------|:--------:|:-------:|------|
| instruct_1_26 | **sat** (TP) | unsat (FN) | A1 意图理解引入过强约束导致 FN |
| instruct_1_49 | sat (FP) | **unsat** (TN) | A1 意图理解帮助解决 FP |
| instruct_1_125 | unsat (FN) | **sat** (TP)* | no_eval 模式此 case 正确 |

> *注意：instruct_1_125 在 no_eval 模式下 pass，但在 full 模式下 fail，说明 A3 评估循环破坏了这个 case。

---

## PASS@K 汇总

| Run ID | PASS@1 | PASS@3 | PASS@5 |
|--------|:------:|:------:|:------:|
| exp_full_v2 | 92.06% | 92.06% | 92.06% |
| exp_gen_only | 95.24% | 95.24% | 95.24% |
| exp_no_eval | 96.03% | 96.03% | 96.03% |

（attempts=1，故 PASS@1=PASS@3=PASS@5）

---

## 结论

1. **当前实现中，移除 Agent3 评估反馈环路的性能最佳**。no_eval 模式以 96.03% PASS@1 领先，且 Precision (98.67%) 和 F1 (96.73%) 均为最高。

2. **A3 反馈循环弊大于利**。虽然能修复个别用例（如 instruct_1_121），但引入了更多回归问题。核心矛盾在于：Agent3 的评估标准过于简化（基于 `all_satisfied` flag），其反馈无法精确指导 Agent2 进行有针对性的代码修改。A2 在收到负面反馈后倾向于过度补偿（添加过多约束），导致 Z3 模型过约束。

3. **工具层面的局限**是所有模式的共同瓶颈。5 个用例在所有模式下均失败（117, 123, 125, 49, 96），这些需要修复 `generate_smt_from_policy` 工具本身。

4. **Agent1 意图理解有一定价值**：no_eval vs gen_only 对比显示，Agent1 帮助 Precision 从 97.37% 提升到 98.67%（FP 2→1）。但同时 Recall 持平 (94.87%)，说明 Agent1 不影响漏报。

---

## 历史变更记录

| Commit | 日期 | 内容 |
|--------|------|------|
| `fc21ed1` | - | feat: 新增 generate_smt_from_policy skill，移除.gitignore中valid_permission忽略 |
| `9da8947` | - | feat: 新增extract_smt_code skill，精简Agent2工具集 |
| `8eb8200` | - | feat: Agent1新增extract_intent_json skill，修复JSON引号转义问题，支持消融实验 |
| `4171b8e` | - | fix: Z3 sat输出含get-model时精确匹配失败，改用startswith |
| `6ffb61c` | - | fix: 不再硬编码 contradiction 为 false，生成显式 SMT 断言 |
| `(本次)` | 2026-06-01 | fix: Z3 输出含 error 行时 sat 匹配失败，改用逐行检查 |
