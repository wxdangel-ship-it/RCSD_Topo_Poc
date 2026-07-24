# P05-Scheme-A-P2-P3-P1：失败归因与推理期证据可用性审计

## 1. 状态与授权

- 状态：已完成
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅限 `E:\TestData\POC_Data` 与现有 P05 不可变工件
- 前置结论：`P05_SCHEME_A_P2_P3_P0_MODEL_NO_GO`
- Movement：继续忽略
- Git：不提交、不推送

本阶段不训练模型、不调整阈值。目标是解释 P2-P3-P0 的稳定错误接受、fold 2 跨 seed 低覆盖与 13 个 clue-only 对象的漏报/过报，并判断是否存在 T06 最终结果产生前即可独立生成、具有完整 lineage、且已获准用于推理的新证据。

## 2. 冻结业务边界

### 2.1 保持不变

- 冻结 T01 Segment 集合、Junction—Segment 关系和 PhysicalMovement 存在性；
- 模型不得新增、删除、拆分、合并或重分配业务骨架；
- Segment 冲突只回退该 Segment；共享 carrier 或 Junction 内部拓扑受影响时才升级 Junction fallback；
- T07 保持 `DRIVEZONE_ONLY`；
- T03/T04/T05/T06 的终态、status、reason、relation success 与 final Road/Node 继续是 `LABEL_ONLY`，本阶段不得提升为推理输入或确定性规则；既有合同登记的 truth-free strategy proposal 只可继续作为 candidate source，不等于提升模块终态字段；
- 49 `LEGAL` + 2 `EXPECTED_FAIL` 的 RoadGraph 终态合同保持不变。

### 2.2 本阶段允许

- 只读分析 P2-P3-P0、P2-P2-P2-P0/P1/P2 与 Dataset-P0 不可变工件；
- 只读核对 T01/T07/T03/T04/T05/T06 的项目级、模块级源事实和实际 artifact lineage；
- 在 `E:\TestData\POC_Data` 内做必要的已登记策略重放，用于确认生成时点、输入依赖与 source role；
- 新增 P05 内部只读审计 callable、专项测试、SpecKit 与不可变审计输出。

### 2.3 本阶段禁止

- 训练、重训、微调或选择任何神经网络；
- 在当前 51 Case 上调 threshold、挑 seed、增加 epoch 或改变 P2-P3-P0 结论；
- 将 Case ID、对象 ID、候选 ID、绝对坐标、路径记忆、人工真值或 T06 终态编码为推理特征；
- 修改 T01–T12 正式实现、模块接口、repo CLI、T10 stage 或长期执行入口；
- 根据局部样本反推上游字段语义并固化为强规则；
- 修改几何、改变 CRS、silent fix 或改写冻结业务骨架。

发现源事实之间或源事实与本任务书冲突时，立即停止并由用户二次确认。

## 3. 审计分母

1. P2-P3-P0 seed 311/313 稳定错误接受的同一 Segment；
2. P2-P3-P0 fold 2 的全部 held-out Segment，逐对象解释 accept/fallback/clue 分布及其与其他 fold 的差异；
3. 冻结的 13 个 `CLUE_MISS_ONLY` 对象，逐 seed 解释捕获和漏报；
4. `E:\TestData\POC_Data` 中所有与 T01/T07/T03/T04/T05/T06/P05 相关的 Case/Segment 测试样本，盘点是否已经进入当前 51 Case、是否具有可重放 lineage、是否能形成新的独立冻结验证集。

## 4. 字段角色合同

每个潜在证据字段必须唯一归类为：

- `INFERENCE_ALLOWED`：推理时在 T06 最终结果前可独立生成，来源语义已被正式源事实启用，且不读取 label/truth；
- `LABEL_ONLY`：只能用于监督、归因或评价；
- `FORBIDDEN_LEAKAGE`：包含最终真值、ID/路径记忆、绝对坐标记忆或由 held-out truth 派生的统计；
- `UNAVAILABLE`：当前输入、实现或 lineage 无法在推理时稳定得到。

“代码能计算”不等于 `INFERENCE_ALLOWED`；必须同时满足正式语义、生成时点、输入依赖、lineage 和成本边界。

## 5. 五类职责视角

### 产品

- 准确性、安全性和异常可见性优先；
- 审计成功不等于自动发布能力通过；
- 没有新证据时应明确 `EVIDENCE_NO_GO`，不得用更多 fallback 或错误替换伪造覆盖率。

### 架构

