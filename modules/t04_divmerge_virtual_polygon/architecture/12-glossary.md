# 12 Glossary

## 业务对象

| 术语 | 定义 |
|---|---|
| `T04` | `t04_divmerge_virtual_polygon` 模块，面向分歧、合流、连续分歧 / 合流与复杂连续链路口的虚拟锚定面生成与发布。 |
| `SWSD` | T04 的 seed / 候选入口，不等于真实分歧 / 合流事实位置。 |
| `RCSD` | 条件性高精度约束；对应事实路口缺失 RCSD 挂接时，不得仅因 RCSD 未覆盖就判定失败。 |
| `Anchor_2 full baseline` | 当前冻结业务基线：`23 case / accepted = 20 / rejected = 3`。 |
| `legacy selected-case baseline` | 2026-04-22 历史子集口径：`accepted = 7 / rejected = 1`，不再作为当前正式 acceptance 数字真相。 |

## Step4 术语

| 术语 | 定义 |
|---|---|
| `event unit` | Step4 的事实解释单元；simple 为单单元，multi-diverge / multi-merge 按相邻 branch pair，complex 按 member node。 |
| `unit envelope` | Step4 执行输入边界，至少包含 `unit_population_node_ids / context_augmented_node_ids / event_branch_ids / boundary_branch_ids / preferred_axis_branch_id`。 |
| `unit-local branch pair region` | 当前 event unit 的有序边界 pair `(L, R)` 在 throat / node 起始切片附近形成的局部中间候选空间。 |
| `unit-local structure face` | 当前 pair-local region 内由道路结构面定义的单连通主事实空间。 |
| `selected_candidate_region` | pair-local 候选空间容器，不等同于主事实证据。 |
| `selected_evidence` | Step4 当前选中的主事实证据。 |
| `fact_reference_point` | 与 `event_chosen_s_m` 对齐的事实参考点，表达 formation-side / throat-side reference。 |
| `review_materialized_point` | 仅用于 PNG 表达的可视化落点，不替代 `fact_reference_point`。 |
| `localized_evidence_core_geometry` | 围绕当前事实点收敛出的局部核心证据几何。 |
| `coarse_anchor_zone_geometry` | 审计与 review 用粗锚定区，不代理 component ownership。 |
| `STEP4_REVIEW` | Step4 内部审计态；在当前 full baseline 中可以是 soft-degrade 常态，不是 Step7 最终状态。 |

## Step5-7 术语

| 术语 | 定义 |
|---|---|
| `must_cover_domain` | Step5 定义的硬覆盖域，Step6 最终面必须覆盖。 |
| `allowed_growth_domain` | Step5 定义的允许增长域，Step6 不得扩出该域。 |
| `forbidden_domain` | Step5 定义的禁止域，包含 `1m` hard negative mask 等。 |
| `terminal_cut_constraints` | Step5 定义的终端裁切约束，由 Step6 执行。 |
| `final_case_polygon` | Step6 在 Step5 约束内生成的 Case 级单一连通面。 |
| `accepted` | Step7 最终发布二态之一，表示通过最终业务验收并进入主发布层。 |
| `rejected` | Step7 最终发布二态之一，表示未通过最终业务验收并进入 rejected 层或拒绝索引。 |
| `reject_stub_geometry` | rejected case 的可定位 stub 几何，不是 fake final polygon。 |
| `swsd_relation_type` | Step7 发布字段，当前允许 `covering / partial / offset_fact / unknown`。 |
| `reject_reason` | Step7 主拒绝原因；完整原因串见 `reject_reason_detail`。 |

## 执行与治理术语

| 术语 | 定义 |
|---|---|
| `runtime_support` | T04 私有 `_runtime_*` 实现支撑层，承载 runtime contract、geometry helper、kernel base 与 IO helper。 |
| `step4_postprocess` | Step4 主解释后处理层，包括 conflict resolver、road-surface fork binding 与 RCSD anchored reverse。 |
| `full_input_orchestration` | internal full-input 运行编排层，包括 bootstrap、shared layers、case pipeline、observability、perf audit 与 streamed results。 |
| `repo 官方 CLI` | `src/rcsd_topo_poc/cli.py` 暴露的稳定子命令；T04 当前不新增此类入口。 |
| `repo 级脚本入口` | `scripts/t04_*` 包装脚本，已登记但不构成新的 CLI 子命令。 |
