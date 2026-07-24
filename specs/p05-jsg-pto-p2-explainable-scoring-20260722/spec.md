# P05-JSG-PTO-P2：可解释评分基线与 grouped OOF

## 1. 状态与授权

- 状态：已正式授权并启动
- 授权日期：2026-07-22
- 授权来源：用户在确认 P2 目标和验收度量后要求“请开始执行目标”
- 前置完成项：JSG-PTO-P0/P1 已完成；M1/M2R/R2/RoadGraph PTO-P0 为历史实验结论

## 2. 业务目标

把 P1 中只用于证明候选可达的 label-only Oracle cost，替换为推理阶段可获得、可解释、无 truth 泄漏的证据评分。使用同一套 PTO-A/PTO-B 与 compiler，验证 V0 固定证据代价和 V1 可解释线性基线能否在 business-ID grouped 5-fold held-out Case 上选择正确 JSG，并生成 T06 Step3 语义 RoadGraph。

P2 回答“现有证据是否足以排序正确候选、排序是否是主要瓶颈”。P2 不训练神经网络；只有 P2 证明候选、约束、编译均正确而可解释评分仍不足，才允许另行授权 P3 object-conditioned 模型。

## 3. 范围

### 3.1 包含

- 冻结 P1 candidate manifest/hash 与 P1 Oracle label manifest/hash。
- 复用 M0 business-ID grouped 5-fold、target/context 权重和排除项。
- 生成不含对象 ID、Case ID、truth 或 Oracle cost 的候选 feature token。
- V0 明确证据代价；V1 训练折内拟合的稀疏可解释线性加性评分。
- PTO-A JSG candidate 与 PTO-B RoadGraph candidate 的 OOF score、margin、confidence、uncertainty 和 explanation contract。
- 逐 fold 模型、逐候选 OOF score、逐 Case selected JSG/RoadGraph、PTO certificate、M0/GIS 评价。
- 双跑确定性、资源、泄漏、基线和 go/no-go 审计。

### 3.2 排除

- 神经网络、LLM teacher、蒸馏、P3。
- 新增或修改 T01-T09 业务规则、字段语义或接口。
- 新增 CLI、root script、T10 stage、`__main__.py`、Makefile target。
- 重跑历史 proposal、优化在线 proposal generator 或宣称生产/在线 GO。
- Case ID 特判、truth-derived feature、事后补路、吸附、重连、relaxation 或 silent fix。

## 4. 职责视角

### 产品

- 最终业务评价对象仍是 T06 Step3 F-RCSD Road/Node。
- P2 结果必须区分“实验完成”“可解释基线 GO”“允许进入 P3”和“在线 proposal 仍 NO-GO”。

### 架构

- candidate、label、feature、model、score、selection、compiler 七层 manifest/hash 隔离。
- V1 每个 held-out fold 只能消费其它 fold 的 label；fold、Case、对象 ID 不进入 feature。
- PTO 只消费统一 `candidate_id/cost/confidence/uncertainty/score_source` 合同。

### 研发

- 仅新增 P05 Python callable/data contract，不新增正式入口。
- V0/V1 与 PTO-A/PTO-B 共用相同候选、约束、compiler 和 evaluator。

### 测试

- 覆盖 manifest/hash、fold leakage、ID/token leakage、label-only 边界、V0/V1 确定性、未知 token、margin/confidence、infeasible、PTO 选择和物化。
- 完整 P05 回归必须通过。

### QA

- 真实 51 Case grouped OOF；排除 `T10-Error / 1213556_1263661`。
- CRS、几何、ID、引用、方向、属性、有向拓扑和 no-silent-fix 全量审计。
- 逐 Case/逐 fold/逐对象类型分母不得隐藏；零实例和 Review/Unknown 单列。

## 5. 成功标准

### Gate 0：冻结、范围与零泄漏

- 51 Case，排除项出现 0 次。
- P1 JSG/RoadGraph candidate signature 与 P1 冻结值一致，candidate/group/lineage 不改写。
- candidate feature 中 Case/business/object/candidate/group ID、truth、Oracle cost、truth signature 和最终 ID 出现次数为 0。
- M0 business-ID grouped 5-fold 原样复用；fold Case 交集为 0，每个 Case 恰好一次 held-out。

### Gate 1：评分合同与可解释性

- V0/V1 覆盖 100% 候选，输出 cost/confidence/uncertainty/score_source。
- 100% V1 score 可由 feature token 与 fold weight artifact 重建，未知 token 使用显式零权重。
- 每组输出最优/次优 margin；模型/评分双跑 signature 一致。

### Gate 2：候选排序与 JSG

- PTO-A group Top-1 accuracy 总体 `>=0.90`，各对象类型 `>=0.80`。
- JSG semantic micro-F1 `>=0.90`、macro-F1 `>=0.85`。
- Review/Unknown recall `>=0.90`；multi-THROUGH 自动发布为 0。

### Gate 3：PTO 与最终 RoadGraph

- PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0。
- grouped OOF Road F1 `>=0.85`、Node F1 `>=0.90`、最差 Case Road F1 `>=0.70`。
- direction/source accuracy `>=0.95`；每类 SPLIT recall `>=0.70`。
- 比最强 V0 确定性基线 Road F1 提升至少 5pp，若 V0 已独立达到全部最终门禁则不强制 V1 增益。
- CRS、ID、引用、有向拓扑、物化 hard failure 为 0；`relaxation=false`、`content_repair=false`、`silent_fix=false`。

### Gate 4：资源、确定性与结论

- score 阶段单 Case P95/max `<=5s/20s`。
- 冻结候选后的 P2 链 P95/max `<=60s/300s`、RSS `<=16GB`、训练 CPU `<=2h`，不要求 GPU。
- 双跑 score/selection/JSG/RoadGraph/metrics signature 一致。
- 历史 proposal replay 5,751.192s 单列，不得据此声明在线 GO。

## 6. 完成定义与决策

- 所有合同、callable、测试、51 Case OOF、双跑、GIS/资源/确定性审计和 validation summary 完成，才可标记 P2 完成。
- V0 或 V1 达到 Gate 0~4：P2 baseline GO；若 V0 已满足，不自动授权神经模型。
- Gate 0、候选、PTO、compiler 均成立，但 V0/V1 排序或最终指标失败：P2 实验完成并确认评分瓶颈，允许另行讨论 P3。
- 候选、约束、编译或证据不足：P2 no-go，禁止训练模型掩盖。
