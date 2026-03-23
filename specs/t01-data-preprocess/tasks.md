# T01 任务清单

## 已接受基础
- [x] Step1 只输出 `pair_candidates`
- [x] Step2 输出 `validated / rejected / trunk / segment_body / step3_residual`
- [x] Step4 / Step5A / Step5B / Step5C accepted 语义继续保持
- [x] Step6 已正式纳入 official end-to-end
- [x] 双向道路前置过滤仍保持：
  - node: `closed_con in {2,3}`
  - road: `road_kind != 1`
- [x] 50m gates 仍保持共享：
  - `MAX_DUAL_CARRIAGEWAY_SEPARATION_M = 50.0`
  - `MAX_SIDE_ACCESS_DISTANCE_M = 50.0`

## 本轮任务
- [x] 在 Step2 中新增 same-stage pair arbitration 阶段
- [x] 识别合法 pair 的 pair-level conflict graph 与 conflict components
- [x] 在 conflict component 内补充组合仲裁，不再由 pair 固定顺序直接决定最终保留
- [x] 输出 `pair_conflict_table.csv`
- [x] 输出 `pair_conflict_components.json`
- [x] 输出 `pair_arbitration_table.csv`
- [x] 输出 `corridor_conflict_roads.geojson`
- [x] 输出 `validated_pairs_final.csv`
- [x] 输出 `target_conflict_audit_xxxs7.json`

## 定点验收
- [x] `XXXS7`：
  - `S2:1019883__1026500`
  - `S2:1026500__1026503`
  - `500588029`
  已进入同阶段仲裁审计
- [x] `XXXS7` corridor 归属不再由 pair 顺序直接决定
- [x] `XXXS7` 当前实现已将 `500588029` 归属给 `S2:1026500__1026503`

## 回归要求
- [x] Step2 单 pair 合法性前半段保持不变
- [x] XXXS freeze compare 已重新执行
- [x] 若存在差异，仅输出 compare 结果，不自动更新 freeze baseline
