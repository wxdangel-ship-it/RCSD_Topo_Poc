# Feature Specification：T12 direction-strict portal

**Feature Branch**：`codex/t12-directional-portal-fix-20260727`

**Created**：2026-07-27

**Status**：In implementation

## 1. 目标

修复 T12 在 FRCSD carrier 审计中未把 portal 角色与 Road `direction` 严格绑定的问题。每个 SWSD 必需方向必须分别从具有真实有向出边的 source portal 跟踪到具有真实有向入边的 target portal；无向图只允许解释“物理走廊存在但方向不成立”，不得参与等价 carrier、portal 资格或自动排除。

本轮必须使用通用规则覆盖正反向平行 Road、`mainNodeId/subNodeId` alias 和 `T03|T07` 混合锚点场景，禁止针对 `1885084_1885086`、`5885111744069971` 或其它对象 ID 特判。

## 2. 用户场景与验收

### US1：方向严格的 portal（P1）

1. `pair0_to_pair1` 与 `pair1_to_pair0` 必须独立构造 source/target portal。
2. source raw portal 必须在当前有向 local graph 中至少具有一条 outgoing Road；target raw portal必须至少具有一条 incoming Road。
3. `direction=0/1` 双向、`direction=2` `snodeId→enodeId`、`direction=3` `enodeId→snodeId`，不得以无向邻接替代。

### US2：方向严格的 carrier（P1）

1. raw、portal-constrained semantic 与 Road-surface carrier 都必须由方向正确的物理 Road 组成。
2. 无向路径只能输出诊断证据并辅助区分 `directed_carrier_missing`，不能成为等价 carrier。
3. 当同一空间走廊存在正反向平行 Road 时，必须按当前必需方向选择可通的 Road 链，不能用反向 Road 代替。

### US3：证据完整与误报防护（P1）

1. 输出必须记录每方向 source/target portal 的方向角色及资格。
2. 如果正确方向 Road 未进入 local graph、未进入 portal、canonical endpoint 断开或 direction 不允许，必须能够区分原因，不得只输出笼统 `semantic_path_missing`。
3. 只有方向搜索覆盖完整且仍无等价 carrier 时，才允许自动 confirmed。

### US4：基线安全（P1）

1. `1026960` 必须维持 35 candidates、10 confirmed、25 excluded、0 manual，以及冻结的 `candidate_id + issue_type` 集合；如有变化必须回到原始数据审计。
2. T10/T12 正式入口、T06/T09/T11 handoff 和 FRCSD 输入均不改变。
3. 不修改输入、不构造虚拟 Road、不 snap、不 silent fix。

## 3. 功能需求

- **FR-001**：portal 资格必须由当前方向的 `outgoing_nodes/incoming_nodes` 决定，不得统一使用 undirected node 集合。
- **FR-002**：有向 carrier 路径必须逐 Road 遵循正式 `direction` 语义。
- **FR-003**：无向路径只保留在诊断层；正式等价 basis 只能来自 raw directed、portal-constrained semantic directed 或 Road-surface directed。
- **FR-004**：对 portal 覆盖不足导致的 directed path missing，输出可审计根因。
- **FR-005**：不得按 Case、Segment、Road 或 Node ID 建分支、白名单或阈值。
- **FR-006**：实现和验证必须显式覆盖 CRS、拓扑一致性、几何语义、审计追溯和性能。
- **FR-007**：不新增 CLI 参数、长期入口或依赖。

## 4. 非目标

- 不修改 FRCSD Road 的 `direction`、endpoint、Node alias 或几何。
- 不修改 T05 relation、T06 替换逻辑或 T09/T11。
- 不把空间接近单独提升为锚定真值。
- 不因单个内网样本反推新的上游字段语义。
