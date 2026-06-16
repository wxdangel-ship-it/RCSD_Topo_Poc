# 003 Phase2 T07 RCSDIntersection Consumable Base

## 日期
- 2026-06-15

## 背景
- T10 relation 级反馈显示，4-case 中存在 38 条 T05 `status = 0` relation 的 `base_id` 无法在 `rcsdnode_out.gpkg` 中作为 `id/mainnodeid` 定位。
- 这些 relation 全部来自 T07 `existing_rcsdintersection_matched`，其 `base_id_candidate` 实际来源是 `RCSDIntersection` 面 ID，而不是已经验证过的 RCSDNode 语义路口 ID。

## 根因
- T07 Step2 在 T05 之前运行，只能发布 RCSDIntersection surface 与 relation evidence。
- T07 Step3 能用 RCSDNode 验证 Step2 surface，但它在 T05 之后运行，无法保护 T05 Phase2 对 T07 Step2 relation evidence 的消费。
- T05 原 direct relation 分支没有先验证 T07 Step2 `base_id_candidate` 是否可被 `rcsdnode_out / rcsdroad_out` 消费。

## 实际变更
- T05 Phase2 消费 T07 `existing_rcsdintersection_matched` 前增加 RCSDNode 可消费校验。
- 若 `base_id_candidate` 已存在于 `rcsdnode_out.id/mainnodeid`，保持原 direct relation。
- 若 `base_id_candidate` 不存在，但 T07 surface 内恰好覆盖 1 个 RCSD 语义节点，则重绑定到该 RCSDNode，audit 记录 `existing_rcsdintersection_surface_1v1_rcsdnode_rebased`。
- 若 T07 surface 内覆盖多个 RCSD 语义节点，保持既有 group existing 处理。
- 若无法证明可消费 RCSDNode，输出失败 relation，audit 记录 `t07_rcsdintersection_base_not_in_rcsdnode_out`。

## 本次边界
- 不基于最近点、固定距离或 T06 成败结果反推 `base_id`。
- 不修改 T07 Step2 输出字段语义。
- 不修改 RCSD 原始拓扑或方向。

## 验证
- 新增 T05 Phase2 单元测试覆盖 surface 1V1 重绑定与不可证明失败。
- 待复跑 T05/T10 测试与 4-case 端到端，确认已成功替换 Segment 不回退。
