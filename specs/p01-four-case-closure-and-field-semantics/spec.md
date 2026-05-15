# Feature Specification: P01 四 Case 收口与字段语义裁定

**Feature Branch**: `p01-four-case-closure-and-field-semantics`
**Created**: 2026-05-15
**Last Updated**: 2026-05-15（用户裁决 C-1=A / C-2=D / C-3=α / C-4 自决 / C-5 yes / C-6 yes / C-7 接受；数据缺失根因可接受）
**Status**: Ready for plan（specify 阶段已锁；尚未进入 plan/tasks/implement）
**Owner**: 用户已签收裁决；任务书锁定，进入 plan.md 起草。
**Input**: 基于 `outputs/_work/p01_audit_2026-05-15/P01_audit_report.md`、`P01_business_correctness_report.md` 与字段语义实测分析。

---

## 0. 任务书定位

本任务书覆盖 P01 在 7 个本地测试用例上的"实现-数据-基线"对齐问题。它**不新增 P01 业务能力**，也**不涉及 P01-A3 / P01-B**。它只做四件事：

1. 把 `baseroadid` 在已验证 case 中的实际分布事实（字符串空数组 `"[]"`）写进 `INTERFACE_CONTRACT.md` §8 与 `architecture/11-risks-and-technical-debt.md`，让契约措辞与现实数据精确对齐；原审计 R1 在量化复核后判定为**误报**（"非空字符串" vs "业务空数组" 的字面 vs 语义混淆），不触发代码改动。
2. 把实际数据中出现、但当前 architecture / contract 未单列的 `kind` 灰色值（12 = bit2|bit3 / 20 = bit2|bit4 / 8192 = bit13）的**兜底语义**写进 `architecture/04-solution-strategy.md`，并在 `junction_context.json` 增加 `kind_distribution` audit 字段。兜底语义保持现行 e2e 行为：除 bit2 (kind=4) 触发既有边界候选规则外，其它独立位按 `kind != 4` 默认继续 trace 不停止；本任务**不改 P01 主规则**，只把现行行为显式声明。
3. 把当前未签收的 4 个 case（5312848 / 5595587 / 5659051 / 612654679）**按事实状态**形成 observed baseline，以建立后续回归保护。**业务正确性根因已锁定**：5659051 / 612654679 的 SWSD 在中心路口 RoadNextRoad **完全缺失**（0 条），5312848 / 5595587 的 SWSD 极度稀疏（1-2 条）；仓库实现 100% 走 `alternate_source_role_ordinal_projection` 合规退化，**符合契约 §8**；上游 SWSD 数据缺失视为**已接受的边界**，**不在 P01 内部修复**。
4. 把 `frcsd_road_next_road.geojson` 的 `turntype` 输出编码（`unknown=0 / straight=1 / left=2 / right=3 / uturn=4`）显式标注为**仓库内部审计编码 + 无外部权威依据**；标 `NEEDS_CLARIFICATION_FROM_RCSD_SPEC`；不改编码值、不改代码，仅文档级声明。

## 0.1 用户裁决记录（specify 阶段冻结）

| 编号 | 选项 | 用户裁决 | 含义 |
|---|---|---|---|
| C-1 | A / B / C | **A** | 保持 `baseroadid` "不作为来源映射依据" 口径，并把契约措辞精确化为"字符串空数组 `[]`" |
| C-2 | D / E | **D** | 未列举 kind 值按 `kind != 4` 默认 continue；`junction_context.json` 增 kind 分布 audit |
| C-3 | α / β | **α** | 现行 turntype 编码保留但标注非权威；不改代码 |
| C-4 | 自决 / 用户给名 | **自决** | observed baseline 目录名采用 `p01_final_seven_cases_observed_2026-05-15/` |
| C-5 | yes / no | **yes** | implement 阶段必须重跑 7 case e2e 作为 baseline 来源 |
| C-6 | yes / no | **yes** | baseline `README.md` 必须附"为何 4 case 未 accepted"的人工说明 |
| C-7 | 接受 / 修改 | **接受** | NFR-005 ±30% 性能偏差门槛 |
| 业务根因 | – | **接受"上游 SWSD 数据缺失"作为已知边界** | 5659051 / 612654679 不在 P01 内部修复 |

**显式不在范围内**：

