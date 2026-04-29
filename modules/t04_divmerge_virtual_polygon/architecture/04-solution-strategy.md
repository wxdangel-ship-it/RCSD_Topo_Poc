# 04 Solution Strategy

## 1. 总体策略

T04 采用“业务主链 + 工程编排层”的分工：

- 业务主链由 `admission -> local_context -> topology -> event_units -> event_interpretation -> support_domain -> polygon_assembly -> final_publish` 承载。
- 工程编排层由 `outputs -> batch_runner -> internal_full_input_runner -> full_input_* -> nodes_publish` 承载。
- Step1-7 的业务语义不依赖 T02/T03 运行时代码；T02/T03 只作为历史经验和产物组织形式参考。

本文件表达 Step1-7 的业务目标、输入、输出和实现策略。稳定文件名、字段、枚举和值域以 `INTERFACE_CONTRACT.md` 为准；回归门槛和冻结 baseline 以 `architecture/10-quality-requirements.md` 为准。

## 2. Step1 Candidate Admission

业务目标：

- 判断给定 representative node 是否属于 T04 当前正式处理范围。
- 将不属于 T04 的候选在入口处明确拒绝，避免后续步骤用几何现象反推字段语义。

主要输入：

- representative node。
- group nodes。
- node 字段中的 `mainnodeid / has_evd / is_anchor / kind / kind_2`。

主要输出：

- `step1_status.json`。
- `case_meta.json`。

实现策略：

- 由 `admission.py` 的 `build_step1_admission(...)` 执行准入 gate。
- 当前支持 `kind_2 in {8, 16, 128}` 或 `kind = 128` 的分歧 / 合流 / continuous complex 候选。
- `has_evd` 与 `is_anchor` 用于确认候选仍需 T04 生成虚拟锚定结果。

边界：

- Step1 不做事实解释、拓扑裁决、polygon 判定或 RCSD 成败判断。
- RCSD 缺失不在 Step1 直接阻断；RCSD 语义在 Step4 及后续审计链路中解释。

## 3. Step2 High-recall Local Context

业务目标：

- 围绕已准入候选构建高召回 local world，让 Step3/4 有足够道路、节点与 SWSD negative context。
- 在保持召回的同时，把上下文限定在 case-local patch 内。

主要输入：

- Step1 admission 结果。
- case-package 或 full-input 收集得到的 `nodes / roads / drivezone / divstripzone / rcsdroad / rcsdnode`。

主要输出：

- Step2 local context 对象。
- local roads、node group、SWSD negative context、RCSD raw context。

实现策略：

- 由 `local_context.py` 的 `build_step2_local_context(...)` 组织 patch-scoped local world。
- diverge 类场景以前向 branch 为主、merge 类场景以反向 branch 为主组织召回窗口。
- continuous / complex 场景保留更宽的双向局部召回，给 Step3 的 chain coordination 留出空间。

边界：

- Step2 只组织上下文，不生成最终候选空间。
- Step2 的 SWSD negative context 是负向提示；正向 RCSD 支持必须后移到 Step4。

## 4. Step3 Topology Skeleton

业务目标：

- 把候选 case 的局部拓扑拆成 case coordination skeleton 与 unit-level executable skeleton。
- 对 continuous / complex 场景保持 branch 语义连续，避免把 same-case sibling internal node 误切成断裂 pair。

主要输入：

- Step2 local context。
- local roads、member nodes、passthrough nodes、candidate branch seeds。

主要输出：

- 顶层 `step3_status.json / step3_audit.json`。
- event-unit 级 `event_units/<event_unit_id>/step3_status.json`。

实现策略：

- 由 `topology.py` 的 `build_step3_topology(...)` 生成 skeleton。
- 顶层 case coordination skeleton 负责 member population、chain context、event-unit population 和 case overview。
- event-unit executable skeleton 才是 Step4 的执行输入，包含 `event_branch_ids / boundary_branch_ids / preferred_axis_branch_id` 等 unit-local 信息。
- continuous complex / merge 场景下，unit population 仍锚定当前 representative node；但如果 same-case sibling internal node 之后仍保持同一 `(L, R)` pair-middle 语义，executable branch 允许沿合法 continuation 延续，硬上限为 `200m`。
- sibling node 上的 continuation 选择顺序固定为：先对齐 `external associated road`，再确认 `L' / R'` 中间没有其他 road，保持左右顺序，最后才用最小转角做 tie-breaker。
- multi-diverge / multi-merge 必须保留 `ordered_side_branch_ids / adjacent_side_pairs / unit_boundary_branch_ids / preferred_axis_branch_id`，不得把多方向过度压扁成单 pair。
- simple 二分歧 / 二合流可以保留 trunk / event-side 粗框架，但 Step3 不承担 DivStrip 事实、tip/throat 或 final reference 的事实定位。

