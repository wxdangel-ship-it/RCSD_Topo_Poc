# T04 - INTERFACE_CONTRACT

## 定位

本文档是 `t04_divmerge_virtual_polygon` 的稳定接口契约，约束输入、输出、状态机、枚举和值域。Step1-7 的业务策略见 `architecture/04-solution-strategy.md`；质量门槛与冻结 baseline gate 见 `architecture/10-quality-requirements.md`。

本文档不作为实现细节清单，不复制 T03 业务语义，也不新增 repo 官方 CLI。

## 1. Formal Scope

T04 当前正式承接：

- `diverge / merge / continuous complex 128` 候选。
- case-package batch 与 internal full-input 两类执行面。
- Step1-7 完整链路：
  - `Step1 = candidate admission`
  - `Step2 = high-recall local context`
  - `Step3 = topology skeleton`
  - `Step4 = fact event interpretation`
  - `Step5 = geometric support domain`
  - `Step6 = polygon assembly`
  - `Step7 = final acceptance and publishing`
- batch / full-input 发布：
  - `divmerge_virtual_anchor_surface*`
  - rejected / summary / audit / consistency report
  - downstream `nodes.gpkg` 与 `nodes_anchor_update_audit.csv/json`

正式边界：

- Step1 不做事实解释与几何裁决。
- Step2 只组织 local context 与 SWSD negative context；RCSD 正向支持在 Step4 解释。
- Step3 区分 `case coordination skeleton` 与 `unit-level executable skeleton`。
- Step4 做 event-unit 事实解释、主证据、Reference Point、section reference、正向 RCSD / SWSD 支持与受控恢复；不生成最终 polygon。
- Step5 定义 `must_cover / allowed_growth / forbidden / terminal_cut`。
- Step6 在 Step5 约束内生成单一连通 case polygon。
- Step7 只发布 `accepted / rejected` 二态最终结果。

非目标：

- 不新增 repo 官方 CLI。
- 不把 T04 surface 主产物改名为 T03 风格产物。
- 不把 Step4 内部 review 态作为 Step7 第三种最终状态。
- 不将 `857993 = rejected` 解释为待修成 accepted 的缺陷。

## 2. Inputs

### 2.1 Case-package 输入

每个 case-package 至少包含：

- `manifest.json`
- `size_report.json`
- `drivezone.gpkg`
- `divstripzone.gpkg`
- `nodes.gpkg`
- `roads.gpkg`
- `rcsdroad.gpkg`
- `rcsdnode.gpkg`

约束：

- 默认 CRS 为 `EPSG:3857`。
- `nodes.gpkg` 必须保留 representative node 与 group nodes。
- `divstripzone.gpkg` 是 T04 正式输入，不是可选 review 辅助层。
- 缺失 `rcsdroad.gpkg / rcsdnode.gpkg` 中的对应事实不得在 Step1 直接阻断；后续步骤必须用审计字段解释 RCSD 缺失、弱支持或冲突。

### 2.2 Internal full-input 输入

full-input 执行面使用 full-layer source：

- `nodes`
- `roads`
- `DriveZone`
- `DivStripZone`
- `RCSDRoad`
- `RCSDNode`

执行约束：

- candidate discovery 只负责发现 representative candidates，不替代 Step1 admission。
- full-input 先 preload shared layers 与 spatial index，再按 case 收集局部 feature 并直跑 Step1-7。
- downstream `nodes.gpkg` 必须基于 full-input 输入整层 `nodes.gpkg` 做 copy-on-write。

### 2.3 必要字段

`nodes.gpkg` 至少需要：

- `id`
- `mainnodeid`
- `has_evd`
- `is_anchor`
- `kind` 或 `kind_2`
- `grade_2`（若输入提供则必须保留）

`roads.gpkg` 至少需要：

- `id`
- `snodeid`
- `enodeid`
- `direction`

`rcsdnode.gpkg` 至少需要：

- `id`
- `mainnodeid`

所有 copy-on-write 输出必须保留输入 geometry 与原字段；新增字段或覆盖字段必须在本契约或质量文档中说明。

## 3. State Machines And Value Domains

### 3.1 Step4 内部审计态

Step4 允许以下内部审计态：

- `STEP4_OK`
- `STEP4_REVIEW`
- `STEP4_FAIL`

约束：

