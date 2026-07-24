# P05-Scheme-A-P2-P3-P2：Dataset-P1 scorer 重基线

## 1. 状态与授权

- 状态：已完成（`P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`）
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data` 及既有 P05 冻结工件
- Git：不提交、不推送
- Movement：忽略

用户在 Dataset-P1 判定 `P05_SCHEME_A_DATASET_P1_GO` 后批准继续。本阶段使用
Dataset-P1 的 6,275 个有效 Segment 标签，从头训练并重新评价 P2-P3 分层
carrier/clue scorer；2,588 个上下文 Segment不得进入标签、loss、阈值、校准或
指标，整图执行时保持安全 fallback。

## 2. 目标

在不改变 P2-P3-P0 基础模型、推理期证据和冻结业务骨架的条件下，回答：

1. 旧模型 NO-GO 是否主要由错误标签范围和 expected-failure 全 Case 级联造成；
2. 在正确的 Segment-scoped 标签合同下，当前 2.818M 级分层 scorer 能否同时满足
   零错误自动接受、有效覆盖、RealityChangeClue 和整图安全门；
3. 若仍为 NO-GO，是否可以把剩余问题明确归因到当前模型/证据能力，而不是本地
   Case 数量不足或无真值上下文污染。

## 3. 冻结业务语义

1. T01 Segment/Junction 骨架冻结，模型不得新增、删除、拆分、合并或重归属。
2. Dataset-P1 是本阶段唯一 Segment 标签资格合同：
   - `label_eligible=true` 的 6,275 个对象进入监督和 scorer 指标；
   - `CONTEXT_ONLY_MASKED` 的 2,588 个对象不进入任何监督或指标，整图执行时
     `KEEP_SWSD` fallback；
   - `context_input_weight=0.3` 只保留上下文资格，不得恢复为弱标签。
3. `T10:609214532` 与 `T10:74155468` 保持 Case `EXPECTED_FAIL`，只对
   Dataset-P1 登记的各 1 个 `failure_group_id` 执行局部 fallback；禁止整 Case
   级联覆盖 scorer decision。
4. 模型只决定 carrier 评分和 RealityChangeClue；通用 Junction/Node compatibility
   closure、合法性检查和 fallback 继续是确定性安全层。
5. T07 Step1 固定 `DRIVEZONE_ONLY`；T03/T04/T05 只作 label-only auxiliary
   target；T06 不作模型输入；Movement 全程为 0。

## 4. 五类职责视角

### 产品

- 准确性和安全性优先，允许更多 fallback。
- GO 必须表示“零错误自动接受且具备最低有效覆盖”，不能只表示训练完成。
- 上下文无人工真值时不得用自动化率换取错误发布风险。

### 架构

- 复用 P2-P3-P0 网络和 202 维 T01/T07 推理期证据，保持模型参数量级可比。
- 新增 Dataset-P1 scope overlay，不改写历史 P2-P3-P0 工件。
- 训练、inner threshold 和 held-out metric 均只读取 eligible 标签。
- RoadGraph 仍使用全部 8,863 Segment，但 context-only 与局部失败对象使用
  冻结 fallback。

### 研发

- 只新增 P05 内部 callable、schema、测试和 SpecKit 工件。
- 不新增 CLI、root script、T10 stage 或长期入口。
- 不修改 T01–T12 实现或接口，不修改 geometry/CRS。

### 测试

- 覆盖 scope 精确 join、eligible/context 隔离、权重覆盖、局部失败与整 Case
  级联保护。
- 覆盖训练/inner/held-out 仅使用 eligible label。
- 覆盖 context-only 决策恒为 `KEEP_SWSD` fallback。
- 覆盖指标分母精确等于 6,275，整图决策分母精确等于 8,863。

### QA

- 冻结 Dataset-P1 manifest/hash、模型配置、Case fold、seed、输入和输出 lineage。
- 正式 Run A/B 内容签名一致。
- CRS、geometry、骨架 mutation、repair、silent fix、Movement 和 T06 model-input
  均为 0。

## 5. 验收门禁

### Gate 0：范围与标签

- 8,863 Segment scope 完整；
- eligible/context=`6,275/2,588`；
- 51 Case 全部至少有一个 eligible 标签；
- eligible target 分布=`KEEP_SWSD 4,487 / USE_RCSD 1,748 /
  REVIEW_FALLBACK 40`；
- context 进入 label/loss/threshold/calibration/metric 数均为 0。

### Gate 1：模型与防泄漏

- 复用 P2-P3-P0 网络结构，参数量 `1,000,000–3,000,000`，硬上限
  `5,000,000`；
- 3 seeds × 5 Case folds，从头训练，held-out Case 无泄漏；
- truth、identifier、绝对坐标、Movement、T03/T04/T05/T06 inference feature
  均为 0；
- 不复用旧模型 state 或旧阈值。

### Gate 2：Carrier 安全与覆盖

在 eligible-only 的逐 seed、逐 fold和整体分母上：

- `carrier_wrong_accepted_count=0`
- `review_auto_publish_count=0`
- `carrier_safety_recall=1.0`
- `safe_coverage>=0.50`
- `USE_RCSD safe_coverage>=0.50`

### Gate 3：RealityChangeClue

在 eligible-only 的逐 seed、逐 fold和整体分母上：

- high-risk clue recall=`1.0`
- clue precision `>=0.80`
- clue macro-F1 `>=0.85`
- Dataset-P1 eligible 的 clue-only 对象全部捕获；冻结分母为 `5`

### Gate 4：整图安全

- 全部 8,863 Segment均有确定性 effective selection；
- context-only 2,588 个对象自动接受数为 0；
- 两个 expected-failure Case 每 seed 只局部回退各 1 个登记 failure group，
  Case 终态仍为 `EXPECTED_FAIL`、`publish=false`；
- 其余49 Case为 `LEGAL`；
- carrier conflict、Node mismatch、unexpected RoadGraph failure、骨架 mutation、
  repair、silent fix均为 0。

### Gate 5：确定性与资源

- 正式 Run A/B 的 score、eligible decision、all-segment effective selection、
  RoadGraph、metric 和 fold 内容签名一致；
- CPU RAM `<=8GB`，GPU VRAM `<=8GB`；
- 单 seed训练 `<=2h`，总训练 `<=6h`；
- Case inference p95 `<=5s`、max `<=20s`。

## 6. 阶段决策

- 全部门禁通过：
  `P05_SCHEME_A_P2_P3_P2_DATASET_P1_SCORER_GO`
- 审计、scope、确定性或资源失败：
  `P05_SCHEME_A_P2_P3_P2_AUDIT_NO_GO`
- 审计通过但模型业务门失败：
  `P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO`

任何结论都不自动授权在线 proposal、生产接入、T01–T12 修改、Movement 训练或
Git 操作。
