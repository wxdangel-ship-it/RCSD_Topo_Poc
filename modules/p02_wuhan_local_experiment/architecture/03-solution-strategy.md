# 03 方案策略

1. Tool1 将四个指定 GeoJSON 转为 GPKG。
2. 按 Tool3→Tool6→Tool4→Tool5 处理 SWSD；Tool6 本批次由用户授权直接进入 Tool4。
3. 原始人工关系先按 T11 八字段落盘；1vN RCSDRoad 以同一行 `selected_ids=A|B` 表达。
4. Tool5 后使用有效 `mainnodeid`，无有效值时使用 `id`，生成 canonical target。
5. 同 canonical target、同对象类别时合并 selected ID 并按数量升级 1vN；完全重复关系去重；junction/road 跨对象类别冲突阻断。
6. Tool1 后、T05 前按 `endpoint_overrides/p02_confirmed_endpoint_overrides.csv` 生成完整 RCSDRoad copy-on-write 工作副本；当前逐项强校验并执行 9 项用户确认覆盖，不读取 `NodeLid/CrossLid`，不在运行时执行几何匹配，不改变 Road 数量、ID 或几何。
7. T05 使用 converted CSV、完整 RCSDNode 与上述 RCSDRoad 工作副本发布 relation；其它缺失端点只审计，不从输入删除 Road。
7. T01/T06 分别生成 Segment 与 F-RCSD，最终按多层 funnel 和 topology audit 收口。
8. T06 只执行 Step2 replacement plan；没有正式锚定关系或未通过硬审计的 Segment 保留 SWSD。
9. 正式内网入口从四个原始 GeoJSON 新建 run root，按上述顺序执行并对当前武汉计数、关键 Segment、Road 唯一归属和正式拓扑结果做硬校验。
10. 通过 QGIS Python 从已校验 run root 重新打包数据并生成相对 datasource 的 `.qgz`；必须执行工程回读、图层有效性、XML 与 datasource 路径校验。
