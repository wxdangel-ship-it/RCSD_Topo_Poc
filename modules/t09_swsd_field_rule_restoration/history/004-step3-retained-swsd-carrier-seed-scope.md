# 004 - Step3 retained SWSD carrier seed scope

## 时间

2026-06-11

## 背景

T10 `1885118` 在 T07 kind_2=128 补锚后，T06 替换结果使部分 F-RCSD Node 不再保留旧 SWSD 主子节点 alias 行。T09 Step3 复跑时，一个 SWSD u-turn movement 的旧版 `frcsd_restriction` 少了两条以同 Segment 其他 Arm road 为 `LinkID` 的输出。

进一步对比发现，T06 Segment relation 本身没有丢失该 road；差异来自 T09 Step3 对 `relation_status=retained_swsd` 的 source=2 road 选择过宽：只要同属一个 Segment relation 且端点命中 junction alias，就会被加入当前 Arm carrier，未继续校验该 road 是否属于当前 Arm 的 `approach_road_ids` / `exit_road_ids`。

## 业务变更

- `relation_status=retained_swsd` 且 `source=2` 的 relation road，只有当 road id 属于当前 Arm 的 `approach_road_ids` 时，才可作为该 Arm 的 F-RCSD approach carrier。
- `relation_status=retained_swsd` 且 `source=2` 的 relation road，只有当 road id 属于当前 Arm 的 `exit_road_ids` 时，才可作为该 Arm 的 F-RCSD exit carrier。
- 仍保留既有 `retained_swsd_seed_fallback`：未进入 Segment relation 的 Arm seed road 只有在 T06 F-RCSD Road 输出中以 `source=2` 存在，并可按 SWSD junction alias 与 road direction 解释时，才补充为 carrier，并输出风险标记。

## 影响范围

- 只影响 T09 Step3 `frcsd_restriction` 的 retained SWSD carrier 选择。
- 不改变 Step1/Step2 restriction 证据还原。
- 不改变 T06 relation、F-RCSD Road/Node 输入。
- 预期减少同一 retained Segment 内跨 Arm road 被错误笛卡尔积到当前 Movement 的误输出。

## 质量与审计

- 新增单元测试覆盖同一 retained SWSD Segment relation 内存在多个 Arm road 时，Step3 只输出当前 Arm seed road 对应的 restriction。
- 输出仍保留 `movement_id`、Arm id、supporting evidence、T06 relation status、source 与风险字段，支持追溯。