- 这些值只属于 Step4 审计层。
- `STEP4_REVIEW` 可以表示 soft-degrade 或需要人工关注的解释结果，不是 Step7 最终状态。
- 不得重新引入最终 `review / review_required`。

### 3.2 Step4 evidence source

`evidence_source` 允许值：

- `divstrip_direct`
- `multibranch_event`
- `conservative_fallback`
- `reverse_tip_retry`
- `road_surface_fork`
- `swsd_junction_window`
- `rcsd_junction_window`
- `rcsd_anchored_reverse`
- `none`

### 3.3 Step4 position source

`position_source` 允许值：

- `divstrip_ref`
- `drivezone_split`
- `fallback`
- `representative_axis_origin`
- `road_surface_fork`
- `swsd_junction_window_axis_projection`
- `rcsd_junction_window_axis_projection`
- `rcsd_anchored_axis_projection`
- `none`

既有 `evidence_source / position_source` 值域保持兼容：`swsd_junction_window / rcsd_junction_window / rcsd_anchored_reverse` 只能表达受控恢复、截面参考或支撑域来源，不得被解释为主证据或虚拟 Reference Point。

### 3.4 主证据、Reference Point 与 section reference

T04 的主证据只指真实世界物理空间证据，当前稳定值域为：

`main_evidence_type`：

- `divstrip`
- `road_surface_fork`
- `none`

`fact_reference_point / Reference Point` 只在 `has_main_evidence = true` 时成立，且来源只能是主证据：

`reference_point_source`：

- `divstrip`
- `road_surface_fork`
- `none`

约束：

- 有导流带主证据时，Reference Point 来自导流带真实决定分歧 / 合流的位置。
- 有道路面分叉主证据时，Reference Point 来自道路面形态真实切换的位置。
- 无主证据时，`reference_point_present = false`，`fact_reference_point = null`，`reference_point_source = none`。
- 不得从 RCSD 语义路口、RCSDRoad、SWSD 语义路口、SWSD candidate、历史抽象 node、拓扑召回点或仅由抽象路网推导出的代理点反推 Reference Point。

`section reference / 截面参考对象` 用于确定路口面前后横向截面位置，不等同于 Reference Point。`section_reference_source` 允许值：

- `reference_point`
- `reference_point_and_rcsd_junction`
- `rcsd_junction`
- `swsd_junction`
- `none`

RCSD / SWSD 只能作为 `section_reference_source`、抽象路网参考、截面参考、支撑域约束或审计辅助；不得写成主证据或 Reference Point。

`RCSD 语义路口` 是比“存在 RCSD 数据 / RCSDRoad”更强的概念：召回的 RCSD 路口必须与当前 SWSD 路口在语义上对齐，至少具备与当前事件一致的进入道路、退出道路和角度趋势。若只有 RCSDRoad 趋势支持，或 RCSD 路口相对 SWSD 路口缺少进入 / 退出道路，或只能形成 `role_mapping_partial_aggregated` 这类弱聚合，则不得登记为 `rcsd_junction`，只能作为 `rcsdroad_fallback`、趋势参考或审计辅助。

### 3.5 路口面场景与生成模式

`surface_scenario_type` 允许值：

- `main_evidence_with_rcsd_junction`
- `main_evidence_with_rcsdroad_fallback`
- `main_evidence_without_rcsd`
- `no_main_evidence_with_rcsd_junction`
- `no_main_evidence_with_rcsdroad_fallback_and_swsd`
- `no_main_evidence_with_swsd_only`
- `no_surface_reference`

场景语义：

- `main_evidence_with_rcsd_junction`：有主证据 + RCSD 语义路口；Reference Point 由主证据决定，section reference 为 `Reference Point + RCSD 语义路口`。
- `main_evidence_with_rcsdroad_fallback`：有主证据 + 无 RCSD 语义路口但存在 RCSDRoad fallback；Reference Point 由主证据决定，section reference 为 `Reference Point`，fallback 只覆盖相关局部段。
- `main_evidence_without_rcsd`：有主证据 + 无 RCSD 语义路口且无可用 RCSDRoad fallback；Reference Point 由主证据决定，主证据独立驱动构面。
- `no_main_evidence_with_rcsd_junction`：无主证据 + RCSD 语义路口；无 Reference Point，section reference 为 `RCSD 语义路口`。
- `no_main_evidence_with_rcsdroad_fallback_and_swsd`：无主证据 + RCSDRoad fallback + SWSD 语义路口；无 Reference Point，section reference 为 `SWSD 语义路口`，fallback 只覆盖相关局部段。
- `no_main_evidence_with_swsd_only`：无主证据 + 无 RCSD 语义路口 + SWSD 语义路口；可存在非语义路口的 RCSD 数据或趋势一致的 RCSDRoad 审计信息，但不得把它们登记为 `rcsd_junction`；无 Reference Point，SWSD-only 构面。
- `no_surface_reference`：无主证据、无 RCSD 语义路口、无 RCSDRoad fallback、无 SWSD 语义路口；无 Reference Point、无 section reference，不生成实体路口面，不伪造 fake final polygon。

