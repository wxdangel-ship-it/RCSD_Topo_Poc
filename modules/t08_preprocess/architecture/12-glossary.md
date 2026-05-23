# 12 术语表

- `T08`：项目正式预处理模块。
- `Tool1`：基础矢量格式转换工具，支持 SHP / GeoJSON 转 GPKG 与 GPKG 转 GeoJSON。
- `Tool2`：Road 数据预处理工具。
- `Tool3`：Nodes 类型聚合工具。
- `Tool4`：T 型路口错误修复工具，输出完整 Nodes 与 audit Nodes。
- `Tool5`：复杂路口预处理工具，构建复杂分歧 / 合流路口并处理错误 1 对多路口。
- `patch_id`：Patch 归属字段。
- `kind`：从原始 Road 图层继承的道路种别字段；作为 Road 字段时，单个 token 为 `XXXX`，前两位为道路等级，后两位为道路类型，多个道路种别用 `|` 分隔。
- `辅路 Road`：`road.kind` 任一 token 后两位为 `0a` 的 Road，大小写不敏感。
- `kind_2 / grade_2`：Nodes copy-on-write 输出中的工作类型字段。
