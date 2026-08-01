# T12 质量分类与 T07 Step2 来源修正

**Feature Branch**: `codex/t12-v10-quality-taxonomy`
**Created**: 2026-08-01
**Status**: Approved
**Input**: 用户批准修复 T07 非所属路口误报，并将 T12 Segment/Junction 正式结果统一为三组七类、可分类型修复的质量错误。

## 1. 业务目标

T12 升级为统一、只读、可审计的 FRCSD 质量问题出口：

1. Segment 继续按 T01 Segment 线几何族（`LineString/MultiLineString`）发布通行质量问题；
2. Junction 继续按 Point 发布 T03 原始 FRCSD 重验结果；
3. T07 Junction 只消费 Step2 最终 `is_anchor=fail1/fail2`，不再消费 Step3 `relation_cardinality_errors`；
4. `fail2 > fail1`，T12 输出集合必须与 T07 Step2 最终代表路口集合精确相等；
5. 正式错误稳定归入三组七类，并提供中文描述、根因、修复责任域与修复建议；
6. 保留一个版本的旧状态与旧类型映射，但新 `result_status` 和新 `issue_type` 是正式口径；
7. 不修改输入、不自动修复、不 silent fix、不按对象 ID 特判。

## 2. 五类职责视角

### 2.1 产品

- 正式错误分组为 `segment_passability`、`junction_topology`、`junction_anchor_relation`。
- 正式错误类型固定为 S01-S03、J01-J04；删除泛化的 `junction_relation_cardinality_mismatch`。
- confirmed 行必须具有中文错误名、中文描述、根因类型、修复责任域和修复建议。
- Segment 与 Junction 不混层，原始根因仍保留在输出字段和 evidence 图层。

### 2.2 架构

- T07 Step2 `nodes.gpkg` 的最终代表路口状态是 J03/J04 真值源。
- `node_error_1.gpkg`、`node_error_2.gpkg`、Step2 summary 和 relation evidence 用于一致性与来源审计。
- T07 Step3 只保留其原有兼容补锚职责，不能再成为 T12 正式错误来源。
- T10 将已有 `t07_run_root` 显式交给 T12；不要求为 T12 运行可选 Step3。
- 旧 `--t07-step3-run-root` 只保留一个版本的定位兼容，禁止读取其 cardinality 文件。

### 2.3 研发

- 新增集中式错误分类定义，Segment/Junction 共用，不在输出模块重复硬编码。
- T07 Step2 输入一次加载，按 final state 与 error evidence 做集合校验。
- 不修改 T03/T07/T05/T06/T09/T11 算法。
- 不新增正式执行入口，只参数化既有 T12/T10 入口。

### 2.4 测试

- 测试 final `fail1/fail2`、`fail2` 优先级、Step2 证据缺失硬阻断和 Step3 行不导入。
- 测试三组七类映射、旧类型兼容、状态守恒、字段完整性和几何分层。
- 冻结 Segment Case `1026960` 的 `63/10/53/0` 与 10 个 confirmed ID。
- 冻结 T03 4 正 16 负；J01=2、J02=2。
- `764857`、`26981804` 在 candidates/confirmed/exclusions 中均为 0。

### 2.5 QA

- CRS 必须显式存在；距离计算仍使用 projected metre CRS。
- manifest 记录 T07 Step2 根、必要工件绝对路径/SHA-256、fail1/fail2 集合和一致性检查。
- QGIS 工程同时加载原始 SWSD、原始 FRCSD/RCSD 与分类后的 Segment/Junction 成果。
- 同输入同参数双跑，去除时间和绝对路径后的业务结果完全一致。
- 内网同机三次中位数记录时间与峰值内存；不把本地小 Case 推导成全量性能结论。

## 3. 正式分类

| code | issue_group | issue_type | 中文名称 |
|---|---|---|---|
| S01 | segment_passability | segment_required_direction_unavailable | 路段必需方向不可通行 |
| S02 | segment_passability | segment_required_connection_missing | 路段必需连接缺失 |
| S03 | segment_passability | segment_unexpected_reverse_passability | 路段存在非预期反向通行 |
| J01 | junction_topology | junction_required_topology_missing | 路口必需拓扑缺失 |
| J02 | junction_topology | junction_unmatched_support_topology | 路口存在未匹配支撑拓扑 |
| J03 | junction_anchor_relation | junction_anchor_one_to_many | 单路口锚定到多个路口面 |
| J04 | junction_anchor_relation | junction_anchor_many_to_one | 多个路口锚定到同一路口面 |

旧 `junction_reality_or_precision_gap` 迁移为 J02；“现实变化/精度误差”只作为后续根因研判，不再作为正式错误类型。

