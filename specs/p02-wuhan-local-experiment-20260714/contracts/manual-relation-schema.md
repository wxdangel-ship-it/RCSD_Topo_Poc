# P02 人工关系落盘契约

## 1. T11 可消费字段

CSV 字段顺序固定为：

```text
case_id,swsd_segment_id,target_id,manual_relation_type,selected_ids,comment,source_manual_table,source_manual_xlsx
```

## 2. 值域

- RCSDNode：`manual_relation_type=1v1_rcsd_junction`。
- RCSDRoad：单 Road 使用 `manual_relation_type=1v1_rcsd_road`，多 Road 使用 `manual_relation_type=1vN_rcsd_road`。
- `selected_ids` 使用文本保存长 ID；多 ID 时用 `|` 分隔。本批次 `521458225` 为 `5855295910117425|5855295910117512`，`612028267` 为 `5855295910117438|5855296278768745`。
- `selected_ids` 不允许为空或 `NULL`。
- `target_id` 在 raw 文件中为用户原始 ID，在 converted 文件中为 Tool5 后 canonical ID。

## 3. 文件分层

- `p02_manual_relations_raw.csv`：不可变人工源事实。
- `p02_manual_relations_converted.csv`：T05 消费文件。
- 多个 raw target 转为同一 canonical target 时，同对象类别 selected ID 按来源顺序并集；并集数量大于 1 时关系类型升级为对应 `1vN_*`。
- junction 与 road 跨对象类别落到同一 canonical target 时阻断，不生成 converted 文件。
- `p02_manual_relation_transform_audit.csv`：逐行 lineage。
- `p02_manual_relation_transform_summary.json`：数量、冲突和缺失汇总。

## 4. 阻断条件

- raw target 不存在于 Tool5 最终 Nodes。
- 同一 canonical target 出现不同 `manual_relation_type` 或不同 `selected_ids`。
- selected RCSDNode/RCSDRoad 在原始输入中不存在。
- 输出出现同一 target 多条可执行关系。
