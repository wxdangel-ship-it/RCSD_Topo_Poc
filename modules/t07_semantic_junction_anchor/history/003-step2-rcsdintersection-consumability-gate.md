# 003 - Step2 RCSDIntersection 可消费性门禁

## 时间

2026-06-15

## 背景

T10 Case `991176` 中，部分 `kind_2=4` SWSD 语义路口在 T07 Step2 命中 `RCSDIntersection` 后被写为 `is_anchor=yes`，但后续 T07 Step3 / T05 审计发现该 `RCSDIntersection` 面内没有可用的 RCSDNode 语义路口，T05 无法把该锚定落实为可被 T06 消费的 `base_id`。

这会导致两类后果：

- T03/T04 因该 SWSD 语义路口已被 T07 标为 anchored，无法再按虚拟路口候选处理。
- T05 若继续消费该 RCSDIntersection id，会形成 `base_id` 不在 RCSDNode 图中的错误关系。

## 根因

T07 Step2 原逻辑只判断 SWSD 语义路口是否命中 `RCSDIntersection` 面，不校验该面是否能落到 RCSD semantic node。对下游 T05/T06 来说，只有能映射到 RCSDNode `id/mainnodeid` 的锚定才是可消费锚定。

## 变更

- `run_t07_step2_anchor_recognition` 增加可选 `rcsdnode_path` 输入。
- 启用 `rcsdnode_path` 后，Step2 对命中的 `RCSDIntersection` 面执行同 CRS 几何覆盖校验：
  - 面内覆盖至少一个具有可用 `id/mainnodeid` 的 RCSDNode geometry 时，保留原锚定判断。
  - 面内没有可用 RCSDNode 时，不再将该面作为成功锚定依据，代表 node 写 `is_anchor=no`。
- relation evidence 对此类失败写入 `relation_state=rcsdintersection_no_rcsd_semantic_node`、`status_suggested=1`，并保留原命中的 `matched_rcsdintersection_ids`。
- `t07_rcsdintersection_anchor_surface.gpkg` 不发布不可消费的 `RCSDIntersection` 面。
- T10 Case runner 与内网全量脚本将已有 RCSDNode 输入传给 T07 Step1/2。

## 非目标

- 不根据距离、最近点或 Segment 结果猜测 RCSDNode。
- 不修改 RCSD 原始拓扑。
- 不改变未传入 `rcsdnode_path` 时的 T07 Step2 旧行为。

## 验证

- 单元测试覆盖可消费 surface 继续成功、不可消费 surface 降级为 `is_anchor=no` 并输出可追溯 relation evidence。
- 回归测试限定为 T10 Case `991176`。