边界：

- `augmented_member_node_ids` 只作为 chain context hint，不直接冒充 Step4 可执行 population。
- local truncation 只限制扫描方向，不得把已经合法延续的 boundary branch membership 裁回 seed road。
- Step3 不选择 Step4 主证据，也不生成最终 polygon。

## 5. Step4 Fact Event Interpretation

业务目标：

- 以 event unit 为单位解释局部事实事件，确定主证据、事实参考点、候选空间、正向 RCSD 支持与受控恢复路径。
- 为 Step5 提供可解释的几何与语义输入，而不是直接发布面。

主要输入：

- Step3 event-unit executable skeleton。
- DivStripZone / DriveZone / local roads / RCSDRoad / RCSDNode。
- Step2/3 形成的 branch、axis、pair-local context。

主要输出：

- `step4_status.json / step4_audit.json`。
- `event_units/<event_unit_id>/step4_status.json`。
- `event_units/<event_unit_id>/step4_candidates.json`。
- event-unit review PNG 与 flat mirror。

实现策略：

- 由 `event_units.py` 先物化 event unit。
- 由 `event_interpretation.py` 作为 facade / composition root，调用私有 Step4 core、selection、branch variant、unit preparation、runtime support 与 postprocess 模块。
- Step4 采用 branch-first + pair-local 策略：先确定当前 unit 的有序边界 pair `(L, R)`，再在合法 continuation 内形成 `pair_local_region / structure_face / selected_candidate_region`。
- `selected_candidate_region` 表示合法候选空间容器；`selected_evidence`、`localized_evidence_core_geometry` 与 `fact_reference_point` 才承担主事实证据和位置语义。
- 正向 RCSD 只在当前 pair-local 语义框架内选择，不回退到 case-level RCSD 世界补证据。
- reverse、road-surface fork、SWSD/RCSD junction window 与 `rcsd_anchored_reverse` 是受控恢复路径，由 `step4_postprocess` 归口。
- complex / multi 的 local throat gate 必须使用当前 unit 的 `boundary_branch_ids`，不得静默退回 case-level main pair；若 throat pair 无法有效形成，必须写出 `degraded_scope_reason`。
- reverse tip 只允许在 forward missing、forward 被 local throat 拒绝、forward 被 same-axis prior conflict 拒绝时作为证据查找重试；它不得扩大、补全或反向追溯当前 `pair-local region`。
- ownership 几何分为 `selected_component_union_geometry / localized_evidence_core_geometry / coarse_anchor_zone_geometry`；component ownership、core ownership 和 review 粗表达不得混用。
- 点位语义分为 `fact_reference_point / review_materialized_point`；`fact_reference_point` 与 `event_chosen_s_m` 对齐，`review_materialized_point` 只服务 PNG 表达。

边界：

