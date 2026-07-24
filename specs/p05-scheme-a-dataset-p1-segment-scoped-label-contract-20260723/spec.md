# P05-Scheme-A-Dataset-P1：Segment-scoped 标签合同重建

## 1. 状态与授权

- 状态：已完成（`P05_SCHEME_A_DATASET_P1_GO`）
- 授权日期：2026-07-23
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data`
- 显式排除：`T10-Error / 1213556_1263661`
- Movement：忽略，不训练、不评价、不改变存在性或 carrier
- Git：不提交、不推送

本阶段修正此前把 `T10-Error/T10-Error-2` 包内上下文 Segment 以 `0.3`
作为弱标签的口径。旧运行和原始证据必须保留，但凡以旧 8,863 Segment
标签分母训练或评价得到的模型指标，只能作为旧口径历史证据，不能继续作为
当前 P05 神经 scorer 的启动依据。

## 2. 业务标签语义

1. `T10` 是 Case 级真值：Case 内全部当前 T01 Segment 可作为人工确认标签。
2. `T10-Error`、`T10-Error-2` 是 Segment 级证据包：
   - 只允许读取 `t10_case_evidence_manifest.json` 的
     `scope.swsd_segment_id` 和冻结 `scope.segment_properties.roads`；
   - 目录目标 Segment 及其 lineage 可证明的当前 T01 后继 Segment可作为标签；
   - 包内其它 Segment只能作为推理上下文，`context_weight=0.3` 不得进入
     carrier/clue label、loss、threshold、calibration 或 metric denominator。
3. 目标 ID 直接存在时，`scope.swsd_segment_id` 是正式业务身份，当前同 ID
   Segment直接继承目标标签；包创建时 Road 集合与当前 T01 Road 集合的增减必须
   单独登记为 `DIRECT_ID_WITH_ROAD_DRIFT`，但不得反过来否定同 ID 身份或扩展到
   其它 Segment。
4. 仅在目标 ID 不存在时，允许使用 Road 归属的精确分区 lineage：
   - 每个后继 Segment 的 `swsd_road_ids` 必须是目标冻结 Road 集合的非空子集；
   - 后继集合的 Road 并集必须与目标集合完全相等；
   - 任意目标 Road 不得被多个后继 Segment 重复拥有；
   - 不允许使用空间邻近、geometry overlap、目录邻近或模型预测补映射。
5. 无法满足上述 lineage 的目标包必须输出 `TARGET_MAPPING_UNAVAILABLE` 并 mask，
   不得降级为上下文弱标签或负样本。

## 3. Case 终态与对象度量分离

`T10:74155468` 与 `T10:609214532` 继续保持 Case 级
`EXPECTED_FAIL + RealityChangeClue + publish=false`。Case 级失败只阻断整图发布：

- `failure_group_ids` 命中的 Segment执行对象级失败/fallback；
- 其它 Segment仍保留 scorer label/decision/metric 资格；
- 禁止把一个 Case 的 `EXPECTED_FAIL` 级联为全 Case Segment
  `accepted=false` 或从 scorer coverage 分母移除。

本阶段只重建合同和审计，不改写历史 P2-P3-P0 decisions，不重训模型。

## 4. 五类职责视角

### 产品

- 准确性和安全性优先；上下文可以被模型读取，但不能伪装为人工真值。
- Case 不可发布与对象是否可正确评分是两个独立结论。
- 旧指标失效不等于神经网络不适用，只表示必须在正确分母上重新训练和评价。

### 架构

- 分离 `CASE_TERMINAL_ELIGIBILITY`、`SEGMENT_LABEL_ELIGIBILITY`、
  `SEGMENT_SCORER_ELIGIBILITY` 和 `CONTEXT_INPUT_ELIGIBILITY`。
- T01 Segment/Junction骨架保持冻结；本阶段只建立 lineage overlay，不改 T01。
- 使用 manifest 的业务 ID、Road 归属和已冻结 skeleton，不读取 T06 终态来决定标签范围。

### 研发

- 只新增 P05 内部只读 callable、schema、测试和 SpecKit 工件。
- 不训练、不调阈值、不修改历史运行、不新增 CLI/脚本/T10 stage/正式入口。
- 不修改 T01–T12 实现或接口，不修改 geometry/CRS。

### 测试

- 覆盖 Case 级全标签、Segment 包 target-only、direct mapping、
  Road partition lineage、上下文 mask、批准排除和映射失败保护。
- 覆盖 expected-failure Case 与对象级 failure group 分离。
- 破坏测试必须检出 Road 集合缺失、重复 owner、额外 Road、geometry 猜测和
  上下文进入标签/指标。

### QA

- 逐包保留 target ID、manifest/hash、冻结 Road、当前后继 Segment、
  lineage method、mapping status 和差异。
- 显式验证 CRS 不变、geometry 不读不写、骨架 mutation=0、拓扑不 silent fix。
- 正式 Run A/B 内容签名一致，输入、参数、输出和运行环境可定位。

## 5. 验收门禁

### Gate 0：范围与输入

- POC sample=`741`，RoadGraph Case=`51`，当前 Segment roster=`8,863`。
- 启用 Segment 包=`45`，批准排除包进入标签数=`0`。
- `T10/T10-Error/T10-Error-2` scope 100% 来自 manifest，不从目录猜测。
- T01–T12 修改、Movement 使用、训练、阈值修改、geometry 修改均为 `0`。

### Gate 1：target lineage

- 45/45 启用 Segment 包映射成功。
- direct ID 包、其中 Road drift 包和 Road partition lineage 包分栏统计。
- Road partition lineage 的目标 Road 缺失、重复 owner、后继额外 Road、空 Road、
  geometry 推断均为 `0`；direct ID 的 Road drift 只审计、不作为映射失败。
- 已知 4 个 ID 漂移包必须分别形成 4/3/7/13 个当前后继 Segment，
  目标 Road 集合无遗漏、无重复。

### Gate 2：标签与上下文隔离

- `T10` 全 Case Segment 标签数=`6,207`。
- 启用 Segment 包的当前 target/descendant 标签数以正式 lineage 审计为准。
- `T10-Error/T10-Error-2` 非目标上下文进入 label/loss/metric 数=`0`。
- 上下文只允许 `context_input_eligible=true`、`context_input_weight=0.3`。
- 新 label denominator、context-only denominator 和两者合计必须精确等于 `8,863`。

### Gate 3：expected-failure 双层合同

- Case terminal：49 `LEGAL` + 2 `EXPECTED_FAIL` 保持不变。
- 每个 expected-failure Case 的失败只定位到其冻结 `failure_group_ids`。
- Case 级级联覆盖/标签屏蔽数量=`0`。
- `T10:609214532` 的 1,795 个 Segment不再整体记为
  `expected_swsd_baseline_failure`；只有实际失败 group 执行对象级失败/fallback。

### Gate 4：历史结论重解释

- 输出逐阶段 invalidation ledger，至少覆盖 Scheme A baseline、Dataset-P0、
  P1、P2-P1、P2-P2 系列和 P2-P3-P0/P1。
- 原始 artifacts/hash 不删除、不覆盖。
- 结构骨架、candidate inventory、49+2 RoadGraph 安全等不依赖旧标签分母的事实保留；
  scorer 训练、错误率、coverage、recall、macro-F1 和 stable-wrong 结论标为需重算。

### Gate 5：确定性、GIS 与资源

- 正式 Run A/B 的 scope、mapping、label、expected-failure 和 invalidation
  内容签名一致。
- CRS 只读一致、geometry read/write=`0`、skeleton mutation=`0`、
  content repair=`false`、silent fix=`false`。
- GPU VRAM=`0`，CPU RSS `<=4GB`，单次 wall `<=10min`。

## 6. 阶段决策

- 全部门禁通过：`P05_SCHEME_A_DATASET_P1_GO`
- lineage 不完整或歧义：`P05_SCHEME_A_DATASET_P1_MAPPING_NO_GO`
- 上下文泄漏、分母或 expected-failure 分层失败：
  `P05_SCHEME_A_DATASET_P1_SCOPE_NO_GO`
- 输入/hash/确定性/GIS/资源失败：
  `P05_SCHEME_A_DATASET_P1_AUDIT_NO_GO`

任何结论都不自动授权训练、在线 proposal、生产接入、T01–T12 修改或 Git 操作。

## 7. 完成结论

- 正式判定：`P05_SCHEME_A_DATASET_P1_GO`
- 正式 Run A/B：`p05_scheme_a_dataset_p1_20260723_01/_02`
- 内容 signature：
  `bc848a8a0eeda04c14b358d505bc70258deaf36bb40cb617611ba7c4d205065c`
- 45/45 Segment 包映射成功：41 个 direct ID（其中 5 个 Road drift），
  4 个 Road partition lineage，后者分别映射 3/4/7/13 个当前 Segment。
- 新 Segment label/context 分母=`6,275/2,588`；其中 T10 Case truth=`6,207`，
  Segment 包 target/descendant=`68`，上下文 label leakage=`0`。
- 旧 expected-failure 全 Case 级联 mask=`5,862` 个 seed-object 行；
  新合同 corrected cascade mask=`0`，每个 Case/seed 只定位 1 个实际失败 group。
- Run B `reference_run_match=true`，核心四工件逐字节一致；CRS=`EPSG:3857`，
  geometry read/write、骨架 mutation、repair、silent fix、训练、Movement 均为 0。
