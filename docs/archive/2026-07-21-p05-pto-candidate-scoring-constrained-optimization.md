# P05-PTO：候选评分—约束优化 RoadGraph 方案归档

## 1. 归档状态

- 中文名称：**P05-PTO：候选评分—约束优化 RoadGraph**
- 英文名称：**P05 Predict-Then-Optimize RoadGraph**
- 简称：`P05-PTO`
- 归档日期：2026-07-21
- 当前角色：原始候选架构归档；PTO-P0 已由 `specs/p05-pto-p0-candidate-oracle-20260721/` 完成验证并同步 P05 source-of-truth，本文不再作为执行合同
- 适用问题：在纯神经网络 RoadGraph 生成泛化不足、过程式业务规则持续膨胀时，探索可解释、可审计、可学习的第三条路线

本文保留方案与差异的历史背景。实际 P0 范围、合同和门禁以 PTO-P0 SpecKit、P05 模块源事实与接口合同为准；不得把本文直接当作实现任务书。P0 正式结果为候选可达性与 Oracle-cost formulation 语义通过、全链策略 replay 性能失败；仅允许进入冻结候选上的 PTO-P1 learned-scoring 研究。

## 2. 核心定义

P05-PTO 不让单一神经网络直接生成最终 RoadGraph，也不让过程式 `if/else` 规则直接决定最终结果。系统把职责拆成五层：

```text
raw / T01 基础事实
        |
        v
高召回候选生成
        |
        v
候选证据与特征
        |
        v
可学习评分 / 代价预测
        |
        v
全局约束优化
        |
        v
Road/Node edit-set
        |
        v
确定性物化、审计与人工复核
```

各层职责如下：

1. **候选生成**：生成可能的 `COPY/UPDATE/SPLIT/CREATE/DROP` Road/Node edit candidates，目标是高召回，不在此阶段唯一决定结果。
2. **证据与特征**：登记几何连续性、道路面覆盖、端点距离、relation 置信度、source/formway 一致性、编辑复杂度、证据来源和不确定性。
3. **可学习评分**：首版可用线性代价或 GBDT/learning-to-rank；只有局部几何无法由结构化特征表达时，才引入专用小型神经模型。
4. **全局优化**：在 Case、corridor 或连通分量范围内联合选择候选，禁止逐 Road 独立 argmax。
5. **物化与审计**：复用 P05 edit-set、物化器与 evaluator；无可行解或多个近等价解时进入人工复核，不执行 silent fix。

## 3. 知识如何进入系统

### 3.1 硬约束

硬约束只接纳已经由项目或模块契约确认、跨场景稳定成立的不变量，例如：

- Road 引用的 Node 必须存在，Road/Node ID 必须唯一；
- SPLIT 父子对象、共享端点和生成状态必须一致；
- direction 必须与所声明的有向连接一致；
- T05 pointer 必须满足正式合同规定的候选存在性与基数；
- 外部开放边界保持显式开放，不强制整图闭合；
- CRS、输入、参数、候选、选择结果和物化输出可追溯；
- `silent_fix=false`。

任何局部样本归纳、距离经验阈值、Case 特判或尚未进入源事实的字段语义，不得直接升级为硬约束。

### 3.2 软代价

容易随区域和样本变化的业务偏好进入候选特征或软代价，不写成分支优先级：

- surface/corridor 支持程度；
- endpoint、形状与方向连续性；
- relation、source、formway 等证据一致性；
- `CREATE/SPLIT/DROP` 的复杂度与风险；
- 规则、模型和人工历史是否一致；
- 与已确认困难样本的相似度。

软代价可以先人工初始化，再由人工确认样本学习；每个代价项必须保留来源、版本和对最终选择的贡献。

### 3.3 不确定决策

对无可行解、最优与次优解差距过小、关键证据缺失或超出训练分布的区域，系统输出结构化 `Unknown/Review`，不通过增加规则或模型猜测强行完成。

## 4. T03-T06 的建议分工

| 模块 | P05-PTO 中的主要角色 |
|---|---|
| T03/T04 | 生成局部 Surface、relation、reference-point 候选；必要时由专用局部模型产生 proposal 或候选分数 |
| T05 | 对 `target_id -> base_id/NO_MATCH` 候选评分，并通过匹配/基数约束联合选择 |
| T06 | 在 corridor/连通分量内联合选择 Road/Node edit-set，负责最终图级组合而非逐 Road 分类 |
| P05 evaluator | 继续评价对象、属性、几何、引用和有向拓扑，不修正输入 |
| 人工复核 | 处理无可行解、近等价解和新型困难区域，并把确认结果回流评分数据集 |

当子问题可以表达为匹配或流守恒时，优先使用二分匹配、最小费用流等专用算法；只有包含异构布尔约束和组合动作的局部复杂区域才使用 CP-SAT/MILP。不得把全城未经分解地交给单个求解模型。

## 5. 与当前 P05-R2 的差异

### 5.1 保持不变的部分

| 维度 | 共同点 |
|---|---|
| 业务目标 | 都生成 T06 Step3 语义的 F-RCSD Road/Node |
| 数据范围 | 都可继续使用当前 `E:\TestData\POC_Data`、approved exclusion、label lineage 和 grouped fold |
| 基础输入 | 都坚持推理侧只使用 raw/T01 基础事实，不把 truth payload 注入输入 |
| 输出语言 | 都可以使用 Road `COPY/UPDATE/SPLIT/CREATE/DROP`、Node `COPY/UPDATE/CREATE/DROP` |
| 表示门禁 | 当前 R2 Gate 1 的 oracle roundtrip 对两种方案都有效 |
| 质量底座 | 都复用 M0 evaluator、不可变 run、hash、CRS、拓扑与性能审计 |
| 安全边界 | 都禁止 T06 fallback、Case ID 特判、content repair 和 silent fix |

