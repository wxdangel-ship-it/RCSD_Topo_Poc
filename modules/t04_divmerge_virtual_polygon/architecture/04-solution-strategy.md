# 04 Solution Strategy

## 总体策略

- 采用 `case_loader -> admission -> local_context -> topology -> event_interpretation -> review_render -> outputs -> batch_runner` 主链。
- Step2/3 主要包装 T02 Stage4 现有内核。
- Step4 在 T02 现有单事件解释逻辑上增加 event-unit 物化与 T03 风格 review 输出。

## 关键策略

### 1. 输入组织

- 采用 T03 风格 case-package loader。
- 在 T04 case-package 中把 `divstripzone.gpkg` 提升为正式输入文件。

### 2. Step1-3

- Step1 使用显式 admission contract。
- Step2 保留 patch-scoped recall window 与 SWSD negative context。
- Step3 保留 member/passthrough/branch/main pair/chain augmentation 语义。

### 3. Step4

- 先显式拆分 event unit，再对每个 event unit 做事实解释。
- simple 默认单单元。
- multi-diverge / multi-merge 使用角度相邻 branch pair。
- complex 使用当前 case 的 member node 粒度；chain augmentation 只补上下文，不直接扩 event-unit population。
- complex 子节点在 Step4 解释阶段继承 complex 128 上下文提示，不因为聚合后 `kind_2=0` 被静默丢弃。
- complex `sub-unit` 在 Step4 内再做一次 `~60m` 局部 scope 收紧，优先只让当前 node 的 throat 邻域参与导流带与参考位置搜索。
- `divstrip_ref` 命中时，review 输出的 reference point materialize 到当前选中的 DivStrip 事实上，并优先贴合 tip / throat 邻域；轴向 `chosen_s` 继续保留为审计标量。
- review 中表达的 selected divstrip 不直接等于原始 component 全面，而是收敛为围绕当前事实点的 localized evidence patch。
- Step4 在接受 forward / reverse 候选前，先做 `branch-middle / throat` gate；不与分支中间区域相关的候选直接判无效，再决定是否进入 reverse tip。
- 连续链 case 若原始 anchor 退化为 seed 占位方框，review 输出把 coarse anchor 重新 materialize 到当前事实证据附近，避免可视审计继续被 seed 占位图误导。
- 最终 review point 必须留在 DriveZone 内；越界候选只允许作为中间诊断，不允许直接落成最终可视结果。
- ownership guard 先看语义冲突：`selected_component_ids` 共用、同一轴且 `Δs<=5m`、localized core segment 重叠；命中即直接升级为 `STEP4_FAIL`。

### 4. Review 输出

- case overview 表达全局语境。
- event-unit PNG 表达当前事件单元的局部解释。
- flat mirror 用于人工平铺质检。

## 当前入口策略

- 不新增 repo 官方 CLI。
- 通过程序内 batch runner 与 pytest/smoke 交付本轮能力。
