# T06 Step2 孤立挂接 RCSDRoad promotion 履历

## 2026-06-11

### 背景

T10 复测中，部分已替换的 RCSDSegment 主通道旁存在孤立挂接 RCSDRoad。此前 Step2 会把 optional junc 旁支剪除，并仅在 `lost_attach_road_ids` 中审计；Step3 因只消费 final `rcsd_road_ids`，不会把这些无冲突挂接 road 带入 F-RCSD，进而影响后续 T09 对路口进入 / 退出 carrier 的识别。

### 根因

原规则只区分主 corridor 与被剪除 optional junc 旁支，没有在 final replaceable 集合层面判断挂接 road 是否可以安全随主 Segment 替换。对“一个端点为断头、且不与其它 Segment 替换冲突”的挂接 road，现有输出过于保守。

### 业务逻辑变更

- Step2 保留 `retained_rcsd_road_ids` 作为主 corridor 审计，不混入旁支。
- Step2 在 special junction gate 后、写出 final replaceable 前，对 final replaceable 集合执行全局无冲突 promotion。
- `lost_attach_road_ids` 中的 RCSDRoad 只有在未被其它 replaceable Segment 主通道占用，且未被多个 replaceable Segment 同时申请时，才追加到当前 Segment 的 final `rcsd_road_ids`。
- 新增审计字段 `promoted_attach_road_ids / blocked_attach_road_ids / attach_promotion_status / attach_promotion_reason`，用于区分已随主 Segment 替换与因冲突阻断的挂接 road。
- 不使用新增数据字段，不根据局部样本反推属性含义；promotion 完全基于既有拓扑候选关系与 final replaceable 集合冲突检查。

### 验证记录

- 新增单测覆盖无冲突挂接 road promotion：final `rcsd_road_ids` 包含主 corridor road 与 promoted attach road，`retained_rcsd_road_ids` 仍仅保留主 corridor。
- 新增单测覆盖两个 replaceable Segment 争用同一挂接 road：不执行 promotion，并在 `blocked_attach_road_ids` 与 summary 统计中记录冲突。

