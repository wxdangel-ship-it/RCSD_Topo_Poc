# T09 Traffic Restriction Recovery Specification Draft

**Status**: Draft only / not implementation-ready
**Scope Mode**: SpecKit draft
**Source Fact Status**: This document is a change artifact under `specs/`; it does not register T09 as an Active module.

## 1. Business Goal

T09 的业务目标是基于 SWSD 数据还原路口处的交通限制，并在后续阶段把这些限制恢复到融合后的 RCSD / F-RCSD 数据上。

当前草案先收敛 Step1：优先建立 SWSD Arm 与 ArmMovement 结构承载面；本轮不定义 F-RCSD RoadNextRoad 输出，也不定义 restriction 表输出。

Step1 已确认的需求边界：

- 面向 SWSD 中 `kind_2 = 4` 的语义路口构建 Arm。
- 在这些 Arm 之间建立 ArmMovement 候选空间。
- 参考 P01 的 Arm / Movement 策略，但优先消费 T01 Segment 成果，减少重复拓扑追溯。
- 必须支持目标路口作为 Segment `junc_nodes` 时的内部切分。

Step1 的输出是后续交通限制分析的 SWSD 结构承载面，不直接生成 F-RCSD 交通限制成果。

## 2. Product View

用户需要先获得 SWSD 路口级的结构化运动空间：

- 每个 `kind_2 = 4` SWSD 语义路口有哪些 Arm。
- 每个 Arm 与相邻 Segment / Road 的关系是什么。
- 每个进入 Arm 到退出 Arm 的 Movement 候选是什么。
- Movement 的类型、方向、构建证据和风险是否可审计。

Step1 成功后，下游阶段才具备把 SWSD 显性交通限制记录挂接到 ArmMovement 的结构基础；最终是否需要生成其它成果形态不在当前草案中定义。

## 3. Current Step1 Scope

### 3.1 Inputs

Step1 预计消费：

- SWSD `nodes.gpkg`
  - 依赖字段：`id / mainnodeid / kind_2 / geometry`
  - 可选字段：`grade_2 / kind / grade / closed_con`
- SWSD `roads.gpkg`
  - 依赖字段：`id / snodeid / enodeid / direction / geometry`
  - 可选字段：`formway / segmentid / sgrade / kind`
- T01 `segment.gpkg`
  - 依赖字段：`id / sgrade / pair_nodes / junc_nodes / roads / geometry`

后续限制分析阶段可能消费 T08 Tool7 `sw_restriction_tool7.gpkg`，但 Step1 不读取 restriction 作为强规则输入，也不把 restriction 输出格式作为本阶段目标。

### 3.2 Target Junctions

Step1 仅处理 SWSD 代表语义路口 `kind_2 = 4`。

语义路口分组口径沿用项目既有规则：

- 有有效 `mainnodeid` 时按 `mainnodeid` 聚合。
- `mainnodeid = null / 空字符串 / 0 / 0.0 / none / null 字符串 / nan` 时退化为单节点语义路口。
- `kind_2` 字段名固定为小写，不兼容 `Kind_2`。

其它 `kind_2` 类型不进入 Step1 Arm / Movement 构建。后续如需支持 `2048 / 64 / 128` 等类型，必须单独扩展任务书。

### 3.3 Segment-Aware Arm Build

Step1 不应直接复制 P01 的长距离 trace 主链。T01 Segment 已经表达路口间 corridor，T09 Step1 应优先使用 Segment 成果减少重复工作。

建议初始策略：

1. 建立 `road_id -> segment_id` 与 `semantic_junction_id -> segment_id` 索引。
2. 对每个目标 `kind_2 = 4` 语义路口，收集与该语义路口 member node 相接的 SWSD Road。
3. 按 Road `direction` 判断 seed road 对目标路口的进入 / 退出能力。
4. 优先使用 seed road 所在 Segment 的 `roads / pair_nodes / junc_nodes` 确定 Arm corridor 与 terminal semantic junction。
5. 当 Segment 缺失或 seed road 无 Segment 归属时，允许执行受限局部拓扑 fallback，但必须输出 `segment_membership_missing` 或等价审计标记。
6. 不允许通过几何相近、最近邻或人工样本反推上游字段语义。

