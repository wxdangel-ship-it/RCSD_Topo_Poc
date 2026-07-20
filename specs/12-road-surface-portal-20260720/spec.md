# Feature Specification：T12 Road-surface portal

**Feature Branch**：`codex/t12-road-surface-portal-20260720`

**Created**：2026-07-20

**Status**：In implementation

## 1. 目标

在 1V1 FRCSD 两端已由 T07 正确锚定到唯一 `RCSDIntersection` 标准路口面的前提下，将 Road 与标准路口面的相交关系、以及锚点 Road 一跳可证明的 surface frontier，纳入 SWSD 必需方向的正式 carrier 排除证据。距离门禁仅保留为人工审计风险，不再单独拒绝该证据；不得修改输入或生成虚拟 Road。

本轮必须用通用规则排除 `1623512_508276240`、`1921739_1921764`、`500636195_505415445` 的已知误判，同时保持 `1026960` 已确认的 10 个质量 Segment 及 issue type 集合不变。若集合变化，必须回到原始数据审计并给出充分业务理由，禁止直接刷新基线。

## 2. 用户场景与验收

### US1：正确识别 Road-surface carrier（P1）

1. 当 T07 两端锚点均可唯一关联标准路口面时，实际有向 Road 链的首末 Road 可通过 Road 几何与对应标准面的空间关系建立 surface portal。
2. 目标端 Road 未直接接触标准面时，若它到达的 raw/canonical frontier 能由目标锚点组的 anchor→frontier 一跳物理 Road 明确连接，且 support Road 接触标准面（允许 `1m` 拓扑容差），可作为 surface access 证据；整条 carrier 至少一端必须有实际 Road-surface contact。
3. 该证据只能排除 raw/node-portal 假断裂，不能单独确认质量问题。

### US2：距离只作审计（P1）

1. 在 T07 1V1 锚点正确且唯一时，endpoint-to-surface、SWSD portal、内部 alias gap 和走廊距离必须输出，但不能单独拒绝 Road-surface carrier。
2. 方向、物理 Road、锚点唯一性和路径长度等价仍是强门禁。
3. 非 T07 锚点继续沿用现有 portal-constrained semantic 规则，不扩大本轮口径。

### US3：基线安全（P1）

1. `1026960` 无 review 回归必须保持 candidate=35、confirmed=10、excluded=25、manual=0。
2. confirmed 的 `candidate_id + issue_type` 集合必须与冻结基线一致。
3. 生产代码与正式规则禁止出现任何 Case、Segment、Road 或 Node ID 特判。

## 3. 功能需求

- **FR-001**：复用现有 T10/T12 正式入口，不新增 CLI 参数或长期入口。
- **FR-002**：新增 T07-only Road-surface portal carrier；仅当两端 T07 锚点和唯一标准面均受信时启用。
- **FR-003**：carrier 必须由方向正确的原始 FRCSD 物理 Road 构成；canonical main/subNode 仅用于表达同一语义节点，不得生成无 Road 的零成本通路。
- **FR-004**：source/target surface access 必须分别记录 `road_surface_intersection` 或 `anchor_one_hop_frontier` 及其 Road/Node 证据；一跳 support Road 必须是 anchor→frontier 有向边、与标准面相交或满足 `1m` 拓扑容差，且整条 carrier 至少一端实际 Road-surface contact。
- **FR-005**：路径长度比例与附加长度继续作为等价强门禁；距离类指标仅输出 `audit_only` 状态，不作为 T07 Road-surface carrier 拒绝理由。
- **FR-006**：Road-surface carrier 通过时，以独立 `equivalence_basis` 和 decision rule 排除 candidate；不能单独把 candidate 提升为 confirmed。
- **FR-007**：输出必须包含方向、Road 序列、两端标准面、两端 access kind、距离指标、路径指标与拒绝原因。
- **FR-008**：不得 snap、repair、补点、补路、截断或改写输入几何；surface contact/stop 仅作为审计语义。
- **FR-009**：实现与验证必须覆盖 CRS、拓扑一致性、几何语义、审计追溯和性能。

## 4. 非目标

- 不修改 T06 代码和替换规则。
- 不改变 T07 锚定算法或 T05/T07 输入事实。
- 不把任意临近 Road 或任意距离内 Node 提升为正式 portal。
- 不修复 FRCSD 数据，不改变 T10 阶段顺序和 T09/T11 handoff。