`rcsd_match_type` 允许值：

- `rcsd_junction`
- `rcsdroad_fallback`
- `none`

`surface_generation_mode` 允许值：

- `main_evidence_driven`
- `rcsd_junction_window`
- `swsd_junction_window`
- `swsd_with_rcsdroad_fallback`
- `no_surface`

稳定字段登记：

| 字段 | 层级 | 说明 |
|---|---|---|
| `has_main_evidence` | Step4 | 是否存在导流带或道路面分叉主证据。 |
| `main_evidence_type` | Step4 | `divstrip / road_surface_fork / none`。 |
| `reference_point_present` | Step4 | 是否存在真实 Reference Point。 |
| `reference_point_source` | Step4 | `divstrip / road_surface_fork / none`。 |
| `section_reference_source` | Step4/5 | 截面参考对象来源。 |
| `section_reference_geometry` | Step4/5 | 截面参考对象几何；可来自 Reference Point、RCSD junction 或 SWSD junction。 |
| `surface_scenario_type` | Step4/5/summary | 六类业务场景与兜底场景分类。 |
| `rcsd_match_type` | Step4 | `rcsd_junction / rcsdroad_fallback / none`。 |
| `swsd_junction_present` | Step4 | 是否存在可用 SWSD 语义路口。 |
| `fallback_rcsdroad_ids` | Step4/5 | 参与 fallback 的 RCSDRoad 局部段。 |
| `surface_generation_mode` | Step5/6 | 构面模式。 |
| `no_reference_point_reason` | Step4 audit | 无 Reference Point 的原因，至少区分 `no_main_evidence`。 |
| `surface_section_forward_m` | Step5 audit | 前向截面距离，默认 `20`。 |
| `surface_section_backward_m` | Step5 audit | 后向截面距离，默认 `20`。 |
| `surface_lateral_limit_m` | Step5 audit | 横向扩展限制，默认 `20`。 |

### 3.6 Step7 最终状态机

`final_state` 只允许：

- `accepted`
- `rejected`

`runtime_failed / formal result missing` 只能作为 batch closeout、failure doc、streamed terminal record 或 downstream nodes 写回原因出现，不得成为 Step7 正式最终状态。

### 3.7 Step7 relation / reject values

`swsd_relation_type` 允许值：

- `covering`
- `partial`
- `offset_fact`
- `unknown`

`reject_reason` 主值允许：

- `final_polygon_missing`
- `multi_component_result`
- `hard_must_cover_disconnected`
- `b_node_not_covered`
- `forbidden_conflict`
- `allowed_growth_conflict`
- `terminal_cut_conflict`
- `unexpected_hole_present`
- `assembly_failed`

`reject_reason_detail` 可使用 `|` 串联多个拒绝原因；不得把 `857993` 的 `rejected` 解释为待提升 accepted 的缺陷。

### 3.8 Downstream nodes values

T04 downstream `nodes.gpkg` 只正式更新 `is_anchor`：

- Step7 `accepted` -> `is_anchor = yes`
- Step7 `rejected` -> `is_anchor = fail4`
- `runtime_failed / formal result missing` -> `is_anchor = fail4`

`fail4` 是 T04 downstream nodes 写回值域，不改变 T03 的 `fail3` 语义。

## 4. Outputs

### 4.1 Run root 输出

batch / full-input run root 至少包含：