当目标路口出现在 Segment 的 `pair_nodes` 中，该 Segment 可作为从目标路口到另一端语义路口的 Arm corridor 证据。

当目标路口出现在 Segment 的 `junc_nodes` 中，Step1 必须支持内部切分：

- 基于目标路口 incident road 与 Segment member road，把穿越该目标路口的 Segment corridor 切分为路口两侧 Arm。
- 切分必须输出 split audit，记录输入 Segment、切分 road、切分 node、两侧 Arm 与 terminal junction。
- 如果输入拓扑不足以稳定切分，不得退化为“只输出人工复核即完成”；必须输出失败原因，例如 `segment_internal_split_unresolved`，并在 summary 中计数。

### 3.4 Arm Output Semantics

Arm 是目标语义路口处一组进入 / 退出道路角色与其 Segment corridor 证据，不等同于 P01 FinalArm，也不等同于全局 Segment。

每条 Arm 至少需要表达：

- `arm_id`
- `swsd_junction_id`
- `member_node_ids`
- `seed_road_ids`
- `segment_ids`
- `member_road_ids`
- `terminal_junction_id`
- `terminal_source`：`segment_pair_node / segment_split / local_topology_fallback / unresolved`
- `direction_role`：`inbound / outbound / bidirectional / unknown`
- `build_status`
- `risk_flags`
- `geometry`

### 3.5 ArmMovement Output Semantics

ArmMovement 是同一 `kind_2 = 4` 语义路口内从进入 Arm 到退出 Arm 的客观候选动作，不表示允许通行，也不表示禁行。

每条 Movement 至少需要表达：

- `movement_id`
- `swsd_junction_id`
- `from_arm_id`
- `to_arm_id`
- `movement_type`：`straight / left / right / uturn / unknown`
- `movement_status`：初始为 `objective_candidate`
- `restriction_status`：Step1 固定为 `not_evaluated`
- `evidence_status`
- `from_seed_road_ids`
- `to_seed_road_ids`
- `risk_flags`
- `geometry`

`movement_type` 可参考 P01 的 same-arm、corridor 连续性、trunk / Segment 证据和相对侧向关系。不得使用 RoadNextRoad `turnType / turntype` 或 T08 restriction 字段作为 Step1 movement type 判定入口。

## 4. Expected Step1 Outputs

建议输出目录：

```text
<out_root>/<run_id>/step1_swsd_arm_movement/
```

建议输出：

- `t09_swsd_kind2_4_junctions.gpkg/csv/json`
- `t09_swsd_arms.gpkg/csv/json`
- `t09_swsd_arm_movements.gpkg/csv/json`
- `t09_swsd_arm_build_audit.gpkg/csv/json`
- `t09_step1_summary.json`

`summary` 必须记录：

- 输入路径、CRS、图层名、字段解析。
- `kind_2 = 4` 目标路口数量。
- 成功构建 Arm 的路口数量。
- 成功构建 Movement 的路口数量。
- Segment 命中 / 缺失 / 需人工复核计数。
- Movement type 计数。
- 拒绝原因与风险标记计数。
- 性能计数与耗时。

## 5. Architecture View

若后续授权进入实现，T09 应作为独立模块落在：

```text
modules/t09_traffic_restriction_recovery/
src/rcsd_topo_poc/modules/t09_traffic_restriction_recovery/
tests/modules/t09_traffic_restriction_recovery/
```

本草案不创建上述目录，不修改项目级源事实，不新增入口。

未来实现应保持 T09 为实现 owner：

- 可以参考 P01 的 Arm / Movement 术语、审计字段和 movement type 思路。
- 可以复用稳定共享工具或轻量模型，前提是不改变 P01 契约。
- 不应把 P01 FinalArm 或 P01-Final RoadNextRoad 生成结果当作 T09 Step1 的必需输入。
- 不应修改 T01 Segment、T08 Tool7 或 P01 的对外契约。

