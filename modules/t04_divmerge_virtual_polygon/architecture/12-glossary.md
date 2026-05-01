# 12 Glossary

## 业务对象

| 术语 | 定义 |
|---|---|
| `T04` | `t04_divmerge_virtual_polygon` 模块，面向分歧、合流、连续分歧 / 合流与复杂连续链路口的虚拟锚定面生成与发布。 |
| `SWSD` | T04 的 seed / 候选入口，不等于真实分歧 / 合流事实位置。 |
| `RCSD` | 条件性高精度约束；对应事实路口缺失 RCSD 挂接时，不得仅因 RCSD 未覆盖就判定失败。 |
| `主证据` | 真实世界物理空间证据，当前只包括导流带与道路面分叉；RCSD/SWSD/RCSDRoad、历史抽象 node、拓扑召回点和抽象路网代理点都不是主证据。 |
| `导流带主证据` | 由导流带表达真实分歧 / 合流或道路组织切换的主证据；导流带本体同时是负向掩膜，不作为可通行道路面。 |
| `道路面分叉主证据` | 由可通行道路面形态真实分叉、合流或切换表达的主证据。 |
| `RCSD 语义路口` | 与当前 SWSD 路口语义一致的 RCSD 路口：进入道路、退出道路和角度趋势与当前事件对齐；可作为 section reference、抽象路网参考或支撑域约束，不是主证据，不得被称为 Reference Point。 |
| `无 RCSD 语义路口` | 可表示没有 RCSD 路口，也可表示存在 RCSD 数据但不是与当前 SWSD 路口语义一致的路口，例如缺少进入 / 退出道路、只有 RCSDRoad 趋势支持或仅形成弱聚合结果。该状态不等于无 RCSD 数据。 |
| `RCSDRoad fallback` | 无 RCSD 语义路口或需 road fallback 时使用的 RCSDRoad 局部段支撑；可表达与 SWSD 路口对应道路趋势一致的局部 RCSDRoad，但只能覆盖相关局部段，不得沿整条 RCSDRoad 远距离扩张。 |
| `SWSD 语义路口` | SWSD 侧可用于构面的语义路口，可作为 section reference，不是主证据，不得被称为 Reference Point。 |
| `Anchor_2 full baseline` | 历史 23-case frozen / visual gate：`23 case / accepted = 20 / rejected = 3`。 |
| `Anchor_2 30-case surface scenario baseline` | 当前 surface scenario 后续正式扩展 gate：`30 case / accepted = 26 / rejected = 4`，rejected set 为 `760598 / 760936 / 857993 / 607602562`。 |
| `607602562` | Anchor_2 30-case extended baseline 中的 rejected case；当前目视审计口径下不得为提高 accepted count 静默改成 accepted，详细原因以后续 case-level 审计材料为准。 |
| `legacy selected-case baseline` | 2026-04-22 历史子集口径：`accepted = 7 / rejected = 1`，不再作为当前正式 acceptance 数字真相。 |
| `representative node` | 当前 case 的代表节点；downstream `nodes.gpkg` 只更新 selected / effective case 的 representative node。 |

## Step4 术语

