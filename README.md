# CodeV: Ensemble of LLM Agents for Automated Formal Verification of IAM Policies

## 项目概述

多LLM智能体集成系统，用于自动化IAM策略的形式化验证。通过3-Agent协作流水线生成SMT-LIB V2代码，使用Z3求解器验证云IAM策略中的权限配置。

### 系统架构

```
Input → Agent 1 (意图理解) → 约束列表 → Agent 2 (代码生成) → SMT代码
                                                      ↓
                                               Agent 3 (评估)
                                                      ↓
                                               Z3验证 → 输出
```

---

## 实验记录

### 图例

| 标记 | 含义 |
|------|------|
| ✅ DONE | 完整运行（125或126条记录） |
| ⏳ N/M | 部分完成（N条/M总条），因崩溃中断 |
| 🏆 | 当前最佳结果 |

### 完整实验

| 实验ID | 方案 | 模型 | PASS@1 | 正确/总数 | 说明 |
|--------|------|------|--------|-----------|------|
| run_20260516_172206 | 3-Agent流水线（默认Prompt） | deepseek-chat | 68.38% | 80/117 | 首次baseline实验，不含generator |
| run_20260517_063647 | 3-Agent流水线（优化Prompt） | deepseek-chat | 68.55% | 85/124 | Prompt优化后完整实验 |
| run_20260517_v11 | 3-Agent流水线（优化Prompt） | Qwen3-Coder-30B-A3B | 73.81% | 93/126 | 完整实验 |
| run_20260517_v13 | Generator规则引擎 | generator | 95.24% | 120/126 | 125/126用例由规则引擎处理，仅2个走LLM；6个错误均为数据集标签异常 |
| 🏆 run_20260517_v14 | **3-Agent流水线（httpx泄漏修复）** | deepseek-chat | **96.00%** | **120/125** | httpx泄漏修复后首次完整运行；100%约束满足率；5个错误均为数据集标签异常 |
| run_20260517_v15 | 3-Agent流水线（完整126用例） | deepseek-chat | 95.24% | 120/126 | 数据集补全后126用例完整运行；6个错误中5个为已知标签异常 |

### 部分完成实验（因resource_tracker泄漏导致SIGTERM崩溃）

| 实验ID | 方案 | 模型 | 进度 | PASS@1 | 说明 |
|--------|------|------|------|--------|------|
| run_20260517_025702 | 3-Agent流水线 | deepseek-chat | 44/126 | 72.73% | 早期Prompt优化中 |
| run_20260517_032850 | 3-Agent流水线 | deepseek-chat | 3/126 | 33.33% | 仅3条即崩溃 |
| run_20260517_033317 | 3-Agent流水线 | deepseek-chat | 49/126 | 81.63% | Prompt优化后 |
| run_20260517_040752 | 3-Agent流水线 | deepseek-chat | 10/126 | 100.00% | 早期测试 |
| run_20260517_041904 | 3-Agent流水线 | deepseek-chat | 66/126 | 77.05% | — |
| run_20260517_052107 | 3-Agent流水线 | deepseek-chat | 30/126 | 73.08% | — |
| run_20260517_055241 | 3-Agent流水线 | deepseek-chat | 18/126 | 100.00% | — |
| run_20260517_060940 | 3-Agent流水线 | deepseek-chat | 40/126 | 89.19% | — |
| run_20260517_v9 | 3-Agent流水线 + Generator | Qwen3-Coder-30B-A3B | 37/126 | 94.59% | 含Generator加速 |
| run_20260517_v10 | 3-Agent流水线 + Generator | Qwen3-Coder-30B-A3B | 29/126 | 89.66% | — |
| run_20260517_v12 | 3-Agent流水线 + Generator | deepseek-chat | 100/126 | 79.00% | Generator改进后 |

---

## 方案演进

### Phase 1: Baseline（3-Agent LLM流水线）

纯LLM驱动的3-Agent协作：
1. Agent 1（意图理解）→ 生成约束列表
2. Agent 2（代码生成）→ 基于约束生成SMT代码
3. Agent 3（评估）→ 逐项检查约束满足情况，不满足则迭代修改

**结果**: PASS@1 ≈ 68-74%，主要瓶颈为LLM意图理解失败、代码生成错误

### Phase 2: Prompt优化

多次迭代优化三个Agent的System Prompt：
- Agent 1: 改进约束列表提取格式和完整性
- Agent 2: 修复Condition为空、值矛盾等边界情况
- Agent 3: 提高评估准确性和反馈质量

**结果**: 部分实验达到PASS@1=81-89%（但多数因资源泄漏未跑完）

### Phase 3: Generator规则引擎（🏆 最佳）

开发`ValidPermissionGenerator`程序化生成器，直接解析IAM策略JSON结构：
- 策略语句解析（Allow/Deny Effect）
- Principal/Condition覆盖关系计算
- 内置字符串模式匹配（stringequals, stringmatch, startwith, endwith, like等）
- Allow+Deny交叉覆盖检测（IP范围子集、字符串模式、数值范围等）
- 跨条件矛盾检测（DateNotEquals+DateEquals、VpcSourceIp+SourceIp互斥等）

**结果**: PASS@1=95.24%（120/126），仅6个错误均为数据集标签异常

### Phase 4: 架构修复 + 完整流水线

修复httpx.AsyncClient资源泄漏问题后，重新运行完整3-Agent流水线（含Generator加速），当前进行中。

---

## 崩溃根因分析

所有实验（除v13 generator模式外）均因 **`resource_tracker: leaked semaphore objects`** 导致SIGTERM崩溃。

**根因**: `agent/llm_client.py` 中每个`LLMClient`实例创建独立的`httpx.AsyncClient`，每个pipeline编译创建3个`LLMClient`（126用例×3≈378个），这些AsyncClient从未被`aclose()`，导致OS级信号量泄漏，最终被macOS内存压力机制杀掉。

**修复**: 将httpx.AsyncClient改为类级共享单例（2026-05-17）。

---

## 数据集

- 总计126个用例（125个可用，`account_1_49.json`缺失）
- 49个 `bucket_policy` + 77个 `agency_trust_policy`
- 78个 True / 48个 False
- 5个已知标签异常：cases 96, 117, 121, 123, 125

---

## 运行方法

```bash
conda activate AI_Normal
python main.py run --attempts 1           # 单次运行全部用例
python main.py run --attempts 5           # 5次尝试计算PASS@K
python main.py run --index 1              # 只运行第1个用例
python main.py run --from 1 --to 10       # 运行用例1-10
python main.py stats                      # 查看实验结果统计
python main.py init                       # 检查项目配置
```
