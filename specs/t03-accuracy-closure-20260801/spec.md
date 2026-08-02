# Feature Specification：T03 全量 Case 准确性闭环

**Feature Branch**：`codex/t03-accuracy-closure-20260801`
**Created**：2026-08-01
**Status**：Reopened for Scheme A implementation

## 1. 业务目标

面向 `E:\TestData\POC_QA\T03_Error` 的 54 个 Case，系统修复 T03 的假拒绝与假接受，
同时保护 `E:\TestData\POC_Data\T03`、`E:\TestData\POC_Data\T03_Error` 已经人工确认和正式
登记的成功/失败基线。

本轮追求的是准确性闭环，不是 accepted 数量最大化：

1. 可正确锚定并生成合规路口面的 Case 不得继续被算法误拒绝；
2. 只覆盖部分 RCSD 路口结构、方向拓扑不等价、ownership 不成立或场景复杂度无法形成唯一可解释
   锚定的 Case 不得被几何收敛误判为成功；
3. 未经人工确认的 Case 只按原始数据和通用规则分类，不自动登记为成功或失败真值；
4. 不使用 Case/Road/Node ID 特判，不修改原始数据，不 silent fix。

## 2. 冻结数据与当前基线

指纹覆盖每个 Case 的 `manifest.json`、`size_report.json`、`drivezone.gpkg`、`nodes.gpkg`、
`roads.gpkg`、`rcsdroad.gpkg`、`rcsdnode.gpkg`，按相对路径、文件大小和单文件 SHA-256 聚合：

| 数据根 | Case 数 | 聚合 SHA-256 |
|---|---:|---|
| `E:\TestData\POC_QA\T03_Error` | 54 | `9bfea7042a5b208522b137099bc1ed35d6da8a03393819074c58e8f3d71be765` |
| `E:\TestData\POC_Data\T03` | 78 | `82fc615de586de982832589edf29d18ca3302b93df0086518aa5ba0182abad60` |
| `E:\TestData\POC_Data\T03_Error` | 258 | `d2ea4f174dbe390e52528c28a037c1576a7472a3128df0a14f849a16946a1d6b` |

当前主干 `7c8b832` 的完整重放结果：

| 数据集 | 有效执行 | Step7 accepted | Step7 rejected | runtime failed |
|---|---:|---:|---:|---:|
| QA T03_Error | 54 | 17 | 37 | 0 |
| legacy T03 | 75 | 71 | 4 | 0 |
| legacy T03_Error | 258 | 186 | 72 | 0 |

`legacy T03` 的 78 个目录中，默认正式批次仍按既有契约排除 3 个 Case；不得把该差异解释为运行失败。

## 3. 真值保护层

### 3.1 正式历史基线

`tests/modules/t03_virtual_junction_anchor/data/t03_anchor_anchorf_visual_baseline_20260429.json`
继续作为已批准的历史保护面。同 ID 在不同数据根或不同输入指纹下必须视为不同快照，禁止按 ID
跨快照复制结论。

后续用户人工审计覆盖历史基线时，以较新的明确裁决为准。例如 legacy `991380` 已由 rejected
改为“应可正确锚定”，本轮必须按 accepted 保护。

### 3.2 本轮人工确认的成功保护

- QA 新快照：`706399`、`709492`、`724917`。
- legacy 明确成功：`698418`、`500950794`、`1881693`、`623073782`、`605652585`、
  `603642523`、`600689129`、`600114422`、`523980540`、`505671093`、`503100157`、
  `75191911`、`74420043`、`74386034`、`62650455`、`58319593`、`54265802`、`47408750`、
  `12792352`、`11836314`、`1633175`、`758888`、`762905`、`765003`、`769081`、`989550`、
  `991380`、`61529208`、`787617`、`899127`、`984901`、`1013539`、`1219975`。

### 3.3 QA 当前快照的审计目标

`E:\TestData\POC_QA\T03_Error` 是独立数据版本，不能继承同 CaseID 在历史目录中的结论。
当前审计目标按输入聚合指纹登记，并区分用户裁决与数据审计目标：

- 用户明确认可失败：`823840`、`950770`、`991243`、`994202`、`995764`、`1071119`、
  `522806716`；
