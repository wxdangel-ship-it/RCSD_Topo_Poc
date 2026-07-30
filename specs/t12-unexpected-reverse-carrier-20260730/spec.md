# T12 单向 SWSD 对应 F-RCSD 非预期反向载体检出

**Feature Branch**: `codex/t12-unexpected-reverse-precision`
**Created**: 2026-07-30
**Status**: Approved
**Input**: 用户要求“保准优先”，在 T12 中增加“SWSD 为单向 Segment，但 RCSD/F-RCSD 存在双向可通行载体”的错误类型，并确认跨模块影响。

## 1. 业务目标

T12 在不修改上游生产结果的前提下，增加对以下缺陷的只读质检：

- SWSD Segment 仅要求一个方向；
- 既有 T12 已确认 SWSD 要求方向在 F-RCSD 中存在等价载体；
- F-RCSD 在相反方向仍存在局部、方向合法且几何等价的实际 Road 载体；
- SWSD 全图中不存在几何等价的反向替代载体。

正式错误类型为 `unexpected_reverse_carrier`。

本变更不把“SWSD 自身可绕行形成反向替代路径”误判为 F-RCSD 多余方向，也不修改任何 T01–T11 产物。

## 2. 五类职责视角

### 2.1 产品

- 用户可在 T12 候选、最终问题、排除项、摘要和 QGIS 证据中区分：
  - 缺少要求方向载体；
  - 非预期反向载体。
- 优先保证最终 `confirmed` 问题的准确率，不以扩大自动确认数量为目标。
- T03/T03 等弱锚点样例可以稳定进入候选审计，但不得自动确认为正式问题。

### 2.2 架构

- 仅扩展 T12 的只读 QA 语义和输出 schema。
- T10 继续把 T12 当作不透明阶段调用并记录产物；不增加 T10 业务判断。
- 不改变 T01、T03、T04、T05、T06、T07、T09、T10、T11 的接口或实现。
- 继续保持 `silent_fix=false`。

### 2.3 研发

- 生产逻辑不得硬编码 Case、Segment 或 Road ID。
- 只对“SWSD 要求方向已经等价”的单向 Segment 检查反向，避免同一 Segment 同时产生两类候选并破坏候选 ID 契约。
- 反向 F-RCSD 载体必须由原始 Road 方向图、反向门户和实际 Road ID 证明。
- SWSD 反向替代载体采用保守排除策略：只要满足既有长度与走廊阈值，即不自动报错。

### 2.4 测试

- 单元测试覆盖：
  - 单向 SWSD + F-RCSD 双向 + 无 SWSD 反向替代路径；
  - 存在等价 SWSD 反向替代路径的负例；
  - T03/T03 弱锚点只能排除、不可自动确认；
  - 原有两类问题行为不回归；
  - 输出字段、图层与摘要兼容。
- 真实 Case 覆盖至少：
  - `26219553_1026960`：高置信样例；
  - `624023705_39546468`：候选可复现但不得自动确认；
  - `1013614_1019738`：存在等价 SWSD 反向替代载体，应排除。

### 2.5 QA

- 同一输入、参数和环境重复运行两次，候选与最终问题内容哈希一致。
- 明确验证 CRS、拓扑不修复、几何语义、审计追溯和性能。
- 自动确认必须满足双 T07 标准面、唯一关联面、局部原始反向载体和无等价 SWSD 反向载体。

## 3. 精度优先规则

### 3.1 候选成立

同时满足以下条件时，形成 `candidate_kind=unexpected_reverse_carrier`：

1. Segment 的 SWSD 要求方向数为 1；
2. SWSD 要求方向在 F-RCSD 中已满足既有等价载体规则；
3. 相反方向在局部原始 F-RCSD 方向图中存在非空实际 Road 载体；
4. 该反向载体通过既有长度比、附加长度和走廊偏离阈值。

短 Segment 的 source/target portal 先按距两端 SWSD portal 的 Voronoi 侧分离，禁止同一 raw node 同时代表两端。双 T07 场景允许把与 anchor base/group 同 canonical group、位于 `portal_radius_m` 内且落在正确 Voronoi 侧的实际 raw endpoint 加入门户集合；该扩展只选择路径端点，不创建 graph edge，也不跨越路径内部断点。

### 3.2 自动排除

满足任一条件即不进入正式问题：

- SWSD 全图中存在通过同一几何阈值的反向替代载体；
- 锚点不是双 T07 标准面，或任一 T07 锚点不能唯一关联到一个标准面；
- F-RCSD 反向载体只在语义合并图成立，原始 Road 方向图不成立；
- 几何或输入证据不足。

### 3.3 自动确认

仅当候选成立、SWSD 无等价反向替代载体、且两端均为可唯一关联标准面的 T07 锚点时，自动确认为：

- `issue_type=unexpected_reverse_carrier`
- `decision_rule=unexpected_reverse_raw_carrier_dual_t07`

DriveZone 仅作为审计证据，不参与该错误类型的自动确认。

## 4. 输出与兼容性

- `t12_frcsd_quality_candidates.csv/gpkg` 增加候选种类与反向载体审计字段。
- `t12_frcsd_quality_issues.csv/gpkg` 可出现 `unexpected_reverse_carrier`。
- `t12_frcsd_quality_exclusions.csv` 增加反向等价与证据不足的排除规则。
- `t12_frcsd_quality_evidence.gpkg` 增加 SWSD 反向替代载体证据；F-RCSD 反向载体沿用载体路径图层并以 `path_kind` 区分。
- 既有字段不删除、不改名；本次为 additive schema bump。

## 5. 范围

### In Scope

- T12 模块实现、测试、模块源事实、项目级 T12 源事实；
- T12/T10 不变性回归；
- 真实 Case 的可重复性和 QGIS 证据验证。

### Out of Scope

- 修改上游 Segment、Road、Node、Intersection 或匹配关系；
- 修改 T10 编排、CLI、官方入口或其他模块接口；
- 使用 DriveZone 推断方向；
- 对弱锚点样例进行自动确认；
- silent fix。

## 6. 验收标准

1. `26219553_1026960` 稳定进入正式问题，类型为 `unexpected_reverse_carrier`。
2. `624023705_39546468` 稳定进入候选审计，但在当前“保准优先”策略下不得自动确认。
3. `1013614_1019738` 因等价 SWSD 反向替代载体稳定排除；`61704236_1049438` 在当前 Case manifest 中位于 crop-edge，沿用既有规则在候选形成前排除。
4. 原有 `directed_carrier_missing` 与 `required_local_connectivity_missing` 测试通过。
5. 不改造 T01–T11；T10 原有调用和清单测试通过。
6. 重复运行产物稳定，GIS 五项检查均有机器可定位证据。
