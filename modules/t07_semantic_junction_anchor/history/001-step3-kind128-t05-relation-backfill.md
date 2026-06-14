# T07 Step3 kind_2=128 T05 relation 补锚

## 时间

- 2026-06-11

## 背景

T10 复测中，高等级单向 SWSD Segment 仍有一批未进入 T06 final fusion。抽查发现部分 Segment 的阻断点不是 T06 buffer 或 RCSD 连通性，而是 T07 Step3 后代表 node 仍为 `is_anchor = no`。

这些代表 node 的共同特征：

- `kind_2 = 128`。
- T07 Step2 按既有规则写为 `is_anchor = no / anchor_reason = NULL`。
- T05 `intersection_match_all.geojson` 已发布 `status = 0 / base_id != 0` 成功 relation。
- T06 Step1 仅消费 T07 Step3 后的 `nodes.gpkg`，因此无法看到 T05 成功 relation，导致关联 Segment 未进入 final fusion。

## 根因

T07 Step3 的 T05 relation backfill 范围仅包含 `kind_2 in {4,8,16}`。`kind_2 = 128` 虽然已由 T04/T05 专项链路产出最终 relation，但 Step3 未将该 relation 回写为代表 node anchor，造成 T05 relation 与 T06 Step1 handoff 之间的信息断链。

## 业务变更

- T07 Step2 规则不变：`kind_2 = 128` 仍先写 `is_anchor = no / anchor_reason = NULL`。
- T07 Step3 的 Step2 surface 1V1 推导范围不变，仍为 `kind_2 in {4,8,16}`。
- T07 Step3 的 T05 relation backfill 候选扩展为 `kind_2 in {4,8,16,128}`。
- `kind_2 = 128` 只允许在以下条件全部满足时补写 anchor：
  - 代表 node `has_evd = yes`。
  - 代表 node `is_anchor = no`。
  - T05 `intersection_match_all.geojson` 中存在 `status = 0 / base_id != 0` relation。
  - `base_id` 存在于输入 `RCSDNode.id/mainnodeid`。
  - 未被 Step2 surface 1V1 阶段占用，且最终 relation 通过 T05 同口径基数质检。

## 非目标

- 不把 `fail1 / fail2` 直接改写为成功 anchor。
- 不处理 `kind_2 = 64`。
- 不改变 `kind_2 = 2048` 交由 T03 虚拟锚定的边界。
- 不根据局部几何或样本反推字段含义。

## 影响

T07 Step3 能把 T04/T05 已确认的 `kind_2=128` 成功 relation 传递给 T06 Step1，减少 T06 因 anchor handoff 断链导致的漏候选。
