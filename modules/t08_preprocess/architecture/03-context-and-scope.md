# 03 上下文与范围

## 当前上下文

T00 Tool4 / Tool5 已有 Road `patch_id / kind` 补充能力，但 T00 是工具集合模块。T08 将这些预处理能力收口为项目正式数据链路的一部分，并提供参数化内网脚本。

## 当前范围

- Tool1：基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON。
- Tool2：Road GPKG 输入，补充 `patch_id` 和 `kind`，输出 `EPSG:3857` GPKG。
- Tool3：Nodes GPKG 输入，补充 `kind_2 / grade_2`，并按 Road 拓扑聚合环岛与复杂分歧 / 合流 mainnode，输出 `EPSG:3857` Nodes GPKG。

## 当前范围外

- Tool3 以外的 Node 预处理。
- repo CLI 子命令。
- `tools/` 命令。
- `Makefile` 目标。
