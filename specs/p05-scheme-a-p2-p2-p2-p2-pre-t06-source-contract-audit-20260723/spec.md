# P05-Scheme-A-P2-P2-P2-P2：Pre-T06 等价证据源审计

## 1. 状态与授权

- 状态：已完成，`P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO`
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅复用 `E:\TestData\POC_Data` 冻结 51 Case 和既有 P05 不可变工件
- 前置结论：`P05_SCHEME_A_P2_P2_P2_P1_SOURCE_FACT_BLOCKED`
- Movement：继续忽略
- Git：不提交、不推送

本阶段不训练模型、不调整阈值、不增加 Case、不修改候选与 RoadGraph，也不把 T03/T04/T05/T06 字段直接提升为推理输入。目标是：

1. 将 Road/Carrier 发布安全与 RealityChangeClue 可见性拆成两个业务指标；
2. 对 P2-P2-P2-P1 的 22 个 `SOURCE_FACT_BLOCKED` 对象建立 Pre-T06 因果证据路径；
3. 判断现有数据能否支持一个不依赖 T06 最终规则结果的下一代分层模型；
4. 保留通用 Junction 一致性闭包作为确定性图合法性约束，不把它误记为业务真值生成。

## 2. 审计对象与业务分类

正式分母固定为 22 个 Segment：

- 9 个 `AGREED_WRONG`：模型 proposal 与真值不一致；
- 13 个 `RESIDUAL_UNSAFE_ACCEPTED`：旧指标判为 unsafe 且模型接受。

必须重新解释为互斥业务分类：

- `ROAD_CARRIER_UNSAFE`：模型接受了错误 Road/Carrier，或错误自动发布 Review；
- `CLUE_MISS_ONLY`：Road/Carrier 选择正确且保留 SWSD，但 RealityChangeClue/异常原因漏报；
- `SAFE_AND_VISIBLE`：Road/Carrier 正确且需要的异常线索已被保留。

## 3. 源事实与推理边界

### 3.1 当前允许的推理源

- T01 冻结 Segment/Junction 骨架、`ADVANCE_RIGHT`、`access_valid`、独立 Road 和 lineage；
- T07 `DRIVEZONE_ONLY` 证据；
- truth-free proposal/candidate、Road/Node payload、候选集合完整性；
- 通用 Node payload compatibility 与 Junction 一致性闭包；
- P05 模型 score/seed agreement，只能作为软信号。

### 3.2 只允许作为监督或归因的源

- T03/T04 `has_evd`、`is_anchor` 及原因字段；
- T05 中间策略结果；
- T06 Step1/Step2/Step3 relation、terminal state 与最终 carrier 真值；
- RealityChangeClue 标签。

上述字段在本阶段可用于回答“策略真值为何这样判”，但不得进入正式推理特征、硬规则或自动发布逻辑。若后续需要提升为推理输入，必须单独获得业务授权并同步源事实。

### 3.3 禁止

- 训练、重训或调整任何模型及阈值；
- 使用 Case/对象/候选 ID、绝对坐标、路径记忆或 Movement；
- 修改 T01–T12 正式实现、官方入口、模块接口或正式数据；
- silent fix、修改几何、改变 CRS 或重写冻结业务骨架；
- 用 T06 最终结果在推理期替代 P05 预测。

## 4. 五类职责视角

### 产品

- 准确性与安全性优先；自动化率不得通过错误替换 SWSD 获得。
- 正确保留 SWSD 但漏报异常，与错误发布 RCSD 必须分别度量。

### 架构

- 冻结 T01 Segment/Junction/PhysicalMovement 骨架。
- 模型只预测 carrier 软判断与异常线索；确定性约束只保证图合法。
- Junction fallback 只在 carrier 共享或影响 Junction 内部拓扑时升级。

### 研发

- 只新增 P05 内部只读审计 callable、测试、SpecKit 和不可变输出。
- 不新增 CLI、root script、T10 stage 或长期正式入口。

### 测试

- 覆盖 22 对象分母、三类互斥、指标重解释、候选可达性、Junction 闭包和输入 hash。
- 破坏测试必须检出 truth 泄漏、源角色误提升、对象漏记和确定性差异。

### QA

- 公开原指标与重解释指标的逐 fold 差异。
- 公开 9 个真实 carrier 错误、13 个 clue-only 漏报、26 个初始 Node payload 冲突及 57 个 Junction fallback Segment。
- GIS 工件只复核 CRS/hash/lineage，不改几何、不做坐标变换、不 silent fix。

## 5. 验收门禁

### Gate 0：范围与输入

- 51 Case、8,863 Segment、22 审计对象、9 carrier 错误、13 clue-only 漏报精确。
- P2-P2-P2-P0、P2-P2-P2-P1、P2-P1 dataset/OOF 与 Scheme A baseline manifest/hash 全部通过。
- 训练、阈值调整、T01–T12 修改、Movement、骨架修改均为零。

### Gate 1：业务指标重解释

- 对 `LINEAR` 与 `SHALLOW_MLP` 逐 fold/整体重算：
  - `carrier_wrong_accepted_count`
  - `review_auto_publish_count`
  - `carrier_safety_recall`
  - `clue_miss_only_count`
  - `clue_recall`
  - `safe_coverage`
  - `use_rcsd_safe_coverage`
- 旧指标保留为历史结果，不覆盖。
- 只有 Road/Carrier 错误可以阻断 carrier safety；clue-only 漏报单独阻断异常可见性。

### Gate 2：Pre-T06 源路径

- 22/22 对象均记录 truth-free 候选可达性、T01/T07 当前证据、T03/T04/T05/T06 监督来源和 lineage。
- 5 个 carrier Road 缺失对象必须核验候选集合是否缺少 `USE_RCSD`。
- 1 个 `MIXED_CARRIER` 对象必须核验正确候选是否已存在。
- 16 个 Junction fallback 对象必须说明初始冲突与 Junction 闭包关系。

### Gate 3：Junction 一致性

- 冻结 compatibility oracle 中的 Junction fallback 集合；
- 精确复核 26 个初始 Node payload 冲突与 57 个关联 Segment；
- 闭包不得新增、删除、拆分、合并或重分配 T01 Segment。

### Gate 4：模型阶段判定

- `HIERARCHICAL_ROUTE_GO`：所有对象存在合法 Pre-T06 监督/推理路径，且重解释后的 cross-case carrier safety、coverage、RoadGraph 门禁全部通过；
- `PARTIAL_ROUTE_NO_MODEL_GO`：已找到合法分层路线，但任一 cross-case coverage、clue visibility 或 RoadGraph 门禁未通过；
- `SOURCE_CONTRACT_BLOCKED`：需要把当前 label-only 源直接提升为推理输入；
- `AUDIT_NO_GO`：分母、hash、lineage、互斥性或确定性失败。

任一结论都不自动授权训练、源角色提升、生产接入、T01–T12 修改或 Git 提交/推送。

### Gate 5：确定性与资源

- 正式 Run A/B 的重解释指标、对象路径、Junction 审计和 decision signature 一致；
- wall `<=30min`、CPU RAM `<=8GB`、GPU VRAM=`0`。
