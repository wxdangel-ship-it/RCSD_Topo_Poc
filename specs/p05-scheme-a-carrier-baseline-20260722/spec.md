# P05 方案 A：冻结业务骨架下的 Carrier 决策与基线重建

## 1. 状态与授权

- 授权日期：2026-07-22
- 生命周期：P05 POC 正式阶段
- 唯一实施工作树：`E:\Work\RCSD_Topo_Poc__wt_p05_neural_road_20260721`
- 数据范围：仅 `E:\TestData\POC_Data` 中已冻结的 51 个 RoadGraph Case
- 显式排除：`T10-Error / 1213556_1263661`
- Git 边界：本阶段不提交、不推送

本阶段以 `docs/archive/2026-07-22-p04-p05-junction-segment-road-node-business-ontology.md` 中已确认的方案 A 为业务基线。旧 JSG-PTO-P0/P1/P2/P3 只保留历史实验与原始证据，不再定义当前业务本体或当前验收指标。

## 2. 阶段目标

在不修改 T01–T12 的条件下，建立可供后续模型训练使用的方案 A 数据与执行合同：

1. 冻结 T01 的 Junction—Segment 业务骨架和 PhysicalMovement 存在性；
2. 将普通提右统一为 `segment_type=ADVANCE_RIGHT` 的 Segment，废止当前业务层 `SegmentConnector`；
3. 把当前 T06 策略结果重建为 `SUCCESS_DIRECT / SUCCESS_WITH_FALLBACK / FAIL` 基线；
4. 只生成 carrier 选择、Movement carrier 和异常概率所需的软标签，不生成骨架增删改标签；
5. 实现确定性的最小依赖闭包 fallback；
6. 对显式证据冲突生成 `RealityChangeClue`，禁止 silent fix；
7. 形成 51 Case 可复现、可审计、可双跑对比的不可变基线 run。

本阶段不训练新神经模型，不把旧 P3 指标迁移为新方案指标，也不发布 Road/Node 到正式主链。

## 3. 业务不变量

### 3.1 冻结对象

- T01 Segment ID 集合、`segment_type`、`pair_nodes`、`junc_nodes`、Road 引用和方向基础事实不可由模型改变；`ADVANCE_RIGHT` 的 source/target Segment access 也是冻结骨架。
- Junction 与 Segment 的已确认关系不可由模型改变。
- PhysicalMovement 的业务存在性不可由模型新增或删除。
- 每个正式 Segment 必须至少有一条独立 Road；缺失时失败并输出线索。
- `junc_nodes` 默认是 hard-required relation；仅显式 `detached/exempt` 且 lineage 完整时允许例外。

### 3.2 模型允许输出

- carrier 候选的评分、排序、置信度和不确定度；
- Segment、JunctionUnit 或 PhysicalMovement 的 carrier 方案选择；
- Review/失败概率；
- 证据冲突的异常线索。

### 3.3 模型禁止输出

- 新增、删除、合并或拆分 Segment；
- 改变 Segment 的 Junction 归属；
- 新增或删除 PhysicalMovement；
- 以 PTO-A 或其它优化器改写业务骨架；
- 通过吸附、补路、重连、改 ID 或改 geometry 消除 hard failure；
- 将 `RealityChangeClue` 自动提升为正式业务结构。

## 4. Fallback 规则

fallback 以最小业务依赖闭包为单位：

1. Segment carrier 失败：仅该 Segment 保留 SWSD，并阻断与其直接相关的新 Movement；
2. Junction 证据冲突：该 Junction 关联的全部 Segment 保留 SWSD；
3. Movement carrier 独占且不影响共享 JunctionUnit：只回退该 Movement；
4. Movement carrier 被共享或影响 JunctionUnit 内部拓扑：升级为 Junction fallback；
5. 原始 SWSD Segment 缺少合法独立 Road 或 Road/Node 引用不完整：fallback 失败，输出 `RealityChangeClue`；
6. fallback 只有在保留结构符合统一本体、依赖闭包完整且拓扑 hard gate 通过时，才计 `SUCCESS_WITH_FALLBACK`。

准确性与安全性优先于自动化率；不允许为提高自动化率错误替换 SWSD。

## 5. 功能需求

### FR-001 冻结骨架

系统必须从已登记、hash 完整的 T01/P05 历史 run 构建 51 Case 方案 A 骨架，逐 Case 保存 canonical signature。骨架必须覆盖全部 T01 Segment，不得只覆盖旧 JSG `StandardSegment`。

### FR-002 提右重解释

