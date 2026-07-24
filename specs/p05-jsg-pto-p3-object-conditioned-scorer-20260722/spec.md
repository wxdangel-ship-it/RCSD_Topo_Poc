# P05-JSG-PTO-P3：Object-Conditioned Neural Scorer grouped OOF

## 1. 状态与授权

- 状态：已完成；正式判定 `P3_MODEL_NO_GO`
- 授权日期：2026-07-22
- 授权来源：用户在确认 P3 目标和验收度量后明确要求“同意，请启动当前阶段目标”
- 前置完成项：JSG-PTO-P0/P1/P2 已完成；P2 已证明候选、PTO 与 compiler 成立且 V0/V1 评分不足

## 2. 业务目标

在不修改 P1 冻结候选、PTO-A/PTO-B、carrier compiler 和 RoadGraph evaluator 的前提下，以 object-conditioned 神经评分器替换 P2 V1 加性线性评分。模型必须在未见 business-ID Case 上结合候选自身、同组备选和 Junction—Segment—Movement 依赖上下文，输出 candidate cost/confidence，并由既有 PTO 生成 T06 Step3 语义 RoadGraph。

P3 回答“上下文神经评分是否能够替代 label-only Oracle cost”。P3 不回答在线 proposal 性能、自由图生成或生产接入问题。

## 3. 冻结输入

- P1 candidate：`p05_jsg_p1_candidate_20260722_02`
- P1 Oracle label：`p05_jsg_p1_oracle_20260722_03`
- P2 dataset：`p05_jsg_p2_dataset_20260722_02`
- P0 JSG truth：`p05_jsg_p0_20260721_04`
- R2 compiler truth：`p05_r2_oracle_20260721_03`
- M0 split/weight：`p05_m0_20260721_06`
- 范围：51 Case；排除 `T10-Error / 1213556_1263661`

正式运行必须记录上述 manifest/path/hash，候选和 fold signature 不得变化。

## 4. 范围

### 4.1 包含

- 由 P1 candidate dependency 构建 ID-free group/context token。
- candidate token、同组备选集合、dependency/reverse-dependency 与 Case profile 的 object-conditioned 表示。
- 小型候选—上下文交互网络，参数目标 `0.5M~3M`、上限 `5M`。
- listwise group ranking、对象类型平衡、Review/Unknown 安全权重与 confidence calibration。
- outer business-ID grouped 5-fold，正式 `3 seeds × 5 folds`。
- 同一 PTO-A/PTO-B、compiler、RoadGraph/GIS evaluator 和完整审计。
- candidate-only ablation 只作诊断，不作为 P3 GO 结果。

### 4.2 排除

- 修改或重跑 P1 candidate/proposal generator。
- 将 Case/business/object/candidate/group ID、绝对坐标、truth、Oracle cost 或 truth signature 输入模型。
- 使用 outer held-out label 做 early stopping、vocabulary、class weight 或超参数选择。
- 修改 PTO 约束、JSG 本体、compiler、T01-T09、T10 stage 或生产入口。
- 自由生成 Road/Node、事后补路、吸附、重连、relaxation、content repair 或 silent fix。
- LLM teacher、蒸馏和在线 proposal generator。

## 5. 职责视角

### 产品

- 主要成功依据是 held-out JSG 排序，不允许用已由策略候选稳定命中的 RoadGraph 100% 掩盖 JSG 错误。
- 结果必须区分 P3 scorer GO/NO-GO、RoadGraph safety gate 和 online/production NO-GO。

### 架构

- candidate、context、label、fold model、score、selection、compiler 分层 manifest/hash。
- context 只来自 inference-available P1/P2 evidence；对象 ID 只用于 join 和 audit。
- 模型只输出 cost/confidence，PTO 与 compiler 的确定性边界保持不变。

### 研发

- 首版采用 token embedding + candidate/context encoder + gated interaction MLP。
- group listwise cross-entropy；训练统计只来自 outer training Case，early stopping 只使用其中的 inner validation Case。
- CPU/GPU 共用实现，不新增 CLI、root script、`__main__.py` 或 Makefile target。

### 测试

- 覆盖上下文构建、ID/token 泄漏、fold/inner-validation 隔离、未知 token、group loss、模型参数量、checkpoint hash、confidence/ECE、PTO 和物化。
- P2 V1 基线与完整 P05 回归必须保留。

### QA

- 51 Case、191,331 groups、712,799 candidates 分母固定；逐 seed/fold/type/Review 指标不得隐藏。
- CRS、几何、ID、引用、方向、属性、有向拓扑和 no-silent-fix 全量审计。
- 训练/推理环境、CPU/GPU、RAM/VRAM、wall/CPU time 和随机种子可定位。

