# P05-Scheme-A-P2-P0：JunctionUnit 一致 Segment Carrier 联合 Oracle

## 1. 状态与授权

- 状态：已完成；`P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`
- 授权日期：2026-07-22
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data` 中方案 A baseline 冻结的 51 个 RoadGraph Case
- 显式排除：`T10-Error / 1213556_1263661`
- Git 边界：不提交、不推送

本阶段承接已完成且判定 `P05_SCHEME_A_P1_MODEL_NO_GO` 的 P1。P1 已证明逐 Segment 判断可学习，但逐对象 Road/Node bundle 在整图组合时存在跨来源 Node carrier 冲突。本阶段不训练模型，先证明 Segment Road 与 JunctionUnit 共享 Node 分层后是否存在安全、可学习的联合真值。

## 2. 阶段目标

在冻结 T01 Segment 集合和 Junction—Segment 关系的前提下：

1. 保留 Segment 对独立 Road carrier 的选择；
2. 把共享 Node carrier 从 Segment bundle 中分离，由 JunctionUnit 统一选择；
3. 建立 truth-free Segment Road/Junction Node carrier 候选和 label-only 联合 Oracle；
4. 对无合法 carrier-set 的 Junction/Segment执行已确认 fallback，并输出 `RealityChangeClue`；
5. 形成 51 Case 的逻辑 RoadGraph、安全覆盖上限和是否值得进入 P2-P1 联合模型的结论。

Movement 本阶段冻结：不生成候选、不选择、不修改、不训练、不进入覆盖率或成败分母。

## 3. 输入隔离

### 3.1 Truth-free candidate 阶段

- 冻结 Scheme A baseline 的 T01 Segment/Junction 业务骨架，但不得读取 carrier label、T06 final Road/Node truth 或 fallback truth。
- 只读取正式 P1 candidate run 中登记的 T01/proposal Road/Node/relation lineage。
- 输出 Segment Road candidate 引用和 Junction Node candidate option；所有 candidate 必须 `truth_derived=false`。
- candidate manifest/hash 完成后，Oracle 阶段才允许读取 label-only truth。

### 3.2 Label-only Oracle 阶段

- P1 dataset 的 Segment truth candidate、Scheme A carrier label、T06 final Node truth 和 relation access 只用于联合真值、选择和评价。
- truth 不得增加、删除或改写 candidate；candidate 缺失必须失败/fallback。
- T06 truth Node 若自身不满足 JunctionUnit 一致性，不得 silent normalize，只能选择其它已冻结 candidate 或触发 fallback。

## 4. 联合 carrier 语义

- `SegmentRoadChoice`：每个 FrozenSegment 选择一个 P1 已冻结 Road candidate；默认只允许个体 truth candidate 或 SWSD identity fallback。
- `JunctionNodeChoice`：同一 JunctionUnit 对被选 Road 引用的共享 Node ID 统一选择 T01/proposal payload。
- `JunctionCarrierSet`：一组 Segment Road choice 与一个共享 `mainnodeid` 分组下的 Node choice。
- `JointTruthExact`：最终 Segment Road candidate 与 P1 个体 truth candidate相同；KEEP_SWSD 仍可作为正确自动判断计入，不把 fallback 输出冒充 RCSD 替换。
- `UseRcsdRetention`：原 `USE_RCSD` truth 在合法联合图中仍保留其 truth Road candidate 的比例，必须独立报告，不能被 KEEP_SWSD 数量掩盖。

## 5. Fallback

- Segment 自身 access、独立 Road、candidate payload、Road/Node 引用或几何失败：只回退该 Segment。
- JunctionUnit 无共同 Node carrier/mainnode 分组：关联全部 Segment保留 SWSD，并记录 Junction fallback。
- fallback 后仍不合法：该对象/Case失败并输出 `RealityChangeClue`。
- 不新增、不删除、不重连 Segment，不修改 Movement，不补点、不吸附、不改写 payload。

## 6. 职责视角

### 产品

- 准确性和安全性优先于自动化率。
- fallback 符合业务认知时可以形成安全终态，但必须把联合 exact、RCSD retention 和 fallback 分开报告。
- 输出 `GO / UPSTREAM_CARRIER_NO_GO / SAFETY_NO_GO`，不得把 KEEP_SWSD 占比高误称为替换能力。

### 架构

- candidate 与 Oracle 两级不可变 manifest/hash 隔离。
- Segment Road ownership 与 JunctionUnit shared Node carrier 分层。
- hard gate 只验证冻结骨架、共享 carrier、schema、引用、方向、CRS、拓扑和 lineage。

### 研发

- 只新增 P05 Python callable、测试和 SpecKit 工件。
- 不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- 不修改 T01–T12 正式实现，不覆盖既有 run。

### 测试

- 覆盖 manifest/hash、candidate/truth 隔离、Movement 零决策、candidate-specific safety、共享 Node payload、mainnode 冲突、Segment/Junction fallback、expected failure 和 no-repair。
- 覆盖 candidate 缺失、同 ID 不同 payload、无共同 mainnode key、SWSD fallback仍非法。

### QA

- 51 Case、8,863 Segment 和全部 JunctionUnit 分母不得隐藏。
- CRS、几何语义、Road/Node 引用、有向拓扑、lineage、资源和 deterministic signature 全量可定位。
- 失败与 fallback 必须保留原始冲突证据。

## 7. 成功标准

### Gate 0：范围与零泄漏

- 51 Case；排除项出现 0 次；Segment 数 8,863。
- Movement candidate/decision/evaluation count 均为 0。
- truth input/derived candidate/feature count 均为 0。
- skeleton mutation 为 0；全部输入 manifest/hash/CRS 可定位。

### Gate 1：联合真值完整性

- 每个 Segment 有 Road终态；每个 JunctionUnit 有 Node carrier 终态或显式冲突。
- 可用 Segment truth candidate reachability 为 100%。
- 同一 JunctionUnit 最终 Node carrier 具有一致 mainnode 分组。
- 同一 Road/Node ID 不得出现不同核心 payload。
- lineage 完整率为 100%。

### Gate 2：安全覆盖与价值

- Segment `joint_truth_exact_coverage >= 0.50`。
- `USE_RCSD` 错误替换和 `KEEP_SWSD` 错误替换均为 0。
- `USE_RCSD` truth retention 必须独立报告；若 `<0.50`，本阶段即使安全门通过也判 `UPSTREAM_CARRIER_NO_GO`，不得启动 P2-P1 训练。
- 40 个 unsafe ADVANCE_RIGHT 发布数为 0；全部冲突具有 clue/fallback lineage。

### Gate 3：RoadGraph 安全

- 49 Case `LEGAL`；`T10:74155468`、`T10:609214532` 精确为 `EXPECTED_FAIL + clue + publish=false`；新增失败为 0。
- CRS、重复 ID、引用、方向、有向拓扑和 Junction mainnode hard failure 为 0。
- `relaxation=false`、`content_repair=false`、`silent_fix=false`。

### Gate 4：确定性与资源

- 两轮 candidate、joint truth、selection、fallback、clue、RoadGraph signature 一致。
- P95/max `<=30s/120s`；RSS `<=16GB`；GPU 不需要；总 CPU `<=1h`。

## 8. 完成定义

SpecKit、source-of-truth、candidate/Oracle callable、单元与破坏测试、两轮 51 Case run、RoadGraph/GIS/资源审计和 validation summary 全部完成后才可关闭本阶段。

- 全部门禁通过：`P05_SCHEME_A_P2_P0_GO`
- 安全通过但 `USE_RCSD` retention 或候选能力不足：`P05_SCHEME_A_P2_P0_UPSTREAM_CARRIER_NO_GO`
- RoadGraph 安全失败：`P05_SCHEME_A_P2_P0_SAFETY_NO_GO`

任何结论都不授权模型训练、生产接入或 T01–T12 修改。

## 9. 实测结论

- 正式 Candidate A/B：`p05_scheme_a_p2_candidate_20260722_01/_02`。
- 正式 Oracle A/B：`p05_scheme_a_p2_oracle_20260722_05/_06`。
- 51 Case、8,863 Segment；Movement candidate/decision/evaluation、truth-derived candidate/feature、骨架 mutation 均为 0。
- joint truth exact=`4,844/8,863=0.546542`，通过总体 `0.50` 门槛。
- `USE_RCSD` truth retention=`363/2,190=0.165753`，未通过 `0.50` 门槛。
- RoadGraph 为 49 `LEGAL` + 2 精确 `EXPECTED_FAIL`，新增失败为 0；错误替换、unsafe ADVANCE_RIGHT 发布、repair/silent fix 均为 0。
- A/B 的 candidate、Segment、Junction、clue、RoadGraph 和指标 signature 全部一致；资源门与 QGIS 输入几何审计通过。

因此本阶段证明联合安全 fallback 和 RoadGraph 物化可行，但当前 T01/proposal Node carrier option 无法承载足够多的正确 RCSD Segment 组合。不得启动 P2-P1 scorer；下一阶段若继续，必须另行讨论并授权不改写冻结业务骨架的上游 carrier option 扩展。
