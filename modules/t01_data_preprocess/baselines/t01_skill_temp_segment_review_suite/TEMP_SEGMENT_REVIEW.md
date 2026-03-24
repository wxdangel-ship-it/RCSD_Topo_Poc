# T01 XXXS 临时 Segment 基线

说明：
- 本目录是临时基线，只关注最终 `roads.geojson` 的 `segmentid -> road_ids`。
- 该基线不覆盖、不替代 accepted baseline。
- 后续每轮迭代都先与这里的快照做最终 Segment 比对。

## 当前锁定样例

- `XXXS`：临时锁定。当前临时基线为 `t01_skill_v1_20260324_xxxs_specbatch_v1`。
- `XXXS2`：通过，当前临时基线与 `t01_skill_v1_20260323_xxxs2_right_turn_boundary_check` 一致。
- `XXXS3`：通过，当前临时基线与 `t01_skill_v1_20260323_xxxs3_current_check_v1` 一致。
- `XXXS4`：通过，当前临时基线与 `t01_skill_v1_20260323_xxxs4_current_check_v1` 一致。
- `XXXS6`：通过，用户已确认 `t01_skill_v1_20260324_xxxs6_specbatch_v1` 的最终 Segment 可接受，现转为锁定样例。
- `XXXS8`：通过，当前临时基线与 `t01_skill_v1_20260323_xxxs8_dupfix_regression_v2` 一致。

## 当前不符合预期

- `XXXS5`
  - 当前临时基线仍等于已知失败输出 `t01_skill_v1_20260324_xxxs5_specbatch_v1`。
  - 用户问题口径：存在旁路分支超过 `50m` 的不接受效果。
- `XXXS7`
  - 当前临时基线仍等于已知失败输出 `t01_skill_v1_20260324_xxxs7_specbatch_v1`。
  - 用户问题口径：存在双向旁路不接受效果，但 `1026500_1026503` 必须保持正确。

## Batch A 2026-03-24 记录

- 已修复 `XXXS8` 小三角场景中宽 trunk option 吞并相邻 road 的 same-stage arbitration 选优偏差。
- 已修复 `XXXS` 在 `Step4` 的 duplicate-road 崩溃；根因是单共享 trunk 且两端均为强锚点的场景被误当成 weak support overlap。
- 当前 Batch A guard 结果：
  - `XXXS2`：`t01_skill_v1_20260324_xxxs2_batchA_guard_v2` 与临时基线最终 Segment 一致。
  - `XXXS3`：`t01_skill_v1_20260324_xxxs3_batchA_guard_v2` 与临时基线最终 Segment 一致。
  - `XXXS4`：`t01_skill_v1_20260324_xxxs4_batchA_guard_v2` 与临时基线最终 Segment 一致。
  - `XXXS6`：`t01_skill_v1_20260324_xxxs6_batchA_guard_v2` 与临时基线最终 Segment 一致。
  - `XXXS8`：`t01_skill_v1_20260324_xxxs8_batchA_guard_v6` 与临时基线最终 Segment 一致。
- `XXXS`：`t01_skill_v1_20260324_xxxs_batchA_guard_v2` 不再崩溃，但仍与临时基线存在 1 处三点组件差异：
  - current：`46336763,616663182` / `502148533`
  - baseline：`46336763,502148533` / `616663182`
  - 该冲突与修订版 baseline 文档语义有关，用户已暂时接受在此基础上继续迭代。

## 后续执行约束

- `PASS_LOCKED` 样例：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS6`
  - `XXXS8`
- `FAIL_TARGET` 样例：
  - `XXXS5`
  - `XXXS7`

后续修复时：

- `PASS_LOCKED` 不允许新增最终 Segment 回退。
- `FAIL_TARGET` 允许变化，但必须记录变化前后差异，并重新评估是否符合人工预期。
