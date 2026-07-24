# P05-Scheme-A-P2-P3-P0：分层 Carrier / Clue / Junction 模型验证

## 1. 状态与授权

- 状态：已完成，`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅使用 `E:\TestData\POC_Data` 冻结 51 Case 及既有 P05 不可变工件
- 前置结论：`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`
- Movement：继续忽略
- Git：不提交、不推送

本阶段训练一个参数量级为 1M–3M、硬上限 5M 的分层神经网络，验证模型能否在不改变 T01 业务骨架的前提下：

1. 对 Segment candidate 进行 object-conditioned carrier 评分，选择 `KEEP_SWSD / USE_RCSD / MIXED_CARRIER`；
2. 以独立 head 识别 `RealityChangeClue`；
3. 仅在训练期用 T03/T04 Node evidence 与 T05 relation 作为辅助监督；
4. 经通用 Node compatibility 与 Junction consistency decoder 得到合法 RoadGraph；
5. 在 Case-grouped 3 seeds × 5 folds 的 held-out Case 上同时满足安全、可见性、覆盖率和整图门禁。

## 2. 冻结业务边界

### 2.1 推理期允许输入

- T01 冻结 Segment/Junction 骨架、Segment 类型、独立 Road、lineage；
- T07 `DRIVEZONE_ONLY`；
- P05 truth-free candidate、Road/Node payload、candidate numeric/token representation；
- P2-P2-P2-P0 冻结的 202 维 truth-free 结构证据；
- 通用 Node payload compatibility 与 Junction consistency；
- base OOF score/seed agreement，只作为软信号。

### 2.2 只允许训练期辅助监督

- T03/T04 `has_evd`、`is_anchor` 状态；
- T05 `target_id -> base_id/status` relation；
- T06 carrier 真值与 `RealityChangeClue` 真值。

T03/T04/T05 的标签不得进入模型输入、阈值规则、decoder 或正式推理输出。辅助标签只通过损失函数塑造共享表征，held-out 推理不读取这些工件。

### 2.3 硬约束与 fallback

- 不新增、删除、拆分、合并或重分配 T01 Segment；
- 正式 Segment 必须有独立 Road；
- 普通提右是可含 `junc_nodes` 的 `ADVANCE_RIGHT Segment`，不存在 `SegmentConnector` 业务类型；
- Segment carrier 冲突只回退该 Segment；
- Movement 暂不建模；
- Node carrier 确实共享或影响 Junction 内部拓扑时，升级为 Junction fallback；
- 冲突或不确定性输出 `RealityChangeClue`，不得 silent fix；
- `REVIEW_FALLBACK` 永不自动发布。

## 3. 五类职责视角

### 产品

- 准确性和安全性优先，允许更多 fallback。
- 正确 Road/Carrier 与异常线索可见性分别验收。
- 不允许通过错误替换 SWSD 提升自动化率。

### 架构

- carrier scorer、clue head、辅助监督 head 分离。
- 通用 decoder 只保证 Node/Junction/RoadGraph 合法，不创造业务真值。
- PTO 继续只作为 candidate 来源，不作为 Node 标签或业务骨架。

### 研发

- 只新增 P05 内部 callable、测试、SpecKit 和不可变实验输出。
- 不新增 CLI、root script、T10 stage、模块正式接口或长期入口。
- 模型参数量目标 1M–3M，硬上限 5M。

### 测试

- Case-grouped 5-fold，固定 3 seeds；train/inner/held-out Case 严格隔离。
- 覆盖辅助标签 source-role、truth leakage、参数量、阈值冻结、fallback、Junction 闭包和确定性。
- 破坏测试必须检出 T03–T06 label-only 字段进入推理特征、ID/绝对坐标记忆和骨架 mutation。

### QA

- 公开逐 seed、逐 fold、整体指标和所有失败对象。
- 正式 Run A/B 内容级确定性比较。
- GIS 检查覆盖 CRS、拓扑一致性、几何语义、lineage/hash、资源和性能；不修改任何几何。

## 4. 数据与训练合同

- 51 Case、8,863 Segment group；
- 3 seeds × 5 held-out folds；
- 每个 outer fold 仅用 outer-train Case 构建词表、数值标准化与辅助标签统计；
- inner validation 只选择 epoch 与安全/clue 阈值；
- held-out fold 禁止调参；
- candidate listwise loss + candidate correctness loss + clue BCE + T03/T04/T05 auxiliary BCE；
- `REVIEW_FALLBACK` 不作为可自动发布 carrier；
- 训练结束后用固定通用 decoder 做 compatibility/Junction 闭包。

## 5. 验收门禁

### Gate 0：输入与泄漏

- Case/Segment/fold 分母为 `51 / 8,863 / 5`；
- Dataset-P0、P2-P1、P2-P2-P0/P1/P2-P2-P2-P0/P2-P2-P2-P2 lineage/hash 全部通过；
- 推理特征中 T03/T04/T05/T06 label/status/reason、对象 ID、Case ID、绝对坐标、Movement 均为 0；
- T03/T04/T05 辅助标签具有非零正负样本，且明确 `label_only=true`。

### Gate 1：模型合同

- 参数量目标 `1,000,000–3,000,000`，硬门禁 `<=5,000,000`；
- carrier、candidate-correctness、RealityChangeClue、auxiliary heads 均存在；
- 训练为 3 seeds × 5 folds，held-out Case 无泄漏。

### Gate 2：Carrier 安全与覆盖

逐 seed、逐 fold及整体均满足：

- `carrier_wrong_accepted_count = 0`
- `review_auto_publish_count = 0`
- `carrier_safety_recall = 1.0`
- 总体 `safe_coverage >= 0.50`
- `USE_RCSD safe_coverage >= 0.50`

### Gate 3：RealityChangeClue

逐 seed、逐 fold及整体均满足：

- high-risk clue recall `=1.0`
- 已知 13 个 clue-only 对象 `13/13` 捕获
- clue macro F1 `>=0.85`
- clue precision `>=0.80`

### Gate 4：Junction 与 RoadGraph

- frozen skeleton mutation、repair、silent fix 均为 0；
- compatibility/Junction decoder 后 carrier conflict、Node payload mismatch、unexpected RoadGraph failure 均为 0；
- RoadGraph 精确为 `49 LEGAL + 2 EXPECTED_FAIL`。

### Gate 5：确定性、资源与性能

- 正式 Run A/B 的 scores、decisions、effective selections、RoadGraph index 与 decision signature 内容一致；
- CPU RAM `<=8GB`，GPU VRAM `<=8GB`；
- 每 seed 五折训练 `<=2h`，总计 `<=6h`；
- Case 推理延迟 `p95<=5s`、`max<=20s`。

## 6. 决策

- 所有 Gate 通过：`P05_SCHEME_A_P2_P3_P0_HIERARCHICAL_MODEL_GO`
- 任一模型/业务 Gate 未通过：`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`
- 输入、lineage、source-role 或确定性失败：`P05_SCHEME_A_P2_P3_P0_AUDIT_NO_GO`

即使 GO，也只代表离线 POC 技术路线成立，不授权生产接入、T01–T12 修改、正式接口变更、Git 提交或推送。