- 不在本任务书内提升任何 case 的 F-RCSD 通行规则正确性（不动 `final_road_next_road.py` 的判定主路径）。
- 不修改 P01 v1.0.0 的核心业务规则（`SourceArmPassRule` / movement_type / trunk / Arm 构建）。
- 不实现 P01-A3 跨源 Movement 空间。
- 不对 `topology.py` / `final_road_next_road.py` / `test_p01_arm_build.py` 做体量拆分（拆分另立 SpecKit 任务）。
- 不修改 P01 对外 callable runner 签名。

---

## 1. 五视角职责覆盖（按 `AGENTS.md` §6 强制）

| 视角 | 本任务承担 |
|---|---|
| 产品 | 明确"4 个 case 当前是否算业务符合预期"，把"低置信审计标签"在业务语义上正式定位为"P01 v1.0.0 合规输出"或"待业务侧补充真值的待办"。 |
| 架构 | 把 `baseroadid` / 灰色 `kind` / `turntype` 编码三处**字段语义口径**在 `INTERFACE_CONTRACT.md` / `architecture/*` 中收口；不引入新接口字段，不变更模块边界。 |
| 研发 | 仅做文档级修订与 baseline 落档；如裁定结果要求代码侧增加防御性检查（如新 kind 进 audit 而非静默），实现保持最小局部修改。 |
| 测试 | 为每个 case 落 baseline；新增/扩展 4 个 case 的 e2e 回归断言（与 baseline 哈希对齐）；不替换现有 27 项需求单元测试。 |
| QA | 审查 baseline 落档过程的可追溯性（输入数据哈希、run id、工具版本、CRS、参数）；审查文档修订是否触发 §1.1 / §1.5；最终验收以"审计 R1–R4 全部 closed 或显式标注为已知未裁定项"为门槛。 |

---

## 2. User Scenarios & Testing

### User Story 1 - 把审计冲突 R1（`baseroadid`）显式裁定 (Priority: P1)

**场景**：产品 / 数据 owner 拿到审计报告 §5.R1，需要在不修改业务规则代码的前提下，让契约文档"言行一致"。

**Why this priority**: 这是 `AGENTS.md` §1.1 命中的源事实冲突；只要不裁定，任何 P01 后续变更都被该冲突阻断。是 P0 阻塞点。

**Independent Test**: 检查在本任务 implement 完成后，`INTERFACE_CONTRACT.md` §8 与 `architecture/11-risks-and-technical-debt.md` 中关于 `baseroadid` 的所有陈述是否一致，且能在 7 个 case 的 F-RCSD `roads.gpkg` 上**自动校验**该陈述真伪。

**Acceptance Scenarios**:

1. **Given** 用户裁定"baseroadid 在已验证 case 中**非空**，但仍**不作为来源映射依据**"，**When** implement 完成，**Then** `INTERFACE_CONTRACT.md` §8 与 `architecture/11-risks-and-technical-debt.md` 中"baseroadid 为空"陈述被替换为"baseroadid 实际非空，仅作为审计参考字段，禁止作为 source mapping 依据"。
2. **Given** 用户裁定"baseroadid 升级为正式来源映射字段"，**When** implement 完成，**Then** 本 spec 被升级为更大范围的 SpecKit 任务（不在本任务书内完成），本任务书标注为"被取代"，并保留为审计证据。
3. **Given** 用户裁定"baseroadid 完全废弃，建议下游数据治理移除该字段"，**When** implement 完成，**Then** 契约文档中删除 baseroadid 描述，并增加"该字段已知存在但不被 P01 使用"的 stop-mark。

### User Story 2 - 灰色 `kind` 值（12 / 20 / 8192）裁定兜底语义 (Priority: P2)

**场景**：研发在新增 case 时不希望 trace 因为遇到未列举 kind 值而行为不可预期。

**Why this priority**: 当前实现对未列举 kind 已"按 `kind != 4` 默认 continue"，e2e 未出错，但口径未声明。属于已知技术债。

**Independent Test**: 实际 7 case 数据中遍历所有出现过的 kind 值，全部能在 `architecture/04-solution-strategy.md` Trace 节找到显式语义（包括"未列举值的兜底"语义）。

**Acceptance Scenarios**:

