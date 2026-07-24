# P05-JSG-PTO-P0：本体、Oracle 与编译证明

## 1. 状态与授权

- 状态：`COMPLETED / P0 GO`
- 授权日期：2026-07-21
- 授权来源：用户明确要求按已归档 `P05-JSG-PTO` 方案启动下一轮目标
- 作用范围：仅 `E:\TestData\POC_Data` 内已冻结的 51 个 RoadGraph Case
- 显式排除：`T10-Error / 1213556_1263661`

## 2. 产品目标

证明“Junction—Segment—Movement 业务语义图”可以完整表达当前 51 Case 中可确认的道路业务结构，并能通过确定性编译后端生成合法的 T06 Step3 F-RCSD Road/Node。P0 回答的是本体、真值和编译合同是否成立，不回答模型能否泛化。

## 3. 范围

### 3.1 本轮包含

1. 固化 `JunctionUnit`、`StandardSegmentUnit`、`JunctionSegmentRelation`、`PhysicalMovement`、`SegmentConnector`、`TerminalJunction` 与显式闭环合同。
2. 从已冻结、可追溯的 T01/T05/T06 与 R2 Oracle 资产生成 canonical JSG truth。
3. 建立 JSG schema、语义、引用、方向、拓扑、CRS 与确定性 evaluator。
4. 建立 `JSG truth -> carrier realization -> R2 edit IR -> Road/Node` 编译器。
5. 在相同 51 Case 上执行两轮独立运行，形成不可变证据与门禁结论。

### 3.2 本轮不包含

- 不训练神经网络、GBDT 或其它 scorer。
- 不从推理时输入生成 JSG 候选，不执行 PTO-A/PTO-B learned/Oracle selection。
- 不新增 repo CLI、root script、Makefile target、模块 `__main__.py` 或 T10 stage。
- 不修改 T01-T09 的接口、业务规则或生产主链。
- 不正式接入点云、BEV、轨迹或生产数据。
- 不把自动转换字段提升为新的上游强规则。

## 4. 角色视角

### 产品

P0 的交付物是一份可审计的 JSG 业务设计图和可编译性证明。Road/Node 是交付载体；JSG 业务语义是本轮主要验收对象。

### 架构

JSG 位于证据层与 RoadGraph 实现层之间。R2 edit-set/materializer 继续作为编译后端，不再被视为 JSG 最高层业务对象。真值转换、语义评价和编译分别实现，禁止互相读取未声明的内部状态。

### 研发

只新增 P05 模块内 Python callable 和数据合同；复用现有 manifest、hash、R2 Oracle、materializer 与 M0 evaluator。任何无法解释的字段、引用或 carrier 都输出异常或 `REVIEW`，不做 silent fix。

### 测试

单元测试覆盖对象 schema、两个端点、显式闭环、环岛截断、多 `THROUGH` 进入 `REVIEW`、Connector 有向一对一、Movement 引用、编译不可行和确定性。回归测试必须保持现有 P05 测试通过。

### QA

真实 51 Case 验证 CRS、ID、引用、方向、有向拓扑、几何语义、输入/参数/环境/hash lineage 和性能。零实例对象类型必须显式报告，不得以“未发现”冒充已验证真实样本。

## 5. 业务真值合同

### 5.1 数据来源

- T01 `segment.gpkg`：`pair_nodes`、`junc_nodes`、`roads`、`sgrade`、`segment_type`。
- T01 `nodes.gpkg` / `roads.gpkg`：Junction 类型、方向、carrier、dead-end 与构段证据。
- T05：Junction 到 RCSD Node 的锚定证据。
- T06 F-RCSD Road/Node：编译真值和 PhysicalMovement 的物理 carrier 拓扑。
- 已冻结 R2 Oracle：label-only Road/Node edit IR 与精确物化合同。

字段只按已有项目/模块事实与本 SpecKit 中的显式映射使用。不能解释或互相冲突的值进入 anomaly/review，不从局部数据反推新业务语义。

### 5.2 关键规则

- StandardSegment 恰有两个端点位置；同一 Junction 两端仅在显式 loop 证据存在时允许。
- `pair_nodes` 形成 `ENDPOINT`；`junc_nodes` 形成 `THROUGH`，附属路口不自动拆分 Segment。
- 自动发布 Junction 最多一个 `THROUGH` Segment；多个贯穿主体必须 `REVIEW`，不得自动选一个。
- 环岛 Junction 强制截断相关 Segment；复杂分歧合流不按类型自动截断。
- Segment 方向从有向 carrier 事实推导，不使用 `pair_nodes` 的字符串顺序猜测。
- `advance_right` 只生成待审计的 SegmentConnector；不能唯一证明 source/target access 时为 `REVIEW`。
- PhysicalMovement 表达物理可达，T09 交通限制不反向删除它。
- TerminalJunction 类型只由明确 dead-end/data-boundary/unknown 证据确定。

## 6. 成功标准

### Gate 0：范围与 lineage

- Case 数恰为 `51`，排除项出现次数为 `0`。
- 每个 Case 的输入 manifest、T01/T05/T06/R2 Oracle 路径与 SHA-256 可定位。
- truth 为 `label_only=true`；P0 不声明任何推理泛化能力。

### Gate 1：本体可表达性

- 51 Case 中实际出现的 Junction、Segment、Relation、Movement、Connector、Terminal 和 loop 真值实例可表达率 `100%`。
- 每种对象同时报告 `observed_count`、`expressed_count`、`review_count`、`unexpressed_count`；`observed_count=0` 不计作真实数据正例通过。
- 已知多贯穿冲突全部进入 `REVIEW`，自动选择数量为 `0`。
- schema/reference/direction/loop/roundabout hard failure 为 `0`。

### Gate 2：Oracle 语义往返

- canonical JSG serialize/deserialize 后 51/51 语义 signature 完全一致。
- 两轮独立运行的 Case 顺序无关 signature 完全一致。
- `content_repair=false`、`silent_fix=false`。

### Gate 3：编译与 RoadGraph hard gate

- 51/51 JSG truth 均能解析到已声明 carrier realization，并编译成 R2 edit IR。
- 51/51 Road/Node 物化成功；Road/Node CRS、ID、引用、几何和有向拓扑 hard failure 均为 `0`。
- 以冻结 T06 truth 评价时 Road/Node/属性/有向拓扑完全一致。该精确性仅证明 Oracle compiler，不等于未来 JSG 候选可达或模型能力。
- 编译器不调用 T01-T06 业务规则，不补路、不吸附、不重连。

### Gate 4：资源与审计

- 单 Case P95 wall time `<=30s`、最大 `<=120s`；全量总 CPU time `<=1h`。
- 峰值 RSS `<=16GB`，GPU 不需要。
- 每个 run 记录 Python/OS/GIS 库版本、参数、计数、耗时、RSS、输入输出 hash。

任一 hard gate 失败即形成 P0 no-go 和异常清单，不得通过 Case 特判或放宽分母掩盖。

## 7. 完成定义

只有 SpecKit、项目/模块 source-of-truth、Python callable、单元/回归测试、两轮真实 51 Case 证据和 validation summary 全部完成，P0 才可标记完成。

上述完成定义已于 2026-07-21 满足。正式验收结论见 `validation_summary.md`；该 GO 仅放行 JSG 本体、label-only Oracle 与确定性 compiler 合同，不代表候选生成、PTO 选择、神经网络泛化或生产接入已经通过。
