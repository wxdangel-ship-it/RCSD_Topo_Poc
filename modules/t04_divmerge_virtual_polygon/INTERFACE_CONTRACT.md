# T04 - INTERFACE_CONTRACT

## 定位

- 本文件是 `t04_divmerge_virtual_polygon` 的稳定契约面。
- 当前正式范围为：T04 `Step1-4` doc-first formalization 与模块化实现。
- `README.md` 只承担操作者入口职责；长期设计以 `architecture/*` 为准。

## 1. 目标与范围

- 模块 ID：`t04_divmerge_virtual_polygon`
- 目标：
  - 将线程级 T04 Step1-4 需求落入 repo source-of-truth
  - 提供 case-package 输入下可运行的 Step1-4 pipeline
  - 提供 Step4 review PNG / flat mirror / index / summary
- 当前正式范围：
  - case-package loader / preflight
  - Step1 candidate admission
  - Step2 local context
  - Step3 topology skeleton
  - Step4 fact event interpretation
  - case-level / batch-level review outputs
- 明确不在当前正式范围：
  - Step5 geometric support domain
  - Step6 polygon assembly
  - Step7 final acceptance / publishing
  - repo 官方 CLI / shell 入口扩展

## 2. Inputs

### 2.1 必选输入

- case-package 根目录
- 每个 case 当前至少包含：
  - `manifest.json`
  - `size_report.json`
  - `drivezone.gpkg`
  - `divstripzone.gpkg`
  - `nodes.gpkg`
  - `roads.gpkg`
  - `rcsdroad.gpkg`
  - `rcsdnode.gpkg`

### 2.2 输入前提

- 所有空间处理统一到 `EPSG:3857`
- `nodes` 当前至少需具备：
  - `id`
  - `mainnodeid`
  - `has_evd`
  - `is_anchor`
  - `kind` 或 `kind_2`
  - `grade_2`
- `roads / rcsdroad` 当前至少需具备：
  - `id`
  - `snodeid`
  - `enodeid`
  - `direction`
- `rcsdnode` 当前至少需具备：
  - `id`
  - `mainnodeid`

## 3. Stable Business Semantics

### 3.1 Step1 Candidate Admission

- Step1 是准入 gate，不是正确性 gate。
- 当前接受：
  - `kind/kind_2 = 8`
  - `kind/kind_2 = 16`
  - 连续分歧 / 合流聚合语义下的 `kind/kind_2 = 128`
- 准入前提：
  - `has_evd = yes`
  - `is_anchor = no`
- `RCSD` 缺失不影响准入。
- `mainnodeid_out_of_scope` 只表示不属于当前 T04 范围，不得承接后续解释失败。

### 3.2 Step2 Local Context

- seed 只来自当前 case 的 SWSD 语义路口与其关联 road 方向。
- PatchID 用于定位当前 `DriveZone / DivStrip` 局部世界。
- recall window 冻结为：
  - diverge：主干向后 `50m`，分支向前 `200m`
  - merge：主干向前 `50m`，分支向后 `200m`
  - complex：各分支向前/向后 `200m`
- Step2 只定义 SWSD 侧负向上下文；RCSD 负向语义后移。

### 3.3 Step3 Topology Skeleton

- Step3 必须显式给出：
  - `member_node_ids`
  - `passthrough_node_ids`
  - `branch_ids`
  - `main_branch_ids`
  - `input_branch_ids`
  - `output_branch_ids`
  - `is_in_continuous_chain`
  - `related_mainnodeids`
  - `unstable_reasons`
- chain augmentation 边界：
  - 到下一个关联语义路口前停止
  - 单侧不超过 `200m`

### 3.4 Step4 Fact Event Interpretation

- event unit 规则：
  - simple：`1 case = 1 event unit`
  - multi-diverge / multi-merge：角度相邻两条道路 = `1 event unit`
  - complex：`1 node = 1 event unit`
  - complex 的 unit population 来自当前 case 的语义 member nodes；`augmented_member_node_ids` 只用于连续链上下文，不自动扩成 event units。