1. **Given** 用户裁定"未列举 kind = 按 kind != 4 默认 continue trace"，**When** implement 完成，**Then** `architecture/04-solution-strategy.md` Trace 节增加"未列举 kind 值兜底"段落，并要求在 `junction_context.json` 内对每个 case 出现的 kind 分布做 audit 输出。
2. **Given** 用户裁定"灰色 kind 必须停 trace 并写 issue"，**When** implement 完成，**Then** `topology.py` 增加显式 unknown kind 处理分支（生成 issue 而非 silent continue），且新增至少 1 个单元测试覆盖。

### User Story 3 - 4 个未签收 Case 形成 baseline (Priority: P1)

**场景**：QA 需要为 5312848 / 5595587 / 5659051 / 612654679 建立"当前状态" baseline，避免后续重构出现回归盲区。

**Why this priority**: 这是审计 R2 的直接后果；没有 baseline，本仓库对这 4 个 case 的所有规则变更都会陷入"无可比对象"。属于 P0 治理阻塞点。

**Independent Test**: 在不修改任何 P01 业务规则的情况下，重跑 7 case 统一 e2e；4 个新 case 的最终输出（`frcsd_road_next_road.geojson` + `final_generation_decisions.json` + `frcsd_road_next_road_audit.json` + `frcsd_road_next_road_issue_report.json`）能按现有 `baselines/p01_final_three_cases_accepted_2026-05-12/` 结构落档，并附 manifest + checksum。

**Acceptance Scenarios**:

1. **Given** 7 case 重跑 e2e 后，**When** implement 完成，**Then** `modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/` 目录建立，每个 case 子目录含 `frcsd_road_next_road.geojson` 等核心文件 + `manifest.json` + `case_summary.csv` + `README.md`。
2. **Given** 4 个新 case 当前含 P0 / P1 issue，**When** implement 完成，**Then** baseline `README.md` 显式标注 4 个 case 的状态为 `observed_not_accepted`，**不**与 2026-05-12 的 `accepted` baseline 等价；同时附"为何未 accepted"的逐条引用（如 `5659051: 15 unresolved bit7 relations / 12 alternate_source_role_ordinal_projection / 14 manual_review_required` 等机器数据）。
3. **Given** 用户后续希望升级某个 case 为 accepted，**When** 用户提供该 case 的人工真值，**Then** 不在本任务内 implement；本任务只把 observed baseline 作为后续 accepted 升级的对比基础。

### User Story 4 - `turntype` 输出编码权威依据裁定 (Priority: P2)

**场景**：当前 `turntype` 编码 `unknown=0 / straight=1 / left=2 / right=3 / uturn=4` 是仓库自定义冻结口径，没有 RCSD 规范权威文件证明。任何下游消费方提出"为何 right=3 而不是 right=4"时，仓库没有依据。

**Why this priority**: 当前不阻塞业务，但属于审计未完全闭合项。

**Independent Test**: `INTERFACE_CONTRACT.md` §8 中 turntype 映射段落能定位到一个"权威依据来源"或"仓库内冻结说明 + 已知风险"段落。

**Acceptance Scenarios**:

1. **Given** 用户提供 RCSD 官方编码规范，**When** implement 完成，**Then** 契约 §8 turntype 映射段附"权威依据：<文档名 / 路径 / 版本>"。
2. **Given** 用户**未提供**官方依据，**When** implement 完成，**Then** 契约 §8 turntype 映射段保留现行编码并显式标注"NEEDS CLARIFICATION：编码无外部权威依据，按仓库自定义冻结；未来若 RCSD 给出冲突编码，需要走独立入口变更任务"。

### Edge Cases

- **F-RCSD `Source` 出现非 1/2 值**：契约 §8 已声明进入 issue；本任务不修改此行为，但要求 7 case 实跑数据中如出现需作为 baseline observed issue 落档。
- **某个 case 在 implement 阶段实跑失败（A1 异常）**：必须保留 stderr、`preflight.json` 与原始 issue，归档到 baseline `failures/<case>/` 子目录；不强行让 implement pass。
- **baseroadid 字段命名大小写漂移**：契约要求字段读取大小写不敏感；本任务的 §3.1 字段口径裁定必须显式覆盖大小写归一化策略。
- **kind = 8192 在某 case 数量很大**：要求 baseline 中的 `junction_context.json` 必须保留 kind 分布统计，便于回归比对。
- **重跑 e2e 后某个 case 输出与本审计观察到的产物哈希不一致**：必须先比对 `preflight.json` 中的输入哈希；输入相同输出不同视为"实现不可复现"风险，进入 P0 issue，本任务不允许 mask。

