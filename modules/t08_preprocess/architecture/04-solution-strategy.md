# 04 方案策略

## Tool1

Tool1 使用参数化 SHP / GeoJSON / GPKG 列表作为输入，逐个流式读取、可选重投影，并将输出写回输入目录下的同名目标格式文件：SHP / GeoJSON 输出 GPKG，GPKG 输出 GeoJSON。命令脚本会输出单文件开始、定量要素转换进度、结束与失败信息。

## Tool2

Tool2 分两步执行：

1. Patch join：按 `road.id = patch_road.road_id` 为 Road 写入 `patch_id`，未命中记录写入 unmatched 图层。
2. Kind enrich：对 Patch join 输出和原始 Kind Road 统一投影到 `EPSG:3857` 后执行空间匹配，写入 `kind`。

## Tool3

Tool3 先将 Nodes `kind / grade` 复制到 `kind_2 / grade_2`，再执行两类拓扑聚合：

1. Roundabout aggregation：参考 T01，使用 `roadtype bit3` Road 连通组识别环岛，组内最小 Node `id` 作为 mainnode。
2. Complex divmerge aggregation：参考 T04/T02 连续分歧 / 合流链路，沿 Road 有向拓扑聚合 representative `kind_2 in {8,16}` 候选，聚合主节点写为 `kind_2 = 128`。

## 输出策略

- Tool1 输出同目录同名目标格式文件与 summary。
- Tool2 输出三个 GPKG 与三个 summary。
- Tool3 输出一个 copy-on-write Nodes GPKG 与 summary，不输出或改写 Roads。
- 所有路径由命令参数提供。