- 分离业务存在性、carrier realization、RealityChangeClue 与通用图合法性；
- 通用 compatibility/Junction decoder 只保证合法图，不生成 carrier 真值；
- 任何新推理证据必须在 T06 最终 Road/Node 前独立成立。

### 研发

- 只实现 P05 内部只读审计逻辑和可复现输出；
- 不新增正式入口，不修改依赖，不触碰 T01–T12 实现。

### 测试

- 覆盖输入 hash、审计分母、字段角色互斥、生成时点、lineage、重复/遗漏、确定性和失败保护；
- 破坏测试必须检出 label-only 提升、truth/ID/绝对坐标泄漏和当前验证集复用。

### QA

- 对稳定错误对象、fold 2 全量对象和 13 clue-only 对象保留逐对象证据；
- 显式检查 CRS、拓扑一致性、几何语义、输入/参数/输出 lineage、资源和性能；
- 不修改几何，不做坐标变换，不 silent fix。

## 6. 验收门禁

### Gate 0：范围、输入与冻结

- 当前分母精确为 51 Case、8,863 Segment、3 seeds × 5 folds；
- P2-P3-P0 Run A/B、P2-P2-P2-P0/P1/P2 与 Dataset-P0 manifest/hash 全部通过；
- 稳定错误对象、fold 2 对象与 13 clue-only 对象无缺失、无重复；
- 训练、阈值修改、Movement、T01–T12 修改、骨架修改均为 0。

### Gate 1：失败归因

- 稳定错误 Segment 形成完整的 candidate、score、truth、Junction/Node compatibility、T01/T07 与 label-only 上游证据链；
- fold 2 每个 Segment 均有逐对象 accept/fallback/clue 行，并按真值、candidate reachability、clue、Junction dependency、置信区间和 source role 汇总；
- 13/13 clue-only 对象逐 seed 解释捕获/漏报，直接事实与模型相关信号分栏记录；
- 每个对象允许落入“缺少可用直接证据”，但不得仅归因于随机 seed。

### Gate 2：推理期证据角色

- T01/T07/T03/T04/T05/T06 与 P05 candidate/decoder 的潜在字段 100% 完成角色分类；
- 每个字段记录 source module、artifact、生成时点、输入依赖、CRS、lineage、成本和适用边界；
- `LABEL_ONLY/FORBIDDEN_LEAKAGE` 被标为 `INFERENCE_ALLOWED` 的数量必须为 0；
- 如需要改变现有源角色，立即阻断并由用户二次确认。

### Gate 3：独立验证可用性

- `E:\TestData\POC_Data` 测试样本 100% 完成 current-51 membership、人工确认口径、策略重放可用性和 lineage 盘点；
- 若存在未使用且合同完整的 Case/Segment，冻结独立验证 manifest，并证明与当前模型调优对象无重叠；
- 若不存在，不伪造新验证集，明确记录为 validation evidence gap。

### Gate 4：阶段决策

- `P05_SCHEME_A_P2_P3_P1_MODEL_RESTART_GO`：至少存在一类新增、已获准、truth-free 的推理期直接证据，可解释稳定错误与 clue-only 风险，并存在独立冻结验证集；
- `P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`：审计完整，但新增合法推理证据或独立验证集任一缺失；
- `P05_SCHEME_A_P2_P3_P1_AUDIT_NO_GO`：输入、hash、lineage、分母、互斥性或确定性失败。

任一决策都不自动授权训练、生产接入、T01–T12 修改、字段角色提升或 Git 提交/推送。

### Gate 5：确定性、资源与性能

- 正式 Run A/B 的归因对象、字段角色、验证清单、统计和 decision signature 内容一致；
- wall `<=30min`、CPU RAM `<=8GB`、GPU VRAM=`0`；
- 单 Case 审计 p95 `<=5s`、max `<=20s`。

## 7. 完成结论

- 正式判定：`P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO`；
- 正式 Run A/B：`p05_scheme_a_p2_p3_p1_audit_20260723_04/_05`；
- 内容 signature：`177344821e1b8b932a7b19bf16248ede1f6293d622c16570ba301ea9a7384311`，Run B `reference_run_match=true`；
- Gate 0/1/2/5 通过；新增合法直接推理证据=`0`，独立冻结验证集=`0`；
- fold 2 有 `1,795/3,037` 个 expected baseline failure，全分母 coverage 理论上限 `0.408956`；eligible-only 只作诊断，未改变冻结门；
- 未训练模型、未调阈值、未修改几何/CRS/业务骨架、未使用 Movement、未修改 T01–T12 实现或接口、未提交或推送 Git。
