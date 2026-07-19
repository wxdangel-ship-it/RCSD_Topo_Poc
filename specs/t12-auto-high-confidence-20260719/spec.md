# Feature Specification：T12 自动高置信质量确认

**Feature Branch**：`codex/t12-auto-high-confidence`

**Created**：2026-07-19

**Status**：Approved for implementation

**Authorization**：用户授权“方案 A”，允许更新正式源事实并实施 T12 自动高置信确认。

## 1. 目标

T12 必须在不依赖人工复核文件的情况下，从 SWSD Segment、正式路口锚定证据和原始 1V1 FRCSD 拓扑中直接发布高置信质量问题。最终问题以准确率为优先，不使用高/中概率分层，不包含 Case、Segment、Road 或 Node 对象级生产规则。

## 2. 用户场景与验收

### US1：自动获得最终质量问题（P1）

作为质量工程师，我希望 T12 一次运行即可获得可程序消费、可在 QGIS 查看且有完整证据链的最终 FRCSD 质量问题，不再要求先生成候选、人工填写 review CSV、再恢复运行。

验收：

1. 无 `--review-decisions` 时也必须自动生成 confirmed CSV/GPKG。
2. 自动确认必须由锚点可信度、原始 Road/Node 物理拓扑、方向、局部无向/有向 carrier 和几何走廊共同证明。
3. 等价 carrier 已存在或锚点不足以唯一归因 FRCSD 时，不得进入最终问题。
4. 外部 review CSV 只作为可选 QA 覆盖，不再是正式结果的前置条件。

### US2：避免语义节点归并造成假通路（P1）

作为拓扑质量工程师，我希望 T12 区分“语义路口节点组”和“Road endpoint 的物理通行连接”，避免把 `mainNodeId/subNodeId` 的零成本归并误当作两路口之间已经存在道路 carrier。

验收：

1. base-node/canonical 图可继续用于宽召回候选筛选。
2. 最终判定必须在原始 FRCSD Road endpoint 图上执行，不得用 canonical alias 自动补出 Road 间连接。
3. T07 portal 必须由 T05 显式 group 与对应 `RCSDIntersection` 标准路口面限定；不得接受 50m 内任意邻近路口节点。
4. T03/T04 非标准面锚点可保留基于实际 SWSD 接入侧的空间 portal，但自动确认必须执行锚点可信度门禁。

### US3：保持 T10 和外部复核兼容（P2）

作为流水线维护人员，我希望现有 T10/T12 参数、输出文件名和可选 review 输入继续可用，同时默认运行已经能产出正式结果。

验收：

1. 不新增正式入口，不改变现有 CLI 必选参数。
2. 既有 review CSV 合同继续校验 run/candidate/状态/理由，并可显式覆盖自动决定。
3. T12 保持 audit-only，不修改 FRCSD、SWSD、T05、T06、T09 或 T11 数据。

## 3. 功能需求

- **FR-001**：T12 必须保留 canonical graph 的宽召回候选筛选，不因本轮改变 T06 或 T05 业务规则。
- **FR-002**：T12 必须为正式 carrier 判定构建不折叠 `mainNodeId/subNodeId` 的 raw endpoint graph。
- **FR-003**：T07 endpoint 的 portal 集必须包含 T05 显式 base/grouped raw node，以及对应 `RCSDIntersection` 面内、满足 start 出边或 end 入边角色的 raw FRCSD Node。
- **FR-004**：T07 与 `RCSDIntersection` 必须按 SWSD 语义路口点和标准路口面建立可审计关联；关联缺失或不唯一时不得获得 T07 自动确认信用。
- **FR-005**：非 T07 endpoint 可使用 T05 显式 group 与 SWSD 接入侧 `portal_radius_m` 内的角色相容 raw node。
- **FR-006**：raw local directed carrier 不等价时，若同 portal 策略下 semantic/canonical local directed 也不等价但 semantic/canonical local undirected carrier 等价，则问题类型为 `directed_carrier_missing`；canonical 证据只用于区分问题类型，不改变 raw failure verdict。
- **FR-007**：raw local directed carrier 不等价且不满足 FR-006 的方向缺失证据时，问题类型为 `required_local_connectivity_missing`；多个失败方向中只要存在 FR-006 证据，Segment 级类型优先为 `directed_carrier_missing`。
- **FR-008**：自动确认锚点门禁为：至少一端是具有唯一标准面关联的 T07，或两端均为正式 T03 anchor；其它组合从最终问题中排除并记录 `insufficient_anchor_confidence`。
- **FR-009**：所有 SWSD 必需方向 raw local directed carrier 均等价时，候选必须以 `equivalent_raw_carrier` 排除。
- **FR-010**：无 review 输入时，每个候选必须自动归入 confirmed 或 excluded；不得因为缺少人工决定进入 manual。
- **FR-011**：显式 review 输入可以覆盖自动决定；覆盖来源、理由、时间与原自动规则必须同时可追溯。
- **FR-012**：最终输出不得包含概率等级；生产代码不得包含 `1026960` 或其任何真值对象 ID。
- **FR-013**：不得修改输入、补路、snap、repair、重写方向或做其它 silent fix。
- **FR-014**：manifest/summary/CSV/GPKG 必须记录 decision source/rule、raw topology 路径证据、CRS、几何、endpoint、参数、输入指纹、环境和性能。

## 4. 质量与 QA 要求

- CRS：仅 projected metre CRS 参与距离判定；显式转换并审计。
- 拓扑：canonical candidate graph 与 raw verdict graph 分层，二者差异必须可解释；不 silent fix。
- 几何：路径长度比、附加长度、最大走廊偏离和 Road ID 必须进入证据。
- 审计：候选、自动决定、可选人工覆盖和最终分组计数守恒。
- 性能：全图 canonical/raw graph 各建一次；逐 Segment 仅查询 local roads；记录分阶段耗时。

## 5. 1026960 回归

- 无 review 输入：candidate=35、confirmed=10、excluded=25、manual=0。
- confirmed ID 集必须与冻结真值完全一致；25 个排除项不得进入最终问题。
- 生产实现扫描不得出现 Case ID、10 个 confirmed ID 或 25 个 excluded ID。
- 该用例只验证通用规则，不构成所有城市参数已经充分校准的声明。

## 6. 非目标

- 不自动修复 FRCSD。
- 不改变 T06 的 canonical node、替换或 replacement plan 语义。
- 不把 DriveZone、Source、T06 reject reason 单独作为自动确认规则。
- 不声称已完成内网全量数据验证。
