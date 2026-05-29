# 03 上下文与范围

## 当前上下文

T00 Tool4 / Tool5 已有 Road `patch_id / kind` 补充能力，但 T00 是工具集合模块。T08 将这些预处理能力收口为项目正式数据链路的一部分，并提供参数化内网脚本。

## 当前范围

- Tool1：基础矢量格式转换，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON。
- Tool2：Road GPKG 输入，补充 `patch_id` 和 `kind`，删除 `kind` 具有 `17` 主辅路出入口属性的 Road 并输出事件 Road，输出 `EPSG:3857` GPKG。
- Tool3：Nodes GPKG 输入，补充 `kind_2 / grade_2`，并按 Road 拓扑聚合环岛 mainnode，输出 `EPSG:3857` Nodes GPKG。
- Tool4：Nodes/Roads GPKG 输入，识别并修复错误 T 型路口、分合流一入一出类型，并可消费 Tool6 人工确认成果，copy-on-write 输出 `EPSG:3857` Nodes/可选 Roads/audit Nodes GPKG。
- Tool5：Nodes/Roads GPKG 输入，构建复杂分歧 / 合流路口，并可基于 `RCSDIntersection` 识别和处理错误 1 对多路口，copy-on-write 输出 `EPSG:3857` Nodes/Roads/audit Nodes GPKG。
- Tool6：Nodes/Roads GPKG 输入，执行 Nodes 类型质检，输出人工质检 CSV 与 `node_error_tool6.gpkg`，不改写输入 Nodes/Roads。
- Tool7：SW C 表 / SW Node / SW Road GPKG 输入，筛选 `CondType=1` 且 in/out Link 均存在于 SW Road 的记录，输出显性 restriction LineString GPKG。

所有 T08 成果输出文件名均在扩展名前以 `_toolX` 结尾，`X` 为工具编号。

## 当前范围外

- Tool5 以外的自动 Node 修复。
- repo CLI 子命令。
- `tools/` 命令。
- `Makefile` 目标。