| 术语 | 定义 |
|---|---|
| `event unit` | Step4 的事实解释单元；simple 为单单元，multi-diverge / multi-merge 按相邻 branch pair，complex 按 member node。 |
| `unit envelope` | Step4 执行输入边界，至少包含 `unit_population_node_ids / context_augmented_node_ids / event_branch_ids / boundary_branch_ids / preferred_axis_branch_id`。 |
| `unit-local branch pair region` | 当前 event unit 的有序边界 pair `(L, R)` 在 throat / node 起始切片附近形成的局部中间候选空间。 |
| `unit-local structure face` | 当前 pair-local region 内由道路结构面定义的单连通主事实空间。 |
| `selected_candidate_region` | pair-local 候选空间容器，不等同于主证据，也不能替代导流带或道路面分叉事实。 |
| `selected_evidence` | Step4 当前选中的事实证据；只有导流带和道路面分叉可作为主证据来源。 |
| `Reference Point` | 主证据上真实决定分歧、合流或道路形态切换的关键点；没有主证据就没有 Reference Point。 |
| `fact_reference_point` | 与 `event_chosen_s_m` 对齐的事实参考点；必须来自导流带或道路面分叉主证据，不得由 RCSD/SWSD/RCSDRoad 虚构。 |
| `section reference / 截面参考对象` | 用于确定路口面前后横向截面位置的参考对象；可来自 Reference Point、Reference Point + RCSD 语义路口、RCSD 语义路口或 SWSD 语义路口，不等同于 Reference Point。 |
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
| `负向掩膜` | 路口面不得越过或吞入的负向约束，包括导流带、hard negative mask、forbidden domain、terminal cut 与不可通行区域。 |
| `terminal_cut_constraints` | Step5 定义的终端裁切约束，由 Step6 执行。 |
| `final_case_polygon` | Step6 在 Step5 约束内生成的 Case 级单一连通面。 |
| `surface_scenario_type` | T04 主业务场景分类，按主证据与 RCSD/SWSD 支持状态区分六类成功构面场景和 `no_surface_reference` 兜底场景。 |
| `no_surface_reference` | 无主证据、无 RCSD 语义路口、无 RCSDRoad fallback、无 SWSD 语义路口；无 Reference Point、无 section reference，不生成实体路口面。 |
| `accepted` | Step7 最终发布二态之一，表示通过最终业务验收并进入主发布层。 |
| `rejected` | Step7 最终发布二态之一，表示未通过最终业务验收并进入 rejected 层或拒绝索引。 |
| `reject_stub_geometry` | rejected case 的可定位 stub 几何，不是 fake final polygon。 |
| `swsd_relation_type` | Step7 发布字段，当前允许 `covering / partial / offset_fact / unknown`。 |
| `reject_reason` | Step7 主拒绝原因；完整原因串见 `reject_reason_detail`。 |
| `divmerge_virtual_anchor_surface.gpkg` | T04 的正式 surface 几何真值主产物。 |
| `nodes.gpkg` | T04 downstream 状态回写副本，基于输入 node 层 copy-on-write，只更新 representative node 的 `is_anchor`。 |
| `nodes_anchor_update_audit.csv/json` | T04 downstream nodes 写回审计，记录旧值、新值、Step7 state 与 reason，并与 summary / consistency report 保持一致。 |
| `fail4` | T04 downstream `nodes.gpkg` 中表示 `rejected / runtime_failed / formal result missing` 的 `is_anchor` 写回值；不属于 T03 `fail3` 语义。 |

## 执行与治理术语

| 术语 | 定义 |
|---|---|
| `runtime_support` | T04 私有 `_runtime_*` 实现支撑层，承载 runtime contract、geometry helper、kernel base 与 IO helper。 |
| `step4_postprocess` | Step4 主解释后处理层，包括 conflict resolver、road-surface fork binding 与 RCSD anchored reverse。 |
| `full_input_orchestration` | internal full-input 运行编排层，包括 bootstrap、shared layers、case pipeline、observability、perf audit 与 streamed results。 |
| `case-package` | 单 case 输入包，包含 manifest、size report 与该 case 可见的 GPKG 输入层。 |
| `internal full-input` | 一次性加载 full-layer source，发现候选并按 case 直跑 Step1-7 的 T04 私有执行面。 |
| `batch closeout` | 所有 case Step7 完成后的根目录发布阶段，生成 surface、rejected、summary、audit、consistency report 与 downstream nodes 输出。 |
| `visual fingerprint refresh` | 对 `final_review.png` raw scanline fingerprint 的显式基线刷新；仅在已有诊断报告和人工目视确认后允许，用于记录 intentional geometry / review-layer drift，不表示 Step7 accepted/rejected 业务失败。 |
| `repo 官方 CLI` | `src/rcsd_topo_poc/cli.py` 暴露的稳定子命令；T04 当前不新增此类入口。 |
| `repo 级脚本入口` | `scripts/t04_*` 包装脚本，已登记但不构成新的 CLI 子命令。 |
