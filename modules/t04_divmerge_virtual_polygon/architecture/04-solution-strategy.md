# 04 Solution Strategy

## 总体策略

- 采用 `case_loader -> admission -> local_context -> topology -> event_interpretation -> support_domain -> polygon_assembly -> final_publish -> review_render -> outputs -> batch_runner` 主链。
- Step2/3 参考 T02 Stage4 的既有语义，但正式运行时内核在 T04 私有实现中落地。
- Step4 参考 T02 的单事件解释思路并增加 event-unit 物化与 T03 风格 review 输出，但正式执行不得回调 T02 模块代码。
- Step5/6/7 参考 T03 的产物风格、批量审计与汇总组织方式，但正式执行不得直接 import / 调用 / 硬拷贝 T03 模块代码。

## 关键策略

### 1. 输入组织

- 采用 T03 风格 case-package loader。
- 在 T04 case-package 中把 `divstripzone.gpkg` 提升为正式输入文件。

### 2. Step1-3

- Step1 使用显式 admission contract。
- Step2 保留 patch-scoped recall window 与 SWSD negative context。
- Step3 保留 member/passthrough/branch/main pair/chain augmentation 语义，但正式拆成两层：
  - `case coordination skeleton`
  - `unit-level executable skeleton`
- `case coordination skeleton` 只负责：
  - member population
  - continuous chain coordination
  - event-unit population
  - case overview / case-level audit
- `unit-level executable skeleton` 才是 Step4 的可执行输入；complex `1 node = 1 unit` 时，Step4 仍只消费当前 representative node 为锚点的 unit-local skeleton，但该 skeleton 的 branch 语义必须保持拓扑语义连续，不能因为穿过 same-case sibling internal node 就被机械切断。
- `augmented_member_node_ids` 只保留为 case 外 `chain_context_hint`，不再直接冒充 Step4 的可执行 population；same-case sibling internal node 的 branch continuation 必须通过 unit-local executable branches 显式表达，不能混进 `context_augmented_node_ids`。

### 3. Step4

- Step4 采用 `branch-first + pair-local` 解释策略：先拆 event unit，再在 unit-local envelope 内解释事实事件。
- Step4 的稳定业务规则、字段、枚举与审计输出以 `INTERFACE_CONTRACT.md §3.4` 为唯一契约面；本节不平行重述候选空间、RCSD A/B/C、ownership guard、reverse/window 与 second-pass 的完整规则。
- 架构策略只保留以下设计意图：
  - 先以 Step3 的 `unit-level executable skeleton` 建立 `unit envelope`，再进入解释内核。
  - 候选空间必须保持 unit-local，不退回 case-level corridor。
  - `selected_candidate_region` 是 pair-local 容器，`selected_evidence` 才是主事实证据。
  - 正向 RCSD 只在当前 pair-local 语义框架内选择，不回退到更大的 case 级 RCSD 世界补证据。
  - reverse、road-surface fork、SWSD/RCSD junction window 与 `rcsd_anchored_reverse` 都是当前 pair-local 语义下的受控恢复路径，不改变 Step4 主规则边界。
  - Step4 内部可保留 `STEP4_OK / STEP4_REVIEW / STEP4_FAIL` 审计态，但 Step7 最终发布仍只允许 `accepted / rejected`。
- 当前 full baseline 中 `STEP4_REVIEW` 是已解释的内部 soft-degrade 常态，不是最终发布第三态，也不是追求 `857993=accepted` 的理由。
- second-pass 后处理由 `step4_final_conflict_resolver`、`step4_road_surface_fork_binding`、`step4_rcsd_anchored_reverse` 等模块承担；其职责归入 `architecture/05-building-block-view.md` 的 `step4_postprocess` building block。

### 4. Review 输出

- case overview 表达全局语境。
- event-unit PNG 表达当前事件单元的局部解释。
- 顶层 `step3_status.json` 只表达 `case coordination skeleton`。
- `event_units/<event_unit_id>/step3_status.json` 表达当前 unit 的 `unit-level executable skeleton`。
- `event_units/<event_unit_id>/step4_candidates.json` 表达 pair-local region、selected candidate 与 alternative candidates。
- flat mirror 用于人工平铺质检。

### 5. Step5-7

- `support_domain`
  - 以 Step4 主证据、`fact_reference_point`、正向 RCSD 结果与局部道路面构建 Unit / Case 两级约束层
  - 只定义 `must_cover / allowed_growth / forbidden / terminal_cut`，不生成最终 polygon
  - 对 `rcsd_anchored_reverse` 且同时具备 `Reference Point + required_rcsd_node` 的路口面，必须额外构建 `junction_full_road_fill_domain`：以 Reference Point 与 RCSDNode 定义的语义主轴为中心，纵向只保留两端各 `20m` terminal window，横向单侧不超过 `20m`，再与 DriveZone 道路面和 forbidden masks 共同约束；`terminal_support_corridor_geometry` 在此场景只作为支撑与审计对象，不应成为最终铺面的主范围。
- `polygon_assembly`
  - 在 Step5 约束内以 `raster-first` 方式组装单一连通面
  - 不得突破 `allowed / forbidden / terminal_cut`
- `final_publish`
  - 基于 Step6 结果做最终验收、二态裁决与发布
  - 输出 `divmerge_virtual_anchor_surface` 主层、rejected 层、summary 层与 audit 层

## 当前入口策略

- 不新增 repo 官方 CLI。
- `Step1-4` 继续通过程序内 batch runner 与 pytest/smoke 交付既有能力。
- `Step5-7` 后续实现仍维持模块私有 runner / batch orchestration，不提升为 repo 官方 CLI。
