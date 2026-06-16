# 2026-06-16 T06 特殊路口组门控承认 path-corridor group 覆盖

## 背景

T10/T05 反馈迭代后，部分失败 Segment 会在 T06 Step2 中通过 `path_corridor_group` 形成组级替换 action。此前特殊路口组门控只检查普通 `t06_rcsd_segment_replaceable`，未把同一轮已经通过 `T06_path_corridor_group_replacement` 的覆盖 Segment 纳入组完整性判断，导致上游聚合增强后反而误删同组内原本已成功的特殊路口双向 Segment。

## 业务变更

- `special_junction_gate` 新增 `additional_replaceable_segment_ids` 口径，用于表达同一轮 Step2 已由正式组级 action 覆盖的关联 Segment。
- Step2 在特殊路口组 gate 前先生成一次 group replacement audit，并从 `group_probe_status=passed` 且 `group_probe_repair_owner=T06_path_corridor_group_replacement` 的行提取 `path_corridor_group_segment_ids`。
- 特殊路口组完整性判断同时承认普通 replaceable Segment 与上述 path-corridor group 覆盖 Segment；但后者不写入普通 replaceable 白名单，仍由 replacement plan 的 `execution_scope=path_corridor_group` 交给 Step3 执行。
- 若特殊路口组仍不完整，移除范围仍只限普通 replaceable Segment，避免把组级覆盖 Segment 误当成普通 Step2 replaceable 删除。

## 预期效果

上游虚拟路口聚合增强后，T06 不再因为同组部分 Segment 从普通替换转为组级替换而造成已成功替换 Segment 的业务回退。
