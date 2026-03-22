# T01 Architecture Overview

## 当前 accepted architecture
- `raw GeoJSON input`
- `working bootstrap`
- `roundabout preprocessing`
- `Step1`
- `Step2`
- `Step3 refresh`
- `Step4`
- `Step5A`
- `Step5B`
- `Step5C`
- `Step6`

## 核心原则
- official 输入统一为 GeoJSON。
- working node 业务判断统一使用 `grade_2 / kind_2 / working_mainnodeid`。
- working road 正式输出统一使用 `segmentid / sgrade`。
- Step1-Step5C 负责 road-level 双向 Segment 构段。
- Step6 负责 segment-level 聚合、`inner_nodes` 提取与 `segment_error` 审计。

## Step6 集成后的结构
- official runner 先完成 Step5C refresh，得到最终 refreshed `nodes / roads`。
- Step6 不再独立重复读取和分组整套流程，而是在 official runner 中直接复用：
  - Step5 in-memory `nodes / roads`
  - Step5 `mainnode_groups`
  - Step5 `group_to_allowed_road_ids`
- 这样避免了：
  - 重复读取 refreshed `nodes / roads`
  - 重复按 `working_mainnodeid` 分组
  - 重复构建 node-road incidence

## 当前活动 baseline
- 五样例活动基线：
  - `XXXS`
  - `XXXS2`
  - `XXXS3`
  - `XXXS4`
  - `XXXS5`
- freeze compare 当前重点仍是：
  - `validated_pairs`
  - `segment_body_membership`
  - `trunk_membership`
  - refreshed `nodes / roads` 语义 hash
- roads schema 迁移通过 compare 归一化兼容，不把 `s_grade -> sgrade` 误判为业务回退。
