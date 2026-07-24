# P05-Scheme-A-P1：Object-Conditioned Carrier Scorer

## 1. 状态与授权

- 状态：已完成，`P05_SCHEME_A_P1_MODEL_NO_GO`
- 授权日期：2026-07-22
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data` 中方案 A baseline 冻结的 51 个 RoadGraph Case
- 显式排除：`T10-Error / 1213556_1263661`
- Git 边界：不提交、不推送

本阶段承接已完成的 `P05-Scheme-A Carrier baseline`。旧 M1/M2R/R2/PTO/JSG-PTO-P0/P1/P2/P3 只保留历史架构与实验事实；旧 `SegmentConnector`、PTO-A 骨架选择和旧 Review 指标不得进入当前业务目标。

## 2. 阶段目标

训练一个冻结业务骨架下的 object-conditioned 神经评分器，使其在未见 business-ID Case 上：

1. 为每个 FrozenSegment 的 `USE_RCSD / KEEP_SWSD / MIXED_CARRIER / REVIEW_FALLBACK` carrier 方案评分；
2. 为每个已冻结 PhysicalMovement 选择 Road/Node carrier realization；
3. 输出 carrier confidence、uncertainty 和 RealityChangeClue 概率；
4. 对高风险、候选缺失或低置信对象触发最小依赖闭包 fallback；
5. 在确定性 hard gate 后形成合法、可追溯的方案 A RoadGraph 结果。

模型不得增删改 Segment、Junction—Segment relation 或 PhysicalMovement 存在性。准确性和安全性优先于自动化率。

## 3. 冻结输入与物理隔离

### 3.1 Label-only 输入

- 方案 A 正式 baseline：`p05_scheme_a_baseline_20260722_12`；`_13` 只用于确定性对照。修正前 `_10/_11` 只保留历史证据，不得作为 P1 监督输入。
- Segment/Movement carrier label、target payload、RealityChangeClue、fallback truth、T06 canonical relation/status/reason 和 canonical T06 Road/Node 只能在候选冻结后用于监督或评价。
- label-only path/hash 不得进入 feature token、数值特征或模型上下文。

### 3.2 推理可用输入

- 方案 A 冻结的 Segment/Junction/PhysicalMovement 业务身份与关系；carrier ID、truth access node 和 canonical selected payload 必须剥离。
- 已登记、`truth_input_count=0`、`truth_derived_candidate_count=0` 的策略 proposal/replay manifest。
- T01 Segment/Road/Node、策略重放产生的候选 Road/Node/relation、对象局部几何与拓扑统计。
- 只允许局部平移/缩放归一后的几何统计；绝对坐标、Case/business/object/candidate/group ID 不进入模型。

### 3.3 Candidate 冻结门禁

candidate builder 必须先独立生成、哈希并冻结 carrier candidates，再读取 baseline label 做 label-only join。候选生成 API 不接受 truth/label path。全部可用 Segment/Movement label 的 exact candidate reachability 必须为 `100%`；否则停止训练并判定 `P1_UPSTREAM_CANDIDATE_NO_GO`。

## 4. Carrier candidate 合同

### 4.1 Segment

每个 Segment 至少包含：

- `SWSD_IDENTITY`：冻结 T01 独立 Road；
- 一个或多个 `TRUTH_FREE_STRATEGY_PROPOSAL`：登记策略重放产生的 RCSD/mixed Road realization；
- `REVIEW_FALLBACK`：无 carrier payload 的安全回退选项。

候选可以携带 Road 数量、source 构成、方向覆盖、端点闭包、局部长度/曲率/连通统计与 provenance token，但不得携带 canonical relation status/reason 或“正确答案”标记。

### 4.2 PhysicalMovement

PhysicalMovement 的业务存在性固定。candidate builder 从 truth-free proposal RoadGraph 中重建 source/target Segment 在 JunctionUnit 的共享 Node carrier set，并保留 SWSD/fallback 选项。候选不得包含 canonical carrier IDs 或旧 JSG Oracle cost。

### 4.3 Fallback

以下情况无条件进入 hard fallback，不由模型覆盖：candidate 缺失、ADVANCE_RIGHT access 不唯一、SWSD 独立 Road 非法、Road/Node 引用或 CRS 不合法、Junction 现实冲突。模型低置信或高异常概率也可触发 fallback，但不得缩小 hard fallback 范围。

fallback 按业务对象严格隔离：Segment 冲突只回退该 Segment，不自动回退其 source/target PhysicalMovement；Movement 仅在自身候选缺失、低置信或 carrier 冲突时回退。仅当该 Movement 的有效 carrier 确实被共享或影响 Junction 内部拓扑时，Movement fallback 才升级为 Junction fallback。

同 ID T01/proposal payload 只有在二维几何与 T01 核心 Road/Node 字段经 ID 类型归一后精确一致时，才可视为 carrier 语义等价；proposal 独有审计扩展字段可忽略。执行器不得合并或改写属性，必须保留确定性原 payload 并记录 coalesce ID；核心字段或几何不同仍为 hard conflict。

## 5. 模型与训练协议

- 模型：`SchemeACarrierGraphSetScorer`，candidate encoder + object/context encoder + gated interaction MLP；不使用自由 RoadGraph decoder。
- 参数量目标：`1M~5M`；超过 `5M` 为 hard fail。
- 损失：加权 listwise candidate loss + anomaly/fallback BCE；label weight 按冻结 `0.7/0.3` 口径使用。
- 切分：M0 business-ID grouped 5-fold；每个 Case 恰好一次 outer held-out。
- inner validation、feature vocabulary、normalization、class weight、early stopping 和阈值只使用 outer train。
- 正式实验：3 seeds × 5 folds；禁止选择最好 seed。
- 推理只输出 candidate score/cost、confidence、uncertainty 和 anomaly probability；确定性执行器负责 hard gate、fallback 与 RoadGraph 物化。

## 6. 职责视角

### 产品

- 以当前策略三态和方案 A carrier truth 为比较基线。
- 自动化覆盖率不能通过错误替换 SWSD 提升；fallback 符合业务认知时可计成功。
- 输出明确区分 `MODEL_GO / MODEL_NO_GO / UPSTREAM_CANDIDATE_NO_GO`。

### 架构

- frozen skeleton、candidate、label、fold model、score、fallback、RoadGraph、evaluation 分层 manifest/hash。
- 历史 PTO-A 不参与骨架选择；硬门禁只验证合法性和业务不变量。
- scorer 可以决定 carrier 内容，但不能改变业务对象存在性。

### 研发

- 只新增 P05 模块 Python callable、测试和 SpecKit 工件。
- 不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target。
- 不修改 T01–T12 正式实现，不覆盖既有不可变 run。

### 测试

- 覆盖 manifest/hash、candidate/label 隔离、forbidden feature、grouped split、inner validation、unknown token、listwise loss、参数量、checkpoint、confidence、fallback 闭包和 skeleton mutation。
- 覆盖候选缺失、ADVANCE_RIGHT access 冲突、共享 Movement carrier、Junction 冲突与 Road/Node 引用破坏。

### QA

- 51 Case 分母、三 seed、每 fold/类型/Case 指标不得隐藏。
- CRS、几何语义、Road/Node 引用、有向拓扑、lineage、资源和 deterministic signature 全量可定位。
- 任何硬失败均保留原始证据，不做 content repair 或 silent fix。

## 7. 成功标准

### Gate 0：范围、候选与零泄漏

- 51/51 Case，排除项出现 0 次；Scheme A baseline 与 M0 fold/signature 精确匹配。
- truth-free Segment/Movement candidate exact reachability `100%`。
- truth/label/Oracle/Case/business/object/candidate/group ID 与绝对坐标 feature hit `0`。
- outer train/held-out 交集 `0`；每个 Case恰好一次 held-out。

### Gate 1：Segment carrier 业务能力

- `USE_RCSD / KEEP_SWSD / REVIEW_FALLBACK` macro-F1 `>=0.85`；14 个 `MIXED_CARRIER` 只单列报告，不作为独立 GO 门禁。
- `USE_RCSD` precision `>=0.95`。
- unsafe/review fallback recall `>=0.98`。
- accepted coverage `>=0.50`，且不得通过降低 precision 达成。

### Gate 2：Movement 与异常能力

- 可用 Movement carrier set exact match `>=0.90`。
- RealityChangeClue / unsafe anomaly recall `>=0.95`、precision `>=0.80`。
- 神经 scorer 的 Segment macro-F1 比最强 train-only non-neural baseline 至少高 `0.03`。

### Gate 3：稳定性

- 三个 seed 均通过 Gate 0~2。
- 三 seed 主 macro 指标极差 `<=0.03`。
- 同 seed 双跑 candidate/model/score/selection/fallback/RoadGraph signature 一致。

### Gate 4：RoadGraph 安全

- 每个 seed 的 51/51 Case均有确定终态：其余49 Case post-hard-gate RoadGraph 全部合法；`T10:74155468` 与 `T10:609214532` 精确输出 `EXPECTED_FAIL + RealityChangeClue` 且不得发布或修复。两个预期失败仍保留在模型、fallback与异常指标分母中。
- expected-failure manifest 与 failure signature 必须精确匹配；非预期 CRS、ID、Road/Node 引用、方向和有向拓扑 hard failure 为 0。
- 40 个已知 unsafe ADVANCE_RIGHT 发布数为 0；已知 Junction 冲突错误替换 SWSD 数为 0。
- `skeleton_mutation_count=0`、`truth_feature_count=0`、`relaxation=false`、`content_repair=false`、`silent_fix=false`。

### Gate 5：资源

- 参数量 `1M~5M`，RAM `<=16GB`，VRAM `<=8GB`。
- 单 fold 训练 `<=1h`，单 seed 5-fold `<=5h`，三 seed总训练 `<=15h`。
- scorer 单 Case P95 `<=5s`、max `<=20s`。

## 8. 完成定义

SpecKit、source-of-truth、candidate/dataset/scorer/executor callable、单元与破坏测试、51 Case candidate gate、3 seeds × 5-fold OOF、同 seed双跑、RoadGraph/GIS/资源审计和 validation summary 全部完成后，本阶段才可标记完成。

Gate 0~5 全部通过：`P05_SCHEME_A_P1_MODEL_GO`。任一模型门失败：`P05_SCHEME_A_P1_MODEL_NO_GO`；候选或零泄漏门失败则为 `P05_SCHEME_A_P1_UPSTREAM_NO_GO`。无论结论如何，本阶段都不授权生产接入。