- `preflight.json`
- `summary.json`
- `step4_review_index.csv`
- `step4_review_summary.json`
- `step4_review_flat/`
- `cases/`
- `divmerge_virtual_anchor_surface.gpkg`
- `divmerge_virtual_anchor_surface_rejected.gpkg`
- `divmerge_virtual_anchor_surface_rejected.csv`
- `divmerge_virtual_anchor_surface_rejected.json`
- `divmerge_virtual_anchor_surface_summary.csv`
- `divmerge_virtual_anchor_surface_summary.json`
- `divmerge_virtual_anchor_surface_audit.gpkg`
- `step7_rejected_index.csv`
- `step7_rejected_index.json`
- `step7_consistency_report.json`
- `nodes.gpkg`
- `nodes_anchor_update_audit.csv`
- `nodes_anchor_update_audit.json`

`preflight.json / summary.json` 必须保留最小 provenance：

- `produced_at`
- `git_sha`
- `input_dataset_id`

### 4.2 Case 输出

每个 case 目录至少包含：

- `case_meta.json`
- `step1_status.json`
- `step3_status.json`
- `step3_audit.json`
- `step4_status.json`
- `step4_audit.json`
- `step5_status.json`
- `step5_audit.json`
- `step6_status.json`
- `step6_audit.json`
- `step7_status.json`
- `step7_audit.json`
- `final_review.png`
- `event_units/<event_unit_id>/step3_status.json`
- `event_units/<event_unit_id>/step4_status.json`
- `event_units/<event_unit_id>/step4_candidates.json`
- `event_units/<event_unit_id>/step4_review.png`

case 级 status / audit 工件必须能追溯输入、关键判断、失败原因与运行 provenance。rejected case 可输出 `reject_stub_geometry`，但不得伪造 fake final polygon。

### 4.3 Step3 输出分层

顶层 `step3_status.json` 表达 case coordination skeleton，至少说明：

- member population
- passthrough / branch context
- continuous chain context
- event unit population

event-unit `step3_status.json` 表达 Step4 可执行 skeleton，至少说明：

- `unit_population_node_ids`
- `context_augmented_node_ids`
- `event_branch_ids`
- `boundary_branch_ids`
- `preferred_axis_branch_id`
- `degraded_scope_reason`（如触发）

### 4.4 Step4 review index / summary

`step4_review_index.csv` 至少包含以下字段族：

- identity：`case_id / event_unit_id / mainnodeid / representative_node_id`
- Step4 state：`review_state / evidence_source / position_source`
- topology：`event_branch_ids / boundary_branch_ids / preferred_axis_branch_id`
- pair-local geometry：`pair_local_direction / branch_separation_* / stop_reason`
- evidence：`has_main_evidence / main_evidence_type / selected_candidate_region / selected_evidence / fact_reference_point / reference_point_present / reference_point_source / review_materialized_point`
- section reference：`section_reference_source / section_reference_geometry / surface_scenario_type / surface_generation_mode / no_reference_point_reason`
- RCSD/SWSD：`positive_rcsd_present / positive_rcsd_support_level / positive_rcsd_consistency_level / required_rcsd_node / rcsd_match_type / swsd_junction_present / fallback_rcsdroad_ids / rcsd_decision_reason`
- focus：`needs_manual_review_focus / focus_reasons`

`step4_review_summary.json` 至少汇总：

- total case / event unit counts
- `STEP4_OK / STEP4_REVIEW / STEP4_FAIL` counts
- focus reason counts
- conflict / degraded scope counts

字段可以追加；不得静默改变已有字段语义。

### 4.5 Step5 输出

`step5_status.json / step5_audit.json` 至少能说明：

- `must_cover_domain`
- `allowed_growth_domain`
- `forbidden_domain`
- `terminal_cut_constraints`
- `fallback_support_strip`
- `bridge_zone`
- `junction_full_road_fill_domain` 是否启用及原因
- `surface_fill_axis_half_width_m`（启用 full-fill 时）
- `surface_section_forward_m / surface_section_backward_m / surface_lateral_limit_m`
- section reference 到 `must_cover / allowed_growth / forbidden / terminal_cut` 的转换说明

Step5 输出只定义约束，不发布最终 polygon。默认以前后 `20m` 横向截面、横向 `20m` 限制组织可通行道路面；负向掩膜包括导流带、hard negative mask、forbidden domain、terminal cut 与不可通行区域。

### 4.6 Step6 输出

`step6_status.json / step6_audit.json` 至少能说明：