### 5.2 核心不同的部分

| 维度 | 当前 P05-R2 | P05-PTO |
|---|---|---|
| 核心假设 | 20M-50M 联合神经模型可以直接预测完整 pointer 与 graph edit 内容 | 模型主要学习候选分数/代价，最终 edit-set 由全局优化器联合选择 |
| 候选空间 | `CREATE` 允许模型生成基础候选之外的新对象 | `CREATE` 也必须先形成可审计候选；求解器只能从候选集合选择 |
| 最终决策者 | 神经图编辑 decoder | 约束优化器，目标函数含可学习分数 |
| 约束范围 | constrained decoder 仅允许 schema、ID、引用、有限几何和生成状态合法性 | 除结构合法性外，可纳入已由正式合同确认的稳定业务不变量；可变偏好仍只能作为软代价 |
| 训练重点 | 多任务 Head、edit action、pointer、几何和连接的端到端 loss | 候选排序、代价校准和最终决策质量；局部神经模型为可选组件 |
| 数据需求 | 需要足够样本学习完整组合图生成 | 更依赖候选真值覆盖；学习任务相对局部，通常比端到端图生成的数据要求低 |
| 可解释性 | 主要解释 logits、action 和约束 intervention | 可列出候选、代价项、硬约束、最优/次优差距及无可行原因 |
| 失败方式 | 模型无法生成、生成错误或 OOF 泛化不足 | 候选缺失、约束冲突、评分错误或问题分解错误，可分层归因 |
| 主要算力 | GPU 训练与推理 | CPU 求解为主，配合较小的排序/局部模型；复杂度取决于候选规模与分解方式 |

### 5.3 差异程度判断

- **从业务目标和工程资产看：中等差异。** 数据清单、label lineage、grouped split、R2 edit-set、oracle、物化器、evaluator、审计和大部分验收指标都可以复用，粗略估计现有底座的 `60%~70%` 仍有价值。
- **从核心决策范式看：重大差异。** 当前 R2 由神经 decoder 直接生成 edit-set；P05-PTO 改为“模型评分、优化器组合”，核心推理层需要重做，不能视为 R2 的小幅调参。
- **从治理范围看：需要重新立项。** 当前 R2 合同明确禁止 decoder 编码业务判断；P05-PTO 若要把已确认业务不变量纳入优化约束，必须经新 SpecKit 明确约束白名单并同步模块源事实。

综合判断：**约三分之二底座可复用，但决定最终 RoadGraph 的核心三分之一发生架构级替换。** 不能直接在 R2 实现中顺手切换。

## 6. 建议的验证顺序

当前 R2 Gate 1 应继续完成，因为它同时验证 P05-PTO 所需的 edit-set 语言和物化器。Gate 1 之后如决定启动 P05-PTO，建议使用独立里程碑：

1. **PTO-G1 候选可达性**：51 Case 的 truth edit 必须全部存在于候选集合；Road coverage 至少 `99.9%`，Node/SPLIT/pointer 为 `100%`。
2. **PTO-G2 Oracle-cost 求解**：使用 label-only truth cost 时，优化器必须在 51/51 Case 选出规范化真值，且所有 hard failure 为 `0`。
3. **PTO-G3 可解释人工代价基线**：冻结一版非学习代价，与 keep-all、M2R、R2 基线比较，逐 Case 输出选择原因。
4. **PTO-G4 学习评分 OOF**：按现有 grouped 5-fold 训练评分模型；不得使用目标 Case 的对象、邻域或 truth cost。
5. **PTO-G5 Shadow**：只有候选覆盖、求解稳定性、OOF RoadGraph 和不确定性门禁均通过，才进入扩大数据范围的 shadow run。

最终评价继续沿用 Road F1、Node F1、最差 Case、direction/source/endpoint、有向拓扑、缺失引用、重复 ID、CRS、确定性、耗时和人工复核比例。平均指标达标但存在拓扑 hard failure时仍不得声明成功。

## 7. 主要风险

1. **候选爆炸**：需要按 corridor/连通分量分解，并以高召回为前提做可审计剪枝。
2. **候选缺失**：正确结果不在候选集合时，任何评分或求解器都无法恢复；必须把 candidate truth recall 作为第一门禁。
3. **约束膨胀**：只允许稳定不变量成为硬约束，局部偏好必须进入特征/代价，Case 特判禁止进入正式求解模型。
4. **不可行问题**：必须输出冲突约束和最小失败范围，不能自动放松约束后静默继续。
5. **评分泄漏**：训练、校准和 OOF 继续按业务 group 隔离，truth cost 只允许用于 label 和 oracle 验证。
6. **求解性能**：必须同时报告候选数、变量数、约束数、求解状态、最优间隙和耗时；不能只报告最终 Road 指标。

## 8. 当前结论

P05-PTO 不是“取消规则”，而是把规则从大量过程式结果判断收缩为少量稳定约束；把多变的业务偏好转为可学习代价；把无法确认的区域显式交给人工。它与当前 R2 共享数据、表示、物化和评价底座，但用约束优化替换神经 decoder 的最终图级决策职责。

本文仅作为候选方案档案。是否正式从 R2 分叉进入 P05-PTO，需等待 R2 Gate 1 的表示完备结果，并由用户另行授权。