- Step4 可产生 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL` 内部审计态，但这些状态不得进入 Step7 最终状态机。
- `STEP4_REVIEW` 在当前 full baseline 中是可解释的 soft-degrade 常态，不表示要把 `857993` 追修成 accepted。
- candidate pruning 采用硬排除与显式 degraded state，不允许静默复用已被排除的 component。
- Step4 不生成最终 polygon，也不决定最终发布层。

## 6. Step5 Geometric Support Domain

业务目标：

- 把 Step4 的事实解释转成 Step6 可消费的几何支撑域和硬约束。
- 明确哪些区域必须覆盖、哪些区域可以增长、哪些区域禁止进入、哪里必须切断。

主要输入：

- Step4 unit / case 结果。
- `selected_evidence`、`fact_reference_point`、正向 RCSD、DriveZone、road-surface fork 与 fallback support strip。

主要输出：

- `step5_status.json`。
- `step5_audit.json`。
- Unit / Case 两级 `must_cover_domain / allowed_growth_domain / forbidden_domain / terminal_cut_constraints`。

实现策略：

- 由 `support_domain.py` 的 `build_step5_support_domain(...)` 构建支撑域。
- 对主证据充分的单元，围绕 evidence core、fact reference patch 与 required RCSD 组织 must-cover。
- 对证据弱但可解释的场景，使用 fallback support strip、bridge zone 或 junction window / full-fill domain，并显式审计启用原因。
- 对 `rcsd_anchored_reverse` 且同时具备 Reference Point 与 required RCSDNode 的场景，在 DriveZone 内按语义主轴构造 `junction_full_road_fill_domain`，并受 forbidden masks 与 terminal cuts 硬约束。

边界：

- Step5 只定义约束，不直接生成最终面。
- 不得用 review point 伪造几何真值；缺少正向 node 时必须退回已定义的道路末端约束或 fallback 支撑规则。

## 7. Step6 Polygon Assembly

业务目标：

- 在 Step5 约束内生成 case 级单一连通最终面。
- 保证结果不突破 `allowed_growth_domain`，不进入 `forbidden_domain`，不违反 terminal cut。

主要输入：

- Step5 Case 支撑域。
- must-cover seeds、allowed / forbidden masks、terminal cut constraints。

主要输出：

- `step6_status.json`。
- `step6_audit.json`。
- `final_case_polygon`。

实现策略：

- 由 `polygon_assembly.py` 的 `build_step6_polygon_assembly(...)` 执行。
- 采用 raster-first 单连通组装，再回到矢量 polygon 做连通性、洞、cut、forbidden overlap 检查。
- 允许业务 hole；不允许算法 hole 或无审计 cleanup。

边界：

- Step6 不放宽 Step5 的硬边界。
- 任何 polygon cleanup 都必须重新套用 allowed / forbidden / cut 约束。

## 8. Step7 Final Acceptance And Publishing

业务目标：

- 对 Step6 结果做最终业务验收，压缩为 `accepted / rejected` 二态，并发布正式 surface、rejected、summary、audit 与 review 工件。
- 在 closeout 阶段补齐 downstream `nodes.gpkg` 状态回写。

主要输入：

- Step6 result。
- Step1-6 status / audit。
- case-package 或 full-input 的原始 nodes layer。

主要输出：

- case 级 `step7_status.json / step7_audit.json / final_review.png`。
- batch / full-input 级 `divmerge_virtual_anchor_surface.gpkg`、rejected layer、summary、audit、`step7_rejected_index.*`、`step7_consistency_report.json`。
- downstream `nodes.gpkg`、`nodes_anchor_update_audit.csv/json`。

实现策略：

- 由 `final_publish.py` 的 Step7 artifact / batch outputs 逻辑发布 surface 主成果。
- 由 `nodes_publish.py` 在 Step7 closeout 后消费最终状态，基于输入 `nodes.gpkg` 做 copy-on-write，只更新当前 selected / effective case 的 representative node `is_anchor`。
- nodes 写回固定为 `accepted -> yes`，`rejected / runtime_failed / formal result missing -> fail4`。

边界：

- `divmerge_virtual_anchor_surface.gpkg` 是 T04 几何真值；`nodes.gpkg` 是 downstream 状态索引层。
- Step7 不新增最终 `review / review_required` 状态；不确定性只留在审计材料中。

## 9. 工程编排层

case-package batch：

- `batch_runner.py` 负责 preflight、per-case orchestration、Step4 second-pass / postprocess、Step5-7 closeout、summary、failure doc、nodes 输出与 consistency report。
- `outputs.py` 负责 case 级文件、flat mirror、index 与 summary 写出。

internal full-input：

- `internal_full_input_runner.py` 是 full-input 主 runner。
- `full_input_bootstrap.py` 负责路径校验、preflight、candidate artifacts。
- `full_input_shared_layers.py` 负责 full-layer preload、spatial index、candidate discovery 与 per-case feature collection。
- `full_input_case_pipeline.py` 负责由 shared layers 直跑单 case Step1-7。
- `full_input_observability.py`、`full_input_perf_audit.py`、`full_input_streamed_results.py` 负责进度、失败、性能、terminal records 与最终视觉审计。

## 10. Source-of-truth 分工

- `INTERFACE_CONTRACT.md`：稳定接口、输入输出、状态机、枚举和值域。
- `architecture/04-solution-strategy.md`：Step1-7 业务目标和实现策略。
- `architecture/05-building-block-view.md`：代码 building blocks 与职责边界。
- `architecture/10-quality-requirements.md`：正确性、可审计性、回归和 baseline gate。
- `architecture/11-risks-and-technical-debt.md`：剩余风险与技术债。
- `architecture/12-glossary.md`：术语表。