- `assembly_state`
- `component_count`
- unit surface 到 case surface 的合并关系（complex / multi 场景）
- `hard_must_cover_ok`
- `b_node_target_covered`
- `forbidden_overlap_area_m2`
- `cut_violation`
- `unexpected_hole_count`
- `final_case_polygon`
- `review_reasons`

Step6 必须在 Step5 约束内生成单一连通结果；cleanup 后必须重新核对 allowed / forbidden / cut / 横向范围。最终 case surface 应保持单一连通，除非存在明确业务 hole。

### 4.7 Step7 输出

`step7_status.json / step7_audit.json` 至少能说明：

- `final_state`
- `reject_reason`
- `reject_reason_detail`
- `swsd_relation_type`
- surface / rejected layer 去向
- `final_review.png`

batch / full-input 发布层：

- `divmerge_virtual_anchor_surface.gpkg`：accepted surface 主层。
- `divmerge_virtual_anchor_surface_rejected.*`：rejected records 与定位信息。
- `divmerge_virtual_anchor_surface_summary.*`：case 级最终状态汇总。
- `divmerge_virtual_anchor_surface_audit.gpkg`：surface 与审计映射。
- `step7_rejected_index.*`：rejected case index。
- `step7_consistency_report.json`：核对 summary、audit、surface、rejected、review PNG、nodes 与 case-level status。

### 4.8 Downstream nodes 输出

`nodes.gpkg`：

- 必须基于输入 `nodes.gpkg` copy-on-write。
- 保留输入整层 geometry 与原字段。
- CRS 保持 `EPSG:3857`。
- 只更新当前 selected / effective case 的 representative node。
- 非 representative node 与未被当前批次选中的 node 不得更新。
- 只正式更新 `is_anchor`。

`nodes_anchor_update_audit.csv` 每条记录至少包含：

- `case_id`
- `representative_node_id`
- `mainnodeid`
- `previous_is_anchor`
- `new_is_anchor`
- `step7_state`
- `reason`

`nodes_anchor_update_audit.json` 至少包含：

- `produced_at`
- `git_sha`
- `input_dataset_id`
- `total_update_count`
- `updated_to_yes_count`
- `updated_to_fail4_count`
- `rows`

一致性要求：

- `nodes.gpkg` 中 representative node 的 `is_anchor` 必须与 Step7 final_state 映射一致。
- audit csv/json 必须与 `nodes.gpkg` 实际更新一致。
- audit csv/json 必须与 `divmerge_virtual_anchor_surface_summary.*` 和 `step7_consistency_report.json` 一致。
- `857993` 必须写为 `fail4`。
- `699870` 当前 baseline 中为 accepted，必须写为 `yes`。

## 5. EntryPoints

当前没有 repo 官方 CLI。

模块内 Python 稳定执行面：

- `run_t04_step14_batch(...)`
- `run_t04_step14_case(...)`
- `run_t04_internal_full_input(...)`

repo 级包装脚本：

- `scripts/t04_run_internal_full_input_8workers.sh`
- `scripts/t04_watch_internal_full_input.sh`
- `scripts/t04_run_internal_full_input_innernet_flat_review.sh`

这些脚本已登记，但不构成新的 CLI 子命令；不得通过本模块文档暗示新增 repo 官方入口。

## 6. Acceptance

当前正式业务冻结基线为 Anchor_2 full baseline：

- `row_count = 23`
- `accepted = 20`
- `rejected = 3`

accepted case：

- `17943587`
- `30434673`
- `505078921`
- `698380`
- `698389`
- `699870`
- `706629`
- `723276`
- `724067`
- `724081`
- `73462878`
- `758784`
- `760213`
- `760256`
- `760984`
- `785671`
- `785675`
- `788824`
- `824002`
- `987998`

rejected case：

- `760598`
- `760936`
- `857993`

验收约束：

- `857993 = rejected` 是人工验收确认后的正确业务结果，不得作为待修成 accepted 的目标。
- Step7 最终状态机只允许 `accepted / rejected`。
- 当前 full baseline 测试必须同时守住 surface 发布层与 downstream nodes 写回：20 个 accepted representative node 为 `yes`，3 个 rejected representative node 为 `fail4`。
- `699870` 是 RCSD-anchored reverse 关键回归样本；当前 full baseline 中为 `accepted`，nodes 写回必须为 `yes`。
- 2026-04-22 selected-case `accepted = 7 / rejected = 1` 仅为 legacy 子集口径，不再作为当前正式 acceptance 数字真相。
