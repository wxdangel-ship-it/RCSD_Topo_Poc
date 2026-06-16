# 2026-06-15 Phase2 T10 side-group endpoint candidates

## 背景

T06 Step2 能识别双向 Segment 在 RCSD 图中只存在单向通路的失败，并通过 T10 输出 `t10_upstream_side_group_endpoint_candidates.*`。这类反馈的正确消费位置不是 T06 Step3，而是回到 T03/T04/T05 的虚拟路口聚合链路。

## 变更

- T05 Phase2 runner 新增可选输入 `t10_side_group_endpoint_candidate_path`。
- `scripts/t05_innernet_experiment.py` 新增参数 `--t10-side-group-endpoint-candidates`。
- T05 evidence classifier 新增来源 `T10_SIDE_GROUP`。
- `T10_SIDE_GROUP` 只作为补充证据：
  - 同一 SWSD `target_id` 已有 T07/T03/T04/T02 成功 relation 时，可把 endpoint 侧 `candidate_rcsdnode_ids` 加入 `group_existing_rcsd_nodes`；
  - 若同一 target 只有 T10 endpoint candidate，不能单独创建成功 relation。

## 边界

- 不消费 segment 级 `t10_upstream_side_group_candidates.*`，避免把 Segment 两端 RCSD node 错误聚合为同一路口。
- 不修正 RCSD road 方向性。
- 不回改 T03/T04/T07 原始 relation evidence。
- 不改变 T06 Step3 替换计划。

该改动让 T06 发现的侧聚合问题能够在二次迭代中回到 T05 junctionization 关系发布阶段处理，同时保证当前已成功替换 Segment 默认不回退。

## 2026-06-15 回归修正

- 修正 T05 Phase2 `choose_actionable_decisions` 的回落分支：若候选集中只有 `T10_SIDE_GROUP` 成功项，不再把该项作为普通 fallback relation 返回。
- 保留两个合法消费场景：`T10_SIDE_GROUP` 可补充同一 `target_id` 已有的 T07/T03/T04/T02 成功 relation；若同时存在 T03/T04 road-only split 决策，优先执行 road-only split，不被 T10 反馈遮蔽。
- `991176` 回归验证中，回灌 endpoint candidate 后 replacement plan 与最终 replaced Segment 均无移除项，新增 `1001581_1001583`、`504597284_603597212`；剩余 `T10_SIDE_GROUP` 单独候选继续留在 problem registry，不在 T05 单独发布 relation。

## 2026-06-15 road-only split supplement

- `991176` 中 `509987509_603597212` 暴露出一种合法前置场景：SWSD endpoint 先由 T03 road-only split 在 T05 生成新的 RCSDNode，再需要把该新节点与 T10 endpoint candidate 中的既有 RCSDNode 归为同一个 RCSD 语义路口。
- T05 Phase2 调整为：当同一 target 同时存在 T03/T04 road-only split 决策与 `T10_SIDE_GROUP` endpoint candidate 时，保留 road-only split 作为主决策；split 成功后，将新生成或 endpoint-reuse 的 RCSDNode 与 side-group 额外节点做 copy-on-write `mainnodeid` grouping。
- 该逻辑不允许 T10 side-group 覆盖 road-only split，也不允许 T10 side-group 单独创建 relation；若 road-only split 失败，仍按 road-only split 失败审计输出。
- 该修正把 T06 发现的端点侧聚合问题前置回 T05 junctionization，而不是在 T06 Step3 通过替换白名单兜底。