---

## 3. Requirements

### 3.1 功能需求（字段语义裁定）

- **FR-001（baseroadid，R1）→ 用户裁决 = A**：必须在**同一轮**修订 `modules/p01_arm_build/INTERFACE_CONTRACT.md` §3.1（F-RCSD Road 字段要求）、§8（Source road mapping audit）、`architecture/11-risks-and-technical-debt.md` 关于 `baseroadid` 的所有陈述，使其与现实数据精确一致。具体措辞应明确：
  - `baseroadid` 字段在 7 case F-RCSD `roads.gpkg` 中实测为 **JSON 空数组的字符串字面值 `"[]"`**（不是 NULL、不是空字符串、不是缺字段）。
  - 该字段的**设计意图**是 F-RCSD road 的多源 base road id 合并链路审计；当前 F-RCSD 数据未填充。
  - **不**作为来源映射依据；映射仍走 `Source + CRS 归一化 rounded exact geometry`。
  - 不触发任何代码读取/解析 baseroadid 的实现修改。
- **FR-002（灰色 kind，R4）→ 用户裁决 = D**：必须在 `architecture/04-solution-strategy.md` Trace 节增加"未列举 kind 兜底"段落，并在 A1 输出 `junction_context.json` 增加 `kind_distribution` audit 字段。具体语义：
  - bit2 (kind=4) 维持既有边界候选规则。
  - bit11 (kind=2048) 维持既有 T 型规则。
  - 其它独立位（bit0=1, bit3=8, bit4=16, bit13=8192）与复合值（12=bit2|bit3, 20=bit2|bit4 等）按 **`kind != 4` 默认 continue trace** 兜底（这已经是当前实现行为，本任务只是**显式声明**，不改判定主路径）。
  - `kind_distribution` audit 字段格式：`{"<kind_value>": <count_of_member_nodes_with_that_kind>}`，仅作 audit，不影响主规则；放在 `junction_context.json` 顶层。
  - 单元测试：必须新增覆盖该 audit 字段的测试用例，**禁止追加到 `test_p01_arm_build.py`**（96.7 KB 已逼近 100 KB 硬阈值），必须新建 `tests/modules/p01_arm_build/test_p01_kind_audit.py`。
- **FR-003（turntype 编码，R5）→ 用户裁决 = α**：必须在 `INTERFACE_CONTRACT.md` §8 turntype 映射段加显式声明：
  - 现行编码 `unknown=0 / straight=1 / left=2 / right=3 / uturn=4` 是**仓库内部审计编码**，**无外部 RCSD 规范权威依据**。
  - 标 `NEEDS_CLARIFICATION_FROM_RCSD_SPEC`：未来取得 RCSD 官方编码规范后，需独立 SpecKit 任务修订；下游消费方在权威规范确定前**不得对该字段做强解释**。
  - **不**改编码值、**不**改 `final_road_next_road.py`、**不**改既有 baseline。

### 3.1bis 业务正确性根因锁定（已与用户裁决）

- 4 个未签收 case 的 F-RCSD 通行规则**未达预期**现象，根因分类为：

| Case | 中心路口 SWSD RoadNextRoad | 中心路口 RCSD RoadNextRoad | 仓库 final 输出 | 根因 |
|---|---|---|---|---|
| 5312848 | **2** 条 | 18 条 | 31 条 | 上游 SWSD 极度稀疏；仓库 `full_allowed` 投影到 F-RCSD 多目标退出 Road 属合规放大 |
| 5595587 | **1** 条 | 20 条 | 19 条 | 同上 |
| 5659051 | **0** 条 | 18 条 | 13 条 | **SWSD 完全缺失**；仓库 100% alternate projection 合规退化 |
| 612654679 | **0** 条 | 17 条 | 13 条 | **SWSD 完全缺失**；同上 |

- 这四个 case **不在 P01 内部修复**。仓库实现行为符合 `INTERFACE_CONTRACT.md` §8。
- 后续 accepted 升级路径需要：(a) 业务侧正式接受 alternate projection 作为这些 case 的最终态，或 (b) SWSD 上游数据治理补齐这些路口 RoadNextRoad 后重跑 P01。**两条路径都不属于本任务**。

### 3.2 功能需求（baseline 落档，R2）

