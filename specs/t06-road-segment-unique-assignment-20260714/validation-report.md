# T06 RCSD Road—Segment 唯一分配验证报告

## 结论

状态：`passed`。

T06 最终发布规则已收紧为：每条 `source=1` F-RCSD Road 只能有一个 Segment owner 或无 owner；两个及以上 owner 直接 hard fail。`path_corridor_group` 仅表达组级原子执行/回退，不表达 Road 多 Segment 所有权。

## 已修改

- ownership ledger 新增 `special_junction_internal`，并保留 `multi_segment_connectivity` 独立关联类型。
- Segment relation 删除非 owner RCSD Road carrier，使用 `related_special_junction_internal_road_ids / related_connectivity_road_ids / connectivity_group_ids` 保存上下文。
- F-RCSD Road 与 added-road audit 统一收口为单值或空值 `t06_swsd_segment_ids`。
- 相同规则已接入 surface ownership refresh；summary 输出 single/unassigned/multi 计数。
- T06 SPEC、architecture、INTERFACE_CONTRACT 与 P02 SpecKit 已同步。

## 已验证

- ownership 聚焦测试：`3 passed`。
- Step3/特殊路口/path-corridor 定向回归：`38 passed`。
- T06 全模块：`418 passed`。
- 输出压缩与 ownership 聚焦补充：`5 passed`。
- P02 run09：58 条唯一归属、4 条无归属、0 条多归属；4 条无归属由 3 条特殊路口内部 Road 与 1 条 connectivity Road 构成。
- 原 run08 的 8 条多归属 Road：4 条收口到唯一 Segment，4 条收口为空 owner；正式最终 topology fail 为 0。
- GIS 工作层为 `EPSG:3857`，检查层几何非空/有效、非空 ID 唯一；未执行 silent fix。
- QGIS 3.40.14 LTR：56/56 图层回读有效、0 缺失数据源、0 绝对路径引用、预览渲染通过。
- 道路面与导流带缺失，in-road coverage overlay gate 明确记录为 `not_run_unavailable`。

## 待确认

- `609020493_61493884` 正式锚点通道与 SWSD 几何走廊仍有空间偏移，保留人工视觉复核标记，不影响本轮唯一归属结论。
- `521458225_600688320` 在补充 `600688320` 正式锚定前继续保持 SWSD。
