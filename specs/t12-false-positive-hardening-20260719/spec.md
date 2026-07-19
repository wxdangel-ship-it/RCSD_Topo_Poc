# Feature Specification：T12 误判审计与高置信规则收敛

**Feature Branch**：`codex/t12-false-positive-hardening`

**Created**：2026-07-19

**Status**：In analysis

## 1. 目标

对 `E:\TestData\POC_QA\T10_Segment` 下 11 个疑似误判 Segment 进行原始数据端到端审计，区分真实 1V1 FRCSD 质量问题、T12 误判和因裁剪/数据损坏无法判断三类结果；在准确率优先前提下修复可泛化误判根因，并保持 `1026960` 已确认的 10 个质量问题业务基线。

## 2. 用户场景与验收

### US1：逐 Segment 获得可解释结论（P1）

1. 每个可重建 Segment 必须检查 SWSD 必需方向、两端锚点/portal、FRCSD raw local/full directed/undirected carrier、路径长度与走廊偏离。
2. 结论只能是 `confirmed_quality_issue`、`false_positive` 或 `not_assessable`。
3. `not_assessable` 必须列出缺失文件、裁剪边界或拓扑重建失败证据，不能进入正式问题或误判统计。

### US2：修复通用误判原因（P1）

1. 修复必须基于通用拓扑、锚点或几何证据，禁止使用 Segment/Road/Node/Case ID 特判。
2. “局部路径未通过阈值”“局部搜索未命中”和“全图 raw carrier 不存在”必须在审计与 decision 中可区分。
3. 证据不足的 candidate 必须排除或明确阻断，不得自动确认。

### US3：保持 1026960 业务基线（P1）

1. 修复后 `1026960` 无 review 仍须输出 candidate=35、confirmed=10、excluded=25、manual=0，并保持 confirmed ID/issue type 集合不变。
2. 若任一基线对象变化，必须从 `E:\TestData\POC_QA\T10\1026960` 原始数据重新审计，不能直接改 fixture 迎合实现。

## 3. 功能需求

- **FR-001**：复用现有 T10/T12 正式入口和字段语义，不新增长期入口。
- **FR-002**：11 个 Segment 的重建输入必须来自各自证据包，不混入其它 Segment 的业务结论。
- **FR-003**：正式 verdict 以 FRCSD raw Road endpoint graph 为主；raw failure 可被受信 portal-constrained semantic carrier 排除，但该 carrier 必须包含物理 Road，满足原方向/长度/走廊阈值，并通过 T07 标准面或非 T07 同组邻近端点及内部 alias gap 门禁。semantic carrier 不能单独确认问题。
- **FR-004**：raw local/full 与 directed/undirected 四层路径状态必须分别输出，并记录拒绝原因。
- **FR-005**：raw carrier 不通过时，必须先区分 semantic path 缺失、路径几何不等价、端点不受信和内部 alias gap 超限；不得仅凭 `raw_carrier_missing_trusted_anchor` 自动确认“carrier 缺失”。
- **FR-006**：semantic carrier 的两端信用必须分别可追溯；T07 alias 必须位于对应唯一标准面，非 T07 alias 必须为同 canonical group 且在 portal radius 内，不能用“至少一端可信”掩盖另一端 portal 不确定性。
- **FR-007**：不得修改输入、补路、snap、repair 或执行 silent fix。
- **FR-008**：生产实现不得出现 11 个 SegmentID、`1026960` Case ID 或冻结真值对象 ID。
- **FR-009**：所有结论和修复验证必须覆盖 CRS、拓扑、几何语义、审计追溯与性能。

## 4. 非目标

- 不修复 FRCSD 数据本身。
- 不改变 T06 替换规则、T10 编排顺序或 T09/T11 handoff。
- 不把目视结果单独作为正式真值。
- 不用局部证据包结果宣称已完成内网全量城市验证。