- **FR-004**：必须建立 baseline 目录 `modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/`，结构对齐既有 `p01_final_three_cases_accepted_2026-05-12/`：
  - 顶层 `manifest.json` 记录冻结日期、源 run root、工具版本、CRS、checksum。
  - 顶层 `README.md` 明确写："本 baseline 是 observed 状态，不等价于 accepted。4 个新 case 含 P0 / P1 待审 issue，详细见 `case_summary.csv`。"
  - 顶层 `case_summary.csv` 列出 7 case 的 `accepted_status / generated_count / manual_review_required_count / p0_count / p1_count / failed_group_count` 等关键指标。
  - 顶层 `final_pass_relations_with_original_evidence.csv` 与既有 baseline 同 schema，覆盖 7 case。
  - `cases/<case_id>/` 至少包含 `frcsd_road_next_road.geojson` / `frcsd_road_next_road_audit.json` / `frcsd_road_next_road_issue_report.json` / `final_generation_decisions.json` / `preflight.json`（用于复现）。
- **FR-005**：必须在 `outputs/_work/` 下统一新跑 7 case 的 e2e run root（建议 run id：`p01_seven_cases_baseline_observed_20260515`），不复用现有零散 run；新 run root 的 `case_results.json` / `p01_arm_build_summary.json` / `p01_arm_build_review_index.csv` 作为 baseline 的"权威 run 证据"，由 baseline `manifest.json` 引用其相对路径。
- **FR-006**：必须验证新 run root 与本审计已观察到的 5312848 / 5595587 / 5659051 / 612654679 e2e 产物在以下机器口径上一致：`generated_road_next_road_count`、`alternate_source_projected_count`、`manual_review_required_count`、`failed_group_count`、`p0_review_count`、`p1_review_count`。差异必须解释并归入 issue（**不允许 mask**）。

### 3.3 功能需求（治理同步）

- **FR-007**：完成 FR-001/FR-002 时，必须**同轮**修订 `modules/p01_arm_build/history/p01_v1_coverage_audit.md`，把新增的字段口径裁定行登记为"已实现 / 已裁定"，并附本 spec 的 feature branch 名称引用。
- **FR-008**：若 FR-002 选 E（unknown kind 写 issue），必须**同轮**更新 `docs/repository-metadata/code-size-audit.md` 中 `topology.py` 行的 size after-change 估计；若变更后逼近 100 KB，必须先回报，按 `AGENTS.md` §3 处理。

### 3.4 非功能需求（GIS / 拓扑 / 审计）

- **NFR-001（CRS 一致性）**：baseline 落档时所有 `frcsd_road_next_road.geojson` 必须保留与输入 F-RCSD `roads.gpkg` 同一 CRS（WGS 84 / EPSG:4326，按本审计实测）；任何 silent CRS reproject 视为 fail。
- **NFR-002（拓扑一致性）**：baseline `frcsd_road_next_road.geojson` 中 `(road_id, next_road_id)` 必须无重复对；本任务的 verification 步骤必须显式断言这一点。
- **NFR-003（几何语义可解释性）**：baseline manifest 必须保留每个 case 输入数据的 SHA-256 checksum（与 `E:\TestData\POC_Data\Interestion\<case>\manifest.json` 内的 checksum 一致）。
- **NFR-004（审计可追溯性）**：baseline 内每条 final pass relation 必须能在 `final_generation_decisions.json` / `frcsd_road_next_road_audit.json` 中找到对应 decision；本任务 verification 步骤必须断言 `frcsd_road_next_road.geojson` 与 `frcsd_road_next_road_audit.json` 之间的 1:1 引用关系。
- **NFR-005（性能可验证性）**：新 run root 总耗时与现有 6-case audit (`p01_local_6case_full_audit_v001/` 中各 case 30–45 秒) 的偏差不超过 ±30%；超过须解释。

### 3.5 字段 / 实体（不引入新字段）

本任务**不引入任何新字段**。仅对以下字段的"语义口径"做裁定与文档同步：

- **`F-RCSD:Road.baseroadid`**：当前实际填充字段，但 P01 业务规则不消费；本任务裁定后语义将固化为 A / B / C 三种之一。
- **`Node.kind`**：当前 P01 已显式覆盖 4 / 2048 / `!= 4` 三类；本任务将固化 12 / 20 / 8192 等灰色值的兜底语义。
- **`turntype`（输出字段）**：当前编码 `unknown=0 / straight=1 / left=2 / right=3 / uturn=4` 已冻结；本任务将固化"是否有外部权威依据"的元数据。

