# 12 术语表

- `T08`：项目正式预处理模块。
- `Tool1`：基础矢量格式转换工具，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON。
- `Tool2`：Road 数据预处理工具。
- `Tool3`：Nodes 类型聚合工具。
- `Tool4`：路口类型修复工具，输出完整 Nodes、可选 Roads 与 audit Nodes。
- `Tool5`：复杂路口预处理工具，构建复杂分歧 / 合流路口并处理错误 1 对多路口。
- `Tool6`：Nodes 类型质检工具，输出人工质检 CSV 与 `node_error_tool6.gpkg`，不执行修复。
- `Tool7`：交通限制显性化工具，读取 SW C 表与 SW Road 并输出显性 restriction LineString。
- `C 表`：SW 原始交通限制表；Tool7 当前使用 `CondType / inLinkID / outLinkID` 字段。
- `restriction`：Tool7 输出的显性交通限制记录，属性继承 C 表业务字段，几何由 inLink / outLink 拼接或直线连接构成。
- `patch_id`：Patch 归属字段。
- `kind`：从原始 Road 图层继承的道路种别字段；作为 Road 字段时，单个 token 为 `XXXX`，前两位为道路等级，后两位为道路类型，多个道路种别用 `|` 分隔。
- `辅路 Road`：`road.kind` 任一 token 后两位为 `0a` 的 Road，大小写不敏感。
- `kind_2 / grade_2`：Nodes copy-on-write 输出中的工作类型字段。
- `是否修复`：Tool6 CSV 最后一列，默认 `1`，人工确认不需要修复的数据改为 `0` 后供 Tool4 后续修复流程消费。