## 4. User Scenarios & Testing

### User Story 1 - 只发布 T07 正式锚定失败 (P1)

质检人员只看到 T07 Step2 明确产生的 `fail1/fail2`，不会再看到 Step3 广义 relation 审计误报。

**Independent Test**: 构造 Step2 final state 与 Step3 cardinality 行不一致的运行根；T12 只发布 final fail 集合。

**Acceptance Scenarios**:

1. Given final `fail1`, When T12 加载 Step2, Then 输出 J03。
2. Given final `fail2` 且 error1 也曾命中, When T12 加载 Step2, Then 只输出 J04。
3. Given 仅存在 Step3 cardinality 行, When T12 运行, Then 该行不进入任何 Junction 结果。
4. Given final state 与 Step2 error evidence/summary 不一致, When T12 预检, Then run 为 blocked。

### User Story 2 - 按稳定类型审计和修复 (P1)

质检人员可以按 S01-S03、J01-J04 聚合问题，并直接路由给对应修复域。

**Independent Test**: 对七类各生成一条 confirmed，校验分类字段和中文字段完整且唯一。

### User Story 3 - 保持旧运行连续性 (P2)

既有 Segment-only 调用不新增必选参数；T10 full 使用已有 T07 Step1/2 运行根即可连续执行 T12。

**Independent Test**: 不传 Junction 来源时生成空 Junction 文件；传 `t07_run_root` 时不执行或依赖 Step3。

## 5. Functional Requirements

- **FR-001**: T12 MUST 只从 T07 Step2 final `is_anchor=fail1/fail2` 构造 J03/J04。
- **FR-002**: T12 MUST 校验 Step2 summary、final nodes 与对应 error GPKG 一致；不一致时 blocked。
- **FR-003**: T12 MUST 实现 `fail2 > fail1`，同一代表路口最多发布一种 T07 issue。
- **FR-004**: T12 MUST NOT 读取 Step3 `relation_cardinality_errors` 作为候选或 confirmed。
- **FR-005**: T12 MUST 为 confirmed 行写入统一分类和修复字段。
- **FR-006**: `result_status` MUST 为 `confirmed/excluded/manual_review`，并与兼容 `review_status` 一致。
- **FR-007**: 新 `issue_type` MUST 只取七类；旧值只允许进入 `legacy_issue_type`。
- **FR-008**: Segment/Junction 文件名与主几何类型 MUST 保持兼容。
- **FR-009**: T10 MUST 向 T12 传递 `t07_run_root`，且不得为 T12 强制启用 Step3。
- **FR-010**: T07 代码、接口和算法 MUST 不变。
- **FR-011**: 输入、几何、拓扑 MUST 不被修改或 silent fix。
- **FR-012**: manifest/summary MUST 可核验来源、分类、计数、CRS、环境和性能。

## 6. Success Criteria

- **SC-001**: `O_J03 = E_J03`、`O_J04 = E_J04`；漏报、多报、重复均为 0。
- **SC-002**: Step3 cardinality 导入数为 0；`junction_relation_cardinality_mismatch` 新结果数为 0。
- **SC-003**: `764857`、`26981804` 在三类 Junction 文件中的总出现数为 0。
- **SC-004**: 七类 confirmed 的分类字段完整率为 100%，未知新类型数为 0。
- **SC-005**: Segment `1026960` 保持 `63/10/53/0`，10 个 confirmed ID 不变，类型只按映射迁移。
- **SC-006**: T03 注册集 TP=4、FP=0、FN=0，J01=2、J02=2。
- **SC-007**: Segment/Junction candidate 集合计数守恒且 candidate ID 唯一。
- **SC-008**: Segment-only 三次中位数不超过 v9 的 110%；Junction-enabled T12 不超过 v9 的 150%；峰值内存不超过对应基准的 120%。
- **SC-009**: 为执行 T12 而额外执行 T07 Step3 的次数为 0。
- **SC-010**: QGIS 工程无失效图层，包含原始 SWSD 与原始 RCSD/FRCSD，Segment 为线几何族（`LineString/MultiLineString`）、Junction 为 Point。

## 7. Scope

### In Scope

- T12 代码、测试、模块源事实和必要的项目级源事实；
- T10 的 T07 Step2→T12 handoff、契约和工作流测试；
- 既有 T12/T10 内网脚本参数与连续性修正；
- QGIS 构建/检查脚本和验证记录；
- 入口登记与代码体量台账的必要同步。

### Out of Scope

- 修改 T03/T07/T05/T06/T09/T11 算法；
- 自动修复原始 SWSD、RCSD、FRCSD；
- 根据局部 Case 推导上游字段新语义；
- 新增正式 repo 级执行入口。