- 通用规则应修复为 accepted 的数据审计目标：`768683`、`830724`、`952797`、`992932`、
  `1049277`、`520394575`、`622700016`；
- 当前保守 rejected、但不得直接升级为 T12 质量真值：`787617`、`867264`、`1056150`、
  `522008569`。

上述审计目标只用于验证通用规则，不授权生产代码按 CaseID 分支。用户最终目视复核前，
`data_audit_target` 不得伪装成 `user_confirmed`。

### 3.4 历史数据集人工确认的失败保护

- 历史快照现实差异或精度差异高置信：`520394575`、`622700016`。
- 历史快照只覆盖部分必需路口拓扑或 merge-only terminal collapse：`522008569`、`522806716`。
- 复杂场景无法形成唯一可解释锚定：`507831701`、`74421922`。
- `12777955` 当前仍有争议，只允许保守拒绝/待审，不登记为本轮硬失败真值。

上述 ID 只允许存在于测试与审计工件，生产代码不得引用。

### 3.5 QA 当前快照的 T12 真值

对修复后仍被 T03 rejected 的 11 个 QA Case，T12 以当前原始 SWSD/FRCSD Road、Node、Direction
重新构造必需 movement，不继承历史同 CaseID 结论：

- 自动 confirmed：`522806716`。其 movement `528030913 -> 613908333` 的两端 boundary Road 已按
  ownership、geometry、heading 锚定，但输出臂的 raw FRCSD Road 在严格 Direction 下没有 outgoing
  角色；
- carrier 已等价而排除：`787617`、`522008569`；
- 高置信跨层/冻结合法空间诱发而排除：`823840`、`1071119`；
- 原始输入几何无效而阻断：`950770`、`994202`；
- boundary carrier 不能在当前路口高置信对应而证据不足：`867264`、`991243`、`995764`；
- T03 候选输入不足：`1056150`。

该集合只作为指纹 `9bfea7042a5b208522b137099bc1ed35d6da8a03393819074c58e8f3d71be765`
的 snapshot-scoped 回归台账；生产实现不得读取 CaseID。confirmed 数量不是跨快照固定指标。

## 4. 五类职责视角

### 4.1 产品

- T03 的几何 surface 可发布与 RCSD 锚定关系成立必须分层解释。
- 对本轮“成功/失败”验收，必须同时检查 Step7 surface、association/ownership、Direction raw topology
  和 T05 handoff；不能只看 Polygon 是否生成。
- 每个仍失败 Case 必须有原始数据可复核的明确理由。

### 4.2 架构

- 保持 `Step1 -> Step7` 正式链路和既有入口不变。
- Step3 仍冻结合法空间；用户已确认的 T03/T07 spatial access 门禁统一为 `2m`，不得把该距离
  扩展为任意邻近接边。
- Step4 必须分离 association、junction ownership 与 support-only 证据。
- Step6 使用 Road-surface 边缘、业务终端连通分组和受约束平滑构面；MultiPolygon 按业务连通性
  判定，不强制单 Polygon。
- Step7 在发布前增加 Direction 严格的 raw Road/Node topology 反证；几何收敛不得覆盖锚定不完整。
- T12 保留独立 Junction 质量审计，但 QA 当前快照不预设正样本数量。T03 单一状态、reason、
  unmatched component 或 connected core 只能形成候选；T12 必须用当前原始 FRCSD Road/Node、
  Direction、SWSD 必需通行和等价 carrier 排除证据独立确认。

### 4.3 研发

- 优先复用已验证的 canonical mainNode lookup、Class B ownership、Road-surface portal、业务连通性
  与 surface regularization 通用实现，但必须在当前主干和三套数据上重新验证。
- 新规则只能使用既有正式字段、几何、Road endpoint、Direction、mainNode group、合法空间和标准审计
  证据；不得反推新字段语义。
- 不新增正式入口，不改变 CLI/runner 签名，不增加依赖。

### 4.4 测试

- 冻结数据指纹、当前结果和人工真值注册表。
- 先增加 synthetic 单元测试，再增加真实 Case 回归。
- 三套数据必须全量重放；所有 `success_to_failure`、`failure_to_success` 和 runtime change 逐 Case
  审计，不自动刷新期望值。