全部 T01 `advance_right` 必须表示为含 `source_segment_access/target_segment_access` 的 `ADVANCE_RIGHT Segment`。当前 T01 未显式存储 access 时，只接受独立 Road 唯一有向端点与端点处唯一普通 Segment owner的可追溯映射；任一侧不唯一必须形成 clue 并失败，不得猜测。当前业务输出中 `SegmentConnector` 对象数必须为零；旧 Connector 记录只允许作为历史 lineage。

### FR-003 策略基线

每个 T01 Segment 必须映射当前 T06 `relation_status`：

- `replaced` -> `SUCCESS_DIRECT`；
- `retained_swsd`、`replaced+retained_swsd` -> `SUCCESS_WITH_FALLBACK`；
- `failed` -> `FAIL`；
- 未登记状态 -> hard failure，不得自行解释。

### FR-004 软标签

Segment 标签只描述 `USE_RCSD / KEEP_SWSD / MIXED_CARRIER / REVIEW_FALLBACK`。Movement 标签只描述 Road/Node carrier realization；PhysicalMovement 存在性不作为可学习的增删目标。T10 Case 级使用 `0.7/0.7`，Segment 级目标对象使用 `0.7`、其它上下文使用 `0.3`；缺失 carrier 标签必须 mask，不得编码为负样本。

### FR-005 RealityChangeClue

每条线索必须包含 Case、scope、object ID、evidence code、证据路径/hash、建议 fallback 层级和处理状态。线索本身不修改骨架。

### FR-006 fallback 闭包

fallback resolver 必须严格实现第 4 节规则，并输出受影响 Segment、Junction、Movement、保留 SWSD Road 和失败原因。相同输入双跑输出 signature 必须一致。

### FR-007 审计与不可变输出

正式 run 必须校验输入 manifest/hash，目标目录不得覆盖；记录参数、环境、耗时、RSS、CRS、对象数、策略基线、标签、线索、fallback、所有输出 SHA-256 以及 `content_repair=false / silent_fix=false / skeleton_mutation_count=0`。

## 6. 职责视角

### 产品

以当前策略方案为业务比较基线，区分直接成功、正确 fallback 和失败；自动化率不得覆盖安全失败。

### 架构

业务骨架与 carrier realization 分层；历史 PTO-A 和 SegmentConnector 不得进入当前方案 A 运行合同。

### 研发

只新增 P05 Python callable 和模块内数据合同，不新增 CLI、root script、T10 stage、`__main__.py` 或 Makefile target，不修改 T01–T12。

### 测试

覆盖骨架篡改、提右、未知策略状态、Segment/Junction/Movement fallback、共享 carrier 升级、SWSD Road/Node 不合法、manifest/hash 篡改和确定性。

### QA

真实 51 Case 必须覆盖 CRS、Road/Node 引用、Junction mainnode 分组、Movement carrier、lineage、资源与双跑确定性；任何无法解释的差异进入 clue/failure，不做 silent fix。

## 7. 验收标准

- SC-001：51/51 Case 纳入，排除项出现次数为 0。
- SC-002：T01 Segment 集合、ID 和 `pair_nodes/junc_nodes` 覆盖率 `100%`；骨架修改数 `0`。
- SC-003：全部 `advance_right` 以 `ADVANCE_RIGHT Segment` 表达，source/target access 可追溯或显式 `access_valid=false` 并输出 clue；当前 `SegmentConnector` 数 `0`。
- SC-004：每个 Segment 都有独立 SWSD Road 引用；Road/Node 可发布性不足的对象显式失败并生成 clue，禁止补造。
- SC-005：策略结果映射率 `100%`，并分别报告 `SUCCESS_DIRECT / SUCCESS_WITH_FALLBACK / FAIL`。
- SC-006：所有可用 Segment/Movement carrier 标签的 lineage、fold、weight 和 mask 完整率 `100%`；骨架增删改标签数 `0`。
- SC-007：所有显式冲突均有 `RealityChangeClue`，clue lineage 完整率 `100%`。
- SC-008：fallback 单元和升级规则的单元测试全部通过；业务不正确 fallback 成功数 `0`。
- SC-009：CRS、ID、Road/Node 引用和有向拓扑不做 silent fix；`content_repair=false`、`silent_fix=false`。
- SC-010：两轮独立 run 的 skeleton、baseline、label、clue 和 fallback signature 完全一致。
- SC-011：P95 单 Case处理 `<=30s`、max `<=120s`、RSS `<=16GB`、无需 GPU、总 CPU `<=1h`。

## 8. 完成边界

SpecKit、项目/P05 source-of-truth、Python callable、单元测试、两轮真实 51 Case run、确定性审计和 validation summary 全部完成后，本阶段才可标记完成。模型训练和生产接入必须另行授权。