## 6. 成功标准

### Gate 0：范围、上下文与零泄漏

- 51 Case、5 folds，排除项出现 0 次；P1/P2 candidate、label、fold signature 精确匹配。
- 100% JSG/RoadGraph group 各有且仅有一个 label-only truth candidate。
- context token 中 Case/business/object/candidate/group ID、绝对坐标、truth、Oracle cost、truth signature 出现 0 次。
- outer train/held-out Case 交集为 0；inner validation 只来自 outer train。

### Gate 1：模型与评分合同

- 正式模型参数量 `0.5M~3M`，最大不超过 `5M`。
- 100% candidate 有 cost/confidence/uncertainty/model signature/context signature。
- 每组 confidence 归一为 1；10-bin ECE `<=0.10`。
- checkpoint、vocabulary、normalization、seed、fold 和 train/inner/held-out Case 完整记录。

### Gate 2：JSG 主要业务门禁

- PTO-A group Top-1 / JSG micro-F1 `>=0.90`。
- JSG macro-F1 `>=0.85`。
- Junction、PhysicalMovement、Relation、StandardSegment、SegmentConnector 各类型 Top-1 均 `>=0.80`。
- Review/Unknown recall `>=0.90` 且 precision `>=0.80`。
- multi-THROUGH 自动发布为 0。
- 三个正式 seed 均须通过，禁止挑选最好 seed。

### Gate 3：PTO 与 RoadGraph safety gate

- PTO-A/PTO-B 51/51 `OPTIMAL`、gap=0。
- Road/Node F1、最差 Case Road F1、direction/source、SPLIT recall 均保持 `1.0`；精确 Case 51/51。
- schema、CRS、ID、引用、几何、有向拓扑 hard failure 为 0。
- `relaxation=false`、`content_repair=false`、`silent_fix=false`。

### Gate 4：稳定性与资源

- 正式 `3 seeds × 5 folds`；同一 seed 的 Run A/B checkpoint/score/selection/JSG/RoadGraph signature 一致。
- 单 seed 完整 5-fold 训练 `<=2h`；三个 seed 总训练 `<=6h`。
- 峰值 RAM `<=16GB`、峰值 VRAM `<=8GB`。
- 单 Case score P95/max `<=5s/20s`；冻结候选到 RoadGraph P95/max `<=60s/300s`。
- 完整 P05 pytest 通过；代码体量和入口治理通过。

## 7. 完成定义与决策

- SpecKit、合同、callable、测试、正式 context dataset、3×5-fold、同 seed 双跑、PTO/RoadGraph/GIS/资源/确定性审计和 validation summary 全部完成，才可标记 P3 完成。
- Gate 0~4 全部通过：`P3_SCORER_GO`；只证明冻结候选上的 object-conditioned scorer 能力，不授权在线/生产。
- Gate 0/3 成立但 Gate 2 失败：`P3_MODEL_NO_GO`，按对象类型和 Review 错误判断是否需要证据/样本增强；不得修改约束掩盖。
- Gate 0、candidate、PTO 或 compiler 失败：`P3_UPSTREAM_OR_IMPLEMENTATION_BLOCKED`，禁止把失败归因于模型容量。

## 8. 正式完成结论（2026-07-22）

- 已完成 51 Case、191,331 groups、712,799 candidates 的 ID-free context dataset、正式 `3 seeds × 5 folds`、candidate-only 消融、同 seed 双跑以及 PTO/RoadGraph/GIS/资源/回归审计。
- 三个 seed 的 JSG Top-1 为 `0.9390~0.9395`，macro 为 `0.8471~0.8817`，总体能力显著高于 candidate-only；但 SegmentConnector 仅为 `0.4283~0.5992`，Review/Unknown recall/precision 仅为 `0.4389~0.4952 / 0.6886~0.7828`，Gate 2 失败。
- Gate 0、1、3、4 通过：三个 seed 的 PTO-A/PTO-B 均为 51/51 `OPTIMAL`，Road/Node/direction/source/SPLIT 均为 `1.0`，hard failure、repair 与 silent fix 为 0；确定性、GIS、资源和完整 P05 回归通过。
- 结论是当前 inference 输入缺少区分 carrier realization/access-resolved outcome 的对象级证据，而不是神经网络整体不适用。在线 proposal 与生产接入继续为 NO-GO；任何后续 carrier evidence/proposal 阶段必须单独授权。