- T03/T05/T06/T12 受影响测试必须全部通过。

### 4.5 QA

- CRS：所有距离和面积在显式 `EPSG:3857` 中计算，输入/输出 CRS 写入审计。
- 拓扑：Road endpoint 与 Direction 严格验证，不 snap、不补点、不零长度 canonical 折叠。
- 几何：验证 legal/direction/foreign/must-cover/required carrier、业务连通性和 Road-surface 覆盖。
- 追溯：记录 commit、输入指纹、参数、运行环境、逐 Case 决策和前后 diff。
- 性能：记录 Step3-Step7 耗时、吞吐和峰值内存；禁止新增无索引全图扫描。

## 5. 功能需求

- **FR-001**：T03 MUST 将 spatial access 容差统一为 `2m`，且只用于已定义的 Road/DriveZone
  边界接触门禁。
- **FR-002**：T03 MUST 对 canonical mainNode/alias group 做确定性 lookup，canonical 记录优先，
  冲突或缺失进入审计。
- **FR-003**：Class B support carrier MUST 证明当前 junction ownership；邻近路口、远端路口和
  窗口穿越 Road 不得仅凭相交或接近进入 support。
- **FR-004**：Step6 MUST 以业务终端在原始合法 Road surface 中的连通分组为参考生成结果；不得
  以 MultiPolygon 类型本身接受或拒绝。
- **FR-005**：Step6 形态指标只能作为风险审计；合法空间、方向边界、foreign、must-cover、required
  carrier 和业务连通性仍是硬门禁。
- **FR-006**：Step7 MUST 在 support-only 或 topology-risk 场景执行 Direction 严格 raw topology
  完整性检查；只形成 merge-only、共享 degree-1 terminal collapse 或 unmatched support component
  的场景不得 accepted。
- **FR-007**：输入无效几何不得被 silent repair。若既有流程发生合法化，必须输出原始有效性、
  操作、面积/部件变化和最终是否参与判定；无法证明语义保持时显式阻断。
- **FR-008**：不得在生产代码中出现本轮 Case/Road/Node ID。
- **FR-009**：不得修改输入 GPKG，不得改变 T03/T05/T12 官方入口或 T06 业务逻辑。
- **FR-010**：T12 MUST 撤销 QA 当前快照固定的“4 正 16 负”注册集。任何自动 confirmed
  Junction 必须证明具体 SWSD 必需方向/拓扑在当前原始 FRCSD 中缺失或冲突，并排除完整 raw
  carrier、canonical Road-surface portal 等价、跨层策略失败和输入阻断；不得按 T03 reason 直通。

## 6. 成功标准

- **SC-001**：所有人工确认成功快照均 accepted，人工确认失败快照均 rejected；误判数为 0。
- **SC-002**：历史正式 65 Case 基线除明确后续裁决外无回退；所有差异有逐 Case审计。
- **SC-003**：54 个 QA Case 全部有 terminal result；未确认 Case 的状态变化均有通用规则证据。
- **SC-004**：T03/T05/T06/T12 测试通过；T12 QA 当前快照对已证明 carrier 完整、算法误拒绝、
  跨层策略失败或输入阻断的 Case 保持 `FP=0`，最终 confirmed 数量由证据决定而非预设。
- **SC-005**：accepted 几何非空、有效、CRS 明确，并通过 topology/geometry/QGIS 机器门禁。
- **SC-006**：无 silent fix、无生产 ID 特判、无输入修改、无不可解释性能退化。

## 7. 范围

### In Scope

- T03 Step3 spatial access、Step4 ownership、Step6 构面/连通性、Step7 锚定完整性；
- 必要的 T05 canonical lookup 修正，但不改变 Phase 1/Phase 2 接口；
- T03/T05/T06/T12 测试、T12 QA 当前快照 Junction 真值重建、模块源事实和本 SpecKit 验证工件。

### Out of Scope

- 修改原始 SWSD/RCSD/FRCSD/DriveZone；
- 修改 T06 替换策略或 T09/T11；
- 新增正式入口、依赖或对象 ID 白名单；
- 把未确认 Case 自动登记为真值。