### 3.6 兼容性约束

- 不修改 `run_p01_arm_build_from_args` / `run_p01_arm_alignment_from_args` 签名。
- 不修改 A1 / A2 / Final 既有输出 schema（仅在 `junction_context.json` 中追加 kind 分布字段，若 FR-002 选 D）。
- 既有 2026-05-12 accepted baseline 不变更内容。本任务建立的新 baseline 是 observed 平行档案，不替代 accepted。

---

## 4. Success Criteria

### Measurable Outcomes

- **SC-001（R1 closed）**：implement 完成后，`baseroadid` 的字段语义在 `INTERFACE_CONTRACT.md` / `architecture/*` / `history/p01_v1_coverage_audit.md` 三处描述完全一致；任意一处与现实 7 case 数据矛盾视为 fail。
- **SC-002（R2 closed）**：7 case 全部进入 baseline；其中 3 case 标记 accepted（与 2026-05-12 一致），4 case 标记 observed_not_accepted；baseline manifest 覆盖输入 checksum、run id、CRS、工具版本。
- **SC-003（R4 closed）**：实际数据中所有出现过的 kind 值都能在 `architecture/04-solution-strategy.md` Trace 节定位到显式语义。
- **SC-004（R5 closed-or-explicit-NEEDS-CLARIFICATION）**：`turntype` 编码段落要么附权威依据，要么显式标注 NEEDS CLARIFICATION；不允许默认沉默。
- **SC-005（无回归）**：3 个 2026-05-12 accepted case 在新 run root 中的核心指标（`generated_road_next_road_count` 等）与已冻结 baseline 完全一致；否则进入 P0。
- **SC-006（治理同步）**：`docs/repository-metadata/code-size-audit.md` 体量登记与新 run 后实际文件体量一致；逼近 100 KB 的文件必须有显式说明。
- **SC-007（可复现）**：任何第三方在拿到 baseline `manifest.json` 后，按其引用的工具版本 + 输入 checksum + 命令行参数重跑，输出文件 SHA-256 与 baseline 一致。

### Out-of-scope success items（明确**不算**本任务成功标准）

- 不要求消除任何 case 的 `manual_review_required` / `alternate_source_role_ordinal_projection` / `data_error_partial_target_coverage`。
- 不要求把 5312848 / 5595587 / 5659051 / 612654679 升级为 accepted。
- 不要求改进 trunk 闭环完整度（当前 7 case `trunk_complete_count = 0` 属于真实数据规律，不在本任务内处理）。

---

## 5. NEEDS CLARIFICATION 清单（已全部裁决）

| 编号 | 待裁决项 | 用户裁决 | 落地内容 |
|---|---|---|---|
| C-1 | `baseroadid` 口径 | **A** | 把现实数据"`baseroadid` = 字符串 `"[]"`" 精确写进契约；不作为来源映射依据；不改代码 |
| C-2 | 灰色 `kind` 兜底语义 | **D** | `kind != 4` 默认 continue 已显式声明；`junction_context.json` 加 kind_distribution audit；新增独立测试文件 |
| C-3 | `turntype` 编码权威依据 | **α** | 现行 `0/1/2/3/4` 标注为仓库内部审计编码，无 RCSD 权威依据；标 `NEEDS_CLARIFICATION_FROM_RCSD_SPEC` |
| C-4 | observed baseline 命名 | 自决 | `modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/` |
| C-5 | implement 阶段重跑 7 case e2e | **yes** | tasks.md 中作为强制前置任务 |
| C-6 | baseline README 附人工说明 | **yes** | 含"为何 4 case 未 accepted = 上游 SWSD 数据缺失" 文本 |
| C-7 | NFR-005 ±30% 性能偏差门槛 | **接受** | 不修订 |
| 业务根因 | 4 case 未达预期 | **接受"上游 SWSD 数据缺失"为已知边界，不在 P01 内部修复** | 已记入 §3.1bis |

---

## 6. 与既有源事实的关系