## 6. Development View

未来实现建议拆分为：

- SWSD node / road / segment reader。
- semantic junction grouping。
- Segment index builder。
- target `kind_2 = 4` selector。
- segment-aware arm builder。
- movement candidate builder。
- movement type classifier。
- audit / summary writer。

第一版 Step1 不应新增 repo 官方 CLI、`Makefile` 目标、`tools/` 常驻命令、模块 `run.py` 或模块 `__main__.py`。是否新增内网 wrapper 脚本应在实现任务书中单独授权，并同步入口登记。

## 7. Testing View

最小测试应使用 synthetic GPKG 数据，不依赖内网路径：

- 单节点 `kind_2 = 4` 路口可构建 4 个 Arm 与对应 Movement。
- 多节点 `mainnodeid` 语义路口只按代表语义路口处理一次。
- 非 `kind_2 = 4` 路口被跳过。
- seed road 使用 `direction` 判断进入 / 退出能力。
- Segment `pair_nodes` 命中时，Arm 使用 Segment corridor 而非全图 trace。
- Segment `junc_nodes` 命中时必须执行内部切分，并输出 split audit。
- Segment `junc_nodes` 命中但输入拓扑不足以切分时，输出明确失败原因。
- Segment 缺失时，fallback 有显式风险标记。
- Movement 输出不把缺失 restriction 或缺失 RoadNextRoad 解释为禁行。
- Summary 记录字段解析、CRS、计数与性能字段。

## 8. QA View

T09 属于 GIS / 拓扑 / 空间数据任务，后续 closeout 必须覆盖：

- **CRS 与坐标变换正确性**：输入 CRS、目标 CRS、输出 CRS 元数据必须进入 summary，不允许 silent fix。
- **拓扑一致性**：Arm 构建必须能追溯到 SWSD Road endpoint、semantic junction group 与 Segment membership，不允许静默修补断连。
- **几何语义可解释性**：movement type 来自 Arm / Segment / corridor 证据，不来自局部样本字段猜测。
- **审计可追溯性**：每个 Arm / Movement 能追溯输入 junction、road、segment 与 fallback reason。
- **性能可验证性**：summary 必须记录输入规模、目标路口规模、索引规模、输出规模与耗时。

## 9. Non-Goals For This Draft

- 不登记 `t09_traffic_restriction_recovery` 为 Active 模块。
- 不创建模块目录、源码、测试或执行脚本。
- 不修改 `SPEC.md`、`docs/PROJECT_BRIEF.md`、`docs/doc-governance/*`、`docs/architecture/*` 或模块契约。
- 不恢复 F-RCSD / RCSD 交通限制成果。
- 不输出 F-RCSD RoadNextRoad。
- 不输出最终 restriction 表。
- 不读取 SWSD restriction 并判定禁行。
- 不从 RoadNextRoad 缺失、restriction 缺失或局部样本中反推通行能力。
- 不扩展 P01 当前边界，不实现 P01-A3、P01-B 或 P01 禁行迁移。

## 10. Confirmed Decisions

- T09 正式模块名固定为 `t09_traffic_restriction_recovery`。
- Step1 必须支持目标路口作为 Segment `junc_nodes` 时的内部切分。
- 当前优先目标是建立 SWSD Arm / ArmMovement。
- Step1 输出采用 GPKG + CSV + JSON 三形态。
- 当前不需要定义 F-RCSD RoadNextRoad 输出。
- 当前不需要定义最终 restriction 表输出。

## 11. Open Questions Before Implementation

- SWSD C 表 `CondType=1` 在 T09 后续阶段是否权威表示禁行 restriction；当前只沿用 T08 Tool7 的显性化事实，不新增字段语义。
- `movement_type` 的外部编码是否需要对齐 RCSD 官方 turn type 规范；当前不得沿用 P01 内部 `0/1/2/3/4` 审计编码作为权威规范。
