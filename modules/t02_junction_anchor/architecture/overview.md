# T02 Architecture Overview

## 1. T02 在 RCSD 流程中的位置

- T01 负责上游双向 Segment 相关事实整理，当前已提供 `segment` 与 `nodes` 事实基础。
- T02 在其后继续处理 Segment 相关路口，但当前不直接做最终锚定。
- T02 当前阶段结构为：
  - Stage1：`DriveZone / has_evd gate`
  - Stage2：anchoring 主逻辑（占位）

## 2. 为什么先做 Stage1 gate

- 先把“是否有有效资料”与“如何做最终锚定”拆开，可避免把资料缺失问题混进锚定算法。
- Stage1 先固化 gate，可为后续 Stage2 提供更清晰的输入边界、失败口径与审计基础。
- Stage1 允许误伤、不做捞回，目的就是先建立保守、可追溯的资料存在性门禁。

## 3. Stage1 的最小闭环

- 输入：
  - T01 `segment`
  - T01 `nodes`
  - `DriveZone.geojson`
- 字段口径：
  - `segment.id / pair_nodes / junc_nodes`
  - `nodes.id / mainnodeid`
  - `s_grade` 逻辑字段兼容 `s_grade / sgrade`
- 处理：
  - 从 `pair_nodes / junc_nodes` 提取相关路口
  - 做单 `segment` 去重
  - 空目标路口 `segment` 直接记为 `has_evd = no` 并留痕 `reason = no_target_junctions`
  - 按路口组装规则找到 node 组
  - 在 `EPSG:3857` 下完成 `nodes` 与 `DriveZone` 的空间关系判断
  - 基于 `DriveZone` 做 `has_evd` 判定
- 输出：
  - `nodes.has_evd`
  - `segment.has_evd`
  - `summary`
  - 审计留痕

## 4. Stage2 当前只保留占位

- Stage2 将承担真正的路口锚定。
- Stage2 未来会涉及：
  - 锚定结果
  - 候选机制
  - 概率 / 置信度
  - 更复杂的误伤回收
- 上述内容目前都未定型，因此不提前下沉到 Stage1 契约中。

## 5. 当前结构风险

- 环岛代表 node 当前仍是 T01 逻辑继承，不是 T02 独立闭环。
- 缺失 CRS 的修复策略仍依赖上游数据质量或后续任务书明确。