- `SPEC.md`（项目级）：本任务**不修改**。
- `docs/PROJECT_BRIEF.md` / `docs/architecture/*`：本任务**不修改**。
- `modules/p01_arm_build/AGENTS.md`：本任务**不修改**。
- `modules/p01_arm_build/INTERFACE_CONTRACT.md`：本任务**修订** §3.1 / §8 / §10 中与 `baseroadid` / `turntype` 编码权威性相关的段落（视裁定结果）。
- `modules/p01_arm_build/architecture/02-constraints.md`：本任务**修订** `baseroadid` 风险段落（视裁定结果）。
- `modules/p01_arm_build/architecture/04-solution-strategy.md`：本任务**修订** Trace 节增加灰色 kind 兜底（视裁定结果）。
- `modules/p01_arm_build/architecture/11-risks-and-technical-debt.md`：本任务**修订** `baseroadid` 风险条目。
- `modules/p01_arm_build/history/p01_v1_coverage_audit.md`：本任务**追加**字段口径裁定与新 baseline 登记。
- `modules/p01_arm_build/baselines/p01_final_three_cases_accepted_2026-05-12/`：本任务**不变更**。
- `modules/p01_arm_build/baselines/p01_final_seven_cases_observed_2026-05-15/`（新增）：本任务**创建**。
- `docs/repository-metadata/code-size-audit.md`：本任务**追加**新 run 后实际文件体量（若 FR-002 选 E 触发 `topology.py` 修改）。
- `src/rcsd_topo_poc/modules/p01_arm_build/*.py`：本任务**默认不修改**；仅在 FR-002 选 E 时，对 `topology.py` 做最小 unknown kind issue 输出修改，并同轮触发 `code-size-audit.md` 同步。
- `tests/modules/p01_arm_build/`：本任务**默认不修改**；仅在 FR-002 选 E 时新增 1 个单元测试覆盖 unknown kind issue。注意 `test_p01_arm_build.py` 已 96.7 KB，逼近 100 KB；新测试**必须**进入新文件而非追加既有文件。

---

## 7. 触发的硬约束自检

| 条款 | 自检 |
|---|---|
| `AGENTS.md` §1.1 | 本任务**显式裁定**源事实冲突 R1，不再继续累积冲突。 |
| `AGENTS.md` §1.2 | 本任务对 `INTERFACE_CONTRACT.md` 等保护区文档的修订**已包含在本任务书的 §6 显式授权范围中**，但需要用户签收本 spec 才有效。 |
| `AGENTS.md` §1.3 | 本任务**不新增**长期保留的正式执行入口（不动 Makefile / scripts / __main__ / run.py / CLI）。 |
| `AGENTS.md` §1.4 / §3 | 若 FR-002 选 E 触发 `topology.py` 修改，必须**先**做字节数自检，预计 +1 KB 以内（仅一个 issue 分支 + 单元测试新文件）；逼近 100 KB 时停机回报。`test_p01_arm_build.py` 96.7 KB 不允许追加。 |
| `AGENTS.md` §1.5 | 本任务**不**根据局部样本反推上游字段语义；R1 / R4 的裁定权由用户在 C-1 / C-2 显式给出。 |
| `AGENTS.md` §1.6 | 测试数据路径在 PowerShell 会话下使用 `E:\TestData\POC_Data\Interestion\...`；新 run root 在 PowerShell 下使用 `E:\Work\RCSD_Topo_Poc\outputs\_work\...`；如 implement 阶段切换为 WSL 必须做路径换算与确认。 |
| `AGENTS.md` §1.7 | 本任务**非**入口变更任务。 |
| `AGENTS.md` §5 | 本任务覆盖 CRS、拓扑一致性、几何语义可解释性、审计可追溯性、性能可验证性（见 NFR-001 ~ NFR-005）。 |
| `AGENTS.md` §6 | 本任务书已覆盖产品 / 架构 / 研发 / 测试 / QA 五视角（见 §1）。 |
| `AGENTS.md` §8 | 本文档使用中文，参数 / 字段 / 路径保留英文，符合默认语言要求。 |

---

## 8. 下一步

- 本文件 `Status = Ready for plan`，所有 NEEDS CLARIFICATION 已被用户裁决。
- 进入 `plan.md` 起草。
- `tasks.md` 形成后再进入 implement 阶段。
- implement 阶段分四步：Phase A（文档修订）→ Phase B（最小代码改动 + 新测试文件）→ Phase C（7 case e2e 重跑，需 WSL 执行）→ Phase D（observed baseline 落档）。
