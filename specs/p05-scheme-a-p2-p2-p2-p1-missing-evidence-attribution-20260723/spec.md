# P05-Scheme-A-P2-P2-P2-P1：缺失证据归因审计

## 1. 状态与授权

- 状态：已完成，`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅复用 `E:\TestData\POC_Data` 冻结 51 Case 及既有 P05 不可变工件
- 前置结论：`P05_SCHEME_A_P2_P2_P2_P0_EVIDENCE_NO_GO`
- Movement：继续忽略
- Git：不提交、不推送

本阶段不训练模型、不修改阈值、不增加 Case，也不把 T03/T04/T05/T06 label/status/reason 提升为推理输入。目标是逐对象解释“策略或人工真值为何知道正确结果，而当前合法推理证据为何不知道”，并把下一步严格分流为可用推理证据、源事实阻断或不可观测 fallback。

## 2. 审计对象

1. P2-P2-P2-P0 的 9 个三 base-seed 一致错误 proposal。
2. 浅层 MLP 正式结果中仍被接受的 unsafe Segment。
3. 40 个 `REVIEW_FALLBACK` Segment。

三类对象合并后必须形成无重复的正式审计分母。每个对象只能落入一个终态：

- `INFERENCE_EVIDENCE_AVAILABLE`：存在合法、truth-free、推理期可生成的直接业务/结构证据。
- `SOURCE_FACT_BLOCKED`：直接判定来源只存在于当前禁止的 label-only 源事实，提升前必须由用户二次确认。
- `UNOBSERVABLE_FALLBACK`：现有输入与允许补充的推理证据均不能区分，必须永久 fallback/Review。

关联但非直接因果的模型置信度、seed fallback 或相关性信号只能记录为辅助线索，不能把对象从 `SOURCE_FACT_BLOCKED` 改判为 `INFERENCE_EVIDENCE_AVAILABLE`。

## 3. 源事实边界

### 3.1 允许

- T01 冻结 Segment/Junction、`ADVANCE_RIGHT`、`access_valid`、独立 Road 与 lineage。
- T07 `DRIVEZONE_ONLY` 已冻结推理证据。
- truth-free candidate、Road/Node payload、compatibility edge。
- P05 模型的 score、seed agreement、joint fallback 等推理输出，只能作为辅助线索。
- label-only truth、T06 relation/terminal state、RealityChangeClue 仅用于审计归因和判定 `SOURCE_FACT_BLOCKED`，不得进入模型或自动发布逻辑。

### 3.2 禁止

- 训练或重训任何模型。
- 在当前 held-out Case 上调 threshold、加 epoch、增删特征后重报 GO。
- 将 `case_key`、对象 ID、候选 ID、绝对坐标或路径记忆编码为推理特征。
- 修改 T01–T12 正式实现、官方入口或模块接口。
- 根据局部样本反推并固化新的上游字段语义。

## 4. 五类职责视角

### 产品

- 准确性、安全性和冲突可见性优先；审计成功不等于自动化率提升。
- 已有确定性 fallback 证据应保留为硬门，不交给模型重新学习。

### 架构

- 冻结 T01 Segment/Junction/PhysicalMovement 骨架。
- 区分直接因果证据与相关模型信号；RealityChangeClue 必须能回溯到直接事实来源。
- `SOURCE_FACT_BLOCKED` 不自动授权 label-only 字段进入推理。

### 研发

- 只新增 P05 内部只读审计 callable、测试、SpecKit 和不可变输出。
- 不新增 CLI、root script、T10 stage 或长期正式入口。

### 测试

- 覆盖输入 hash、三类审计分母、终态互斥、直接/辅助证据区分、源角色和确定性。
- 破坏测试必须检出对象漏归因、重复归因、label-only 被误标为推理可用和 lineage 缺口。

### QA

- 必须公开 9 个一致错误、残留 unsafe、40 Review 及合并去重分母。
- 每个对象记录 source module/role、生成时点、推理可用性、计算成本、lineage、建议动作。
- GIS 数据只做既有 hash/CRS lineage 复核，不修改几何、不做坐标变换、不 silent fix。

## 5. 验收门禁

### Gate 0：输入与范围

- P2-P2-P2-P0、P2-P1 dataset/OOF、Scheme A baseline manifest 与正式输出 hash 全部通过。
- 51 Case、8,863 Segment、9 一致错误、40 Review 和浅层 MLP 残留 unsafe 分母精确。
- Movement、T01–T12 修改、训练和阈值调整均为零。

### Gate 1：逐对象终态

- 9/9 一致错误完成直接根因归因。
- 浅层 MLP 残留 unsafe 100% 完成直接根因归因。
- 40/40 Review 完成直接根因归因。
- 合并对象无重复、无缺失，每个对象只有一个终态。

### Gate 2：证据候选合同

- 每个直接或辅助证据候选均标明 source module/role、生成时点、推理可用性、计算成本和完整 lineage。
- truth/label-only、ID、绝对坐标和 Movement 推理特征计数为零。
- 相关模型信号不得冒充直接因果证据。

### Gate 3：决策

- 若全部问题由当前允许的新推理证据直接解释，输出 `P05_SCHEME_A_P2_P2_P2_P1_EVIDENCE_ROUTE_GO`。
- 若任一对象的直接来源只存在于当前 label-only 源事实，输出 `P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`。
- 若任一对象没有可观测直接来源，输出 `P05_SCHEME_A_P2_P2_P2_P1_UNOBSERVABLE_FALLBACK`。
- 任一输入、分母、lineage 或互斥性失败，输出 `P05_SCHEME_A_P2_P2_P2_P1_AUDIT_NO_GO`。

任一结论都不自动授权下一模型阶段、label-only 字段提升、生产接入、T01–T12 修改或 Git 提交/推送。

### Gate 4：确定性与资源

- 正式 Run A/B 的对象归因、证据候选、分类计数和决策 signature 一致。
- wall `<=30min`、CPU RAM `<=8GB`、GPU VRAM=`0`。