- 不同 event unit 之间不得共用同一事实依据核心段、同一参考位置、同一导流带 component。
- 事实位置链路至少表达：
  - `event_anchor_geometry`
  - `selected DivStrip component`
  - `event axis`
  - `scan origin`
  - `crossline scan`
  - `DivStrip ref s / DriveZone split s`
  - `event_reference_point`
- `divstrip_ref` 命中时，`event_reference_point` 的 review materialization 必须落在当前选中的 DivStrip 事实上，且优先物化到 tip / throat 邻域；`event_chosen_s_m` 继续作为轴向标量审计值保留。
- review 中表达的 `selected DivStrip` 是当前事实依据的 localized evidence patch，不得继续把整块无关导流带面作为单一事实依据涂出。
- Step4 在最终接受 `event_reference_point` 前，必须对当前候选做 `branch-middle / throat` 合法性 gate；若候选与当前分歧 / 合流分支中间区域无实际关系，不得直接放行为有效事实位置。
- 连续链 case 若原始 anchor 仍停留在 seed 占位区且不命中当前选中的 DivStrip，T04 必须把 review 用 `event_anchor_geometry` materialize 为围绕当前事实证据的 coarse anchor zone，而不是继续输出固定 seed 方框。
- `event_reference_point` 不得落到 `DriveZone` 外；若轴向候选越界，T04 必须把 review point 收敛回当前道路面内的事实证据位置，并留痕。
- Step4 只负责正向 RCSD 选取与一致性校验，不定义 RCSD 最终负向语义。
- `reverse tip` 只允许在 forward 缺失或 forward 被 `branch-middle / throat` gate 判为无效时作为受控重试，且必须留痕。
- 对 complex `1 node = 1 event unit` 子单元，Step4 解释阶段必须把 evidence search scope 收紧到当前 representative node 的局部 throat 邻域，不得继续共享整条 complex 走廊。
- ownership guard 的主判断必须以语义冲突为先：
  - 共用同一 `selected_component_ids`
  - 同一 `event_axis_branch_id` 且 `|Δevent_chosen_s_m| <= 5m`
  - 共用同一 localized evidence core segment
- 上述任一冲突命中时，T04 必须上浮为 `STEP4_FAIL`，不得仅以 `REVIEW` 吞掉。

## 4. Outputs

### 4.1 Run Root 固定输出

- `preflight.json`
- `summary.json`
- `step4_review_index.csv`
- `step4_review_summary.json`
- `step4_review_flat/`
- `cases/`

### 4.2 单 case 固定输出

- `step1_status.json`
- `case_meta.json`
- `step3_status.json`
- `step3_audit.json`
- `step4_event_interpretation.json`
- `step4_event_evidence.gpkg`
- `step4_audit.json`
- `step4_review_overview.png`
- `event_units/<event_unit_id>/step4_review.png`

### 4.3 review index / summary

- `step4_review_index.csv` 至少包含：
  - `sequence_no`
  - `case_id`
  - `event_unit_id`
  - `event_type`
  - `review_state`
  - `evidence_source`
  - `position_source`
  - `reverse_tip_used`
  - `image_name`
  - `image_path`
- `step4_review_summary.json` 至少包含：
  - `total_case_count`
  - `total_event_unit_count`
  - `STEP4_OK`
  - `STEP4_REVIEW`
  - `STEP4_FAIL`
  - `cases_with_multiple_event_units`

## 5. EntryPoints

### 5.1 当前正式入口状态

- 当前 **无 repo 官方 CLI**。
- 当前模块正式执行面为程序内 runner：
  - `run_t04_step14_batch(...)`
  - `run_t04_step14_case(...)`
- 本轮不更新 `entrypoint-registry.md`。

## 6. Acceptance

1. repo 已存在 T04 正式模块文档面。
2. Step1-4 可对 case-package 运行并产出稳定文件集。
3. Step4 review overview / event-unit png / flat mirror / index / summary 可直接人工检查。
4. 本轮未进入 Step5-7，也未新增 repo 官方入口。
